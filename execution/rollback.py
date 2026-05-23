"""回滚编排器 — 当部署计划中任一 Job 失败时，按逆拓扑顺序回滚已成功的节点。

回滚策略：
  范围：仅回滚状态为 SUCCESS 的 Job（不触碰 PENDING/QUEUED/FAILED）
  顺序：逆拓扑排序 — 先回滚下游消费者，再回滚上游生产者
  原理：下游依赖上游，回滚先撤下游不会破坏未回滚节点的依赖关系

回滚失败不回滚：单个 Job 回滚异常只记录到 result_log，不阻断后续 Job 的回滚流程。
"""
import logging
from core.models import DeploymentJob, DeploymentPlan, DeploymentNode, AuditLog
from plugin_framework.registry import registry
from plugin_framework.base import TaskContext
from cfg_engine.dag import build_dag, reverse_topological_order

logger = logging.getLogger(__name__)


def orchestrate_rollback(plan_id: str):
    """编排计划级回滚 — 收集所有成功 Job，按逆拓扑顺序依次回滚。

    副作用：更新 Job 状态（→ ROLLING_BACK → ROLLED_BACK）、
    更新 Plan 状态（→ ROLLED_BACK）、创建 AuditLog。

    若 DAG 构建失败（如数据损坏），降级为直接遍历所有成功 Job 回滚。
    """
    logger.info("Rollback start: plan_id=%s", plan_id)
    plan = DeploymentPlan.objects.get(id=plan_id)
    if plan.status == DeploymentPlan.Status.ROLLED_BACK:
        logger.info("Plan %s already rolled back, skipping", plan_id)
        return

    # 仅回滚成功部署的节点 — 未执行的节点不需要回滚
    success_jobs = DeploymentJob.objects.filter(
        plan=plan, status=DeploymentJob.Status.SUCCESS
    ).select_related("node", "plugin")
    success_count = success_jobs.count()
    logger.info("Plan %s: %d success job(s) to roll back", plan_id, success_count)

    if not success_jobs.exists():
        logger.info("Plan %s: no success jobs to roll back, marking ROLLED_BACK directly", plan_id)
        plan.status = DeploymentPlan.Status.ROLLED_BACK
        plan.save(update_fields=["status"])
        return

    # 从 plan.nodes 重构 DAG，获取正确的拓扑顺序
    nodes_data = []
    for node in plan.nodes.all():
        nodes_data.append({
            "id": node.target_id,
            "node_type": node.node_type,
            "depends_on": node.dependencies,
        })
    try:
        dag = build_dag(nodes_data)
    except Exception:
        # DAG 构建失败时的降级策略：直接遍历所有成功 Job 回滚
        logger.warning("Plan %s: DAG build failed during rollback, rolling back all %d job(s) directly", plan_id, success_count)
        for job in success_jobs:
            _rollback_job(job)
        plan.status = DeploymentPlan.Status.ROLLED_BACK
        plan.save(update_fields=["status"])
        return

    # 逆拓扑排序：下游先回滚，上游后回滚 — 确保被依赖者最后撤销
    reverse_order = reverse_topological_order(dag)
    logger.info("Plan %s: reverse topological rollback order: %s", plan_id, reverse_order)

    for node_id in reverse_order:
        try:
            job = success_jobs.get(node__target_id=node_id)
        except DeploymentJob.DoesNotExist:
            logger.info("Plan %s: node '%s' not in success jobs, skipping rollback", plan_id, node_id)
            continue
        _rollback_job(job)

    AuditLog.objects.create(
        user=plan.created_by,
        action="rollback_completed",
        target_plan=plan,
        detail={"reversed_nodes": reverse_order},
    )

    plan.status = DeploymentPlan.Status.ROLLED_BACK
    plan.save(update_fields=["status"])
    logger.info("Rollback complete: plan_id=%s rolled_back=%d node(s)", plan_id, success_count)


def _rollback_job(job):
    """执行单个 Job 的回滚 — 获取插件、构建连接器、调用 plugin.rollback()。

    回滚异常不向上传播：单个回滚失败记录到 result_log.rollback_error，
    后续 Job 的回滚继续执行，确保整个计划的回滚不被某个节点阻断。
    """
    logger.info("Rolling back job: job_id=%s node=%s plugin=%s", job.id, job.node.target_id, job.plugin.name)
    job.status = DeploymentJob.Status.ROLLING_BACK
    job.save(update_fields=["status"])

    plugin = registry.get(job.plugin.name)
    if plugin is None:
        logger.warning("Job %s: plugin '%s' not found, marking ROLLED_BACK without action", job.id, job.plugin.name)
        job.status = DeploymentJob.Status.ROLLED_BACK
        job.save(update_fields=["status"])
        return

    connector_type = job.parameters.get("_connector_type", "ssh")
    creds = job.parameters.get("admin_creds", job.parameters.get("credentials", {}))
    target = job.parameters.get("management_ip", "")

    logger.info("Job %s rollback: building connector type=%s target=%s", job.id, connector_type, target)
    if connector_type == "ssh":
        from plugin_framework.connectors.ssh import SSHConnector
        connector = SSHConnector(target, creds)
    elif connector_type == "telnet":
        from plugin_framework.connectors.telnet import TelnetConnector
        connector = TelnetConnector(target, creds)
    else:
        logger.warning("Job %s rollback: unsupported connector_type=%s", job.id, connector_type)
        connector = None

    ctx = TaskContext(
        job_id=str(job.id),
        plan_id=str(job.plan_id),
        node_id=job.node.target_id,
        logger=logger,
    )

    try:
        if connector:
            with connector:
                result = plugin.rollback(job.parameters, connector, ctx)
                job.result_log = job.result_log or {}
                job.result_log["rollback"] = {"output": result.output, "message": result.message}
                logger.info("Job %s rollback result: success=%s message=%s", job.id, result.success, result.message)
    except Exception as e:
        # 单个回滚异常记录但不中断，继续回滚后续 Job
        logger.exception("Job %s rollback: exception — %s", job.id, e)
        job.result_log = job.result_log or {}
        job.result_log["rollback_error"] = str(e)

    job.status = DeploymentJob.Status.ROLLED_BACK
    job.save(update_fields=["status", "result_log"])
    logger.info("Job %s rollback complete: status=%s", job.id, job.status)
