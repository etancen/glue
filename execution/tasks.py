"""Celery 异步任务模块 — 单个部署 Job 的执行、重试、失败处理与回滚触发。

核心任务 execute_job_task 的完整生命周期：
  加载 Job → 构建连接器 → plugin.deploy() → plugin.verify() →
  成功：检查计划完成 → 失败：根据异常类型决定重试/回滚

异常分类：
  RetryableError → 自动退避重试（最多 RETRY_MAX_COUNT 次，间隔递增）
  FatalError    → 立即失败，触发回滚，不重试
  Exception     → 视为未知错误，触发回滚（保留手动重试可能）
"""
import logging
from celery import shared_task
from django.utils import timezone as dj_timezone
from django.conf import settings
from core.models import DeploymentJob, DeploymentPlan, AuditLog
from plugin_framework.registry import registry
from plugin_framework.base import RetryableError, FatalError, TaskContext
from execution.rollback import orchestrate_rollback


logger = logging.getLogger(__name__)


@shared_task(bind=True, max_retries=0)
def execute_job_task(self, job_id: str):
    """Celery 任务入口 — 执行单个部署 Job 的完整流程。

    bind=True 提供 self 参数用于访问 Celery 任务控制（如重试），
    但本项目使用自定义重试机制（apply_async + countdown），而非 Celery 内建 self.retry()，
    原因是需要精细控制退避策略和状态追踪。

    max_retries=0 禁止 Celery 自动重试 — 重试由本函数手动调度。

    副作用：更新 Job 和 Plan 状态、创建 AuditLog、触发回滚编排。
    """
    logger.info("Job task start: job_id=%s", job_id)
    try:
        # select_related 预加载关联对象，避免循环中 N+1 查询
        job = DeploymentJob.objects.select_related("plan", "node", "plugin").get(id=job_id)
    except DeploymentJob.DoesNotExist:
        logger.error("Job %s not found in database", job_id)
        return

    logger.info("Job %s loaded: plan_id=%s node_id=%s plugin=%s status=%s retry_count=%d", job_id, job.plan.id, job.node.target_id, job.plugin.name, job.status, job.retry_count)

    if job.status not in (DeploymentJob.Status.PENDING, DeploymentJob.Status.QUEUED, DeploymentJob.Status.RETRYING):
        logger.info("Job %s skipped: status=%s is not in runnable states", job_id, job.status)
        return

    # 第一个 Job 启动时，将计划从 QUEUED 推进到 RUNNING
    plan = job.plan
    if plan.status == DeploymentPlan.Status.QUEUED:
        plan.status = DeploymentPlan.Status.RUNNING
        plan.save(update_fields=["status"])
        logger.info("Plan %s transitioned to RUNNING", plan.id)

    plugin_name = job.plugin.name
    plugin = registry.get(plugin_name)
    if plugin is None:
        logger.error("Job %s: plugin '%s' not found in registry", job_id, plugin_name)
        _fail_job(job, f"Plugin '{plugin_name}' not found in registry")
        _maybe_rollback_plan(plan)
        return

    # 连接器类型由 CFG 的 _connector_type 决定，默认 ssh
    connector_type = job.parameters.get("_connector_type", "ssh")
    logger.info("Job %s: building connector type=%s target=%s", job_id, connector_type, job.parameters.get("management_ip", "?"))
    connector = _build_connector(connector_type, job.parameters)
    if connector is None:
        logger.error("Job %s: cannot build connector type=%s", job_id, connector_type)
        _fail_job(job, f"Cannot build connector of type '{connector_type}'")
        _maybe_rollback_plan(plan)
        return

    ctx = TaskContext(
        job_id=str(job.id),
        plan_id=str(plan.id),
        node_id=str(job.node.target_id),
        logger=logger,
    )

    job.status = DeploymentJob.Status.RUNNING
    job.started_at = dj_timezone.now()
    job.save(update_fields=["status", "started_at"])
    logger.info("Job %s transitioned to RUNNING, executing plugin=%s deploy", job_id, plugin_name)

    try:
        with connector:
            result = plugin.deploy(job.parameters, connector, ctx)
            job.result_log = {"output": result.output, "message": result.message}
            logger.info("Job %s deploy completed: success=%s message=%s", job_id, result.success, result.message)
            if result.success:
                logger.info("Job %s: running post-deploy verification", job_id)
                verified = False
                try:
                    verified = plugin.verify(job.parameters, connector)
                except Exception:
                    verified = False
                logger.info("Job %s verification result: %s", job_id, verified)
                if verified:
                    job.status = DeploymentJob.Status.SUCCESS
                    job.finished_at = dj_timezone.now()
                    job.save(update_fields=["status", "result_log", "finished_at"])
                    logger.info("Job %s completed SUCCESS", job_id)
                    _check_plan_complete(plan)
                else:
                    logger.warning("Job %s: post-deploy verification failed", job_id)
                    _handle_failure(job, plan, "Post-deploy verification failed")
            else:
                logger.warning("Job %s: deploy returned failure — %s", job_id, result.message or "no message")
                _handle_failure(job, plan, result.message or "Deployment returned failure")
    except RetryableError as e:
        job.status = DeploymentJob.Status.RETRYING
        job.retry_count += 1
        job.result_log = {"error": str(e), "retry_count": job.retry_count}
        logger.warning("Job %s: RetryableError caught — %s — retry_count=%d/%d", job_id, e, job.retry_count, settings.RETRY_MAX_COUNT)
        if job.retry_count > settings.RETRY_MAX_COUNT:
            logger.error("Job %s: retry limit exceeded (%d > %d), marking FAILED", job_id, job.retry_count, settings.RETRY_MAX_COUNT)
            job.status = DeploymentJob.Status.FAILED
            job.finished_at = dj_timezone.now()
            job.save(update_fields=["status", "result_log", "retry_count", "finished_at"])
            _maybe_rollback_plan(plan)
        else:
            # 退避索引从 0 开始，使用 RETRY_BACKOFF_SECONDS 数组实现递增等待（30s → 60s → 120s）
            backoff_idx = min(job.retry_count - 1, len(settings.RETRY_BACKOFF_SECONDS) - 1)
            backoff = settings.RETRY_BACKOFF_SECONDS[backoff_idx]
            job.save(update_fields=["status", "result_log", "retry_count"])
            logger.info("Job %s: retrying in %ds (backoff index %d)", job_id, backoff, backoff_idx)
            execute_job_task.apply_async(kwargs={"job_id": job_id}, countdown=backoff)
    except FatalError as e:
        logger.error("Job %s: FatalError — %s", job_id, e)
        job.status = DeploymentJob.Status.FAILED
        job.result_log = {"error": str(e), "fatal": True}
        job.finished_at = dj_timezone.now()
        job.save(update_fields=["status", "result_log", "finished_at"])
        _maybe_rollback_plan(plan)
    except Exception as e:
        logger.exception("Job %s: unexpected error — %s", job_id, e)
        _handle_failure(job, plan, str(e))


def _handle_failure(job, plan, error_msg):
    """处理部署失败 — 将 Job 标记为 FAILED 并触发回滚检查。

    用于 deploy() 返回 success=False 或验证失败的情况。
    """
    logger.warning("Handling failure for job %s: %s", job.id, error_msg)
    job.status = DeploymentJob.Status.FAILED
    job.result_log = job.result_log or {}
    job.result_log["error"] = error_msg
    job.finished_at = dj_timezone.now()
    job.save(update_fields=["status", "result_log", "finished_at"])
    _maybe_rollback_plan(plan)


def _fail_job(job, error_msg):
    """直接标记 Job 失败 — 不触发回滚（用于不可恢复错误如插件缺失、连接器构造失败）。

    这种情况下 plan 中其他 job 可能也受影响，但不应因单个 job 的设施问题回滚整个计划。
    """
    logger.error("Failing job %s: %s", job.id, error_msg)
    job.status = DeploymentJob.Status.FAILED
    job.result_log = {"error": error_msg}
    job.finished_at = dj_timezone.now()
    job.save(update_fields=["status", "result_log", "finished_at"])


def _maybe_rollback_plan(plan):
    """检查计划是否需要回滚 — 任一 Job 失败时调用。

    通过回滚防止部分部署导致的环境不一致：
    已成功的节点会被逆序回滚，未执行的节点保持原样。
    """
    if plan.status == DeploymentPlan.Status.ROLLED_BACK:
        logger.info("Plan %s already rolled back, skipping rollback check", plan.id)
        return
    logger.warning("Plan %s: job failed, triggering rollback — current status=%s", plan.id, plan.status)
    plan.status = DeploymentPlan.Status.FAILED
    plan.save(update_fields=["status"])
    orchestrate_rollback(str(plan.id))


def _check_plan_complete(plan):
    """检查计划是否所有 Job 均已完成 — 若是，标记计划为 COMPLETED。

    排除状态：SUCCESS（完成）和 ROLLED_BACK（已回滚，视为终态）。
    其他任何状态（PENDING/QUEUED/RUNNING/RETRYING/FAILED）均说明未完成。
    """
    pending = DeploymentJob.objects.filter(plan=plan).exclude(
        status__in=(DeploymentJob.Status.SUCCESS, DeploymentJob.Status.ROLLED_BACK)
    )
    pending_count = pending.count()
    if pending_count == 0:
        plan.status = DeploymentPlan.Status.COMPLETED
        plan.finished_at = dj_timezone.now()
        plan.save(update_fields=["status", "finished_at"])
        logger.info("Plan %s: all jobs completed, marking COMPLETED", plan.id)
    else:
        logger.info("Plan %s: still %d pending job(s) — %s", plan.id, pending_count, [(j.id, j.status) for j in pending])


def _build_connector(connector_type: str, params: dict):
    """根据连接器类型和凭据信息动态构造连接器实例。

    支持三种连接器：ssh（paramiko）、telnet（telnetlib）、api（requests）。
    凭据优先使用 admin_creds，其次 credentials，为空则返回 None。
    management_ip 为空时无法构造连接器，返回 None。
    """
    creds = params.get("admin_creds", params.get("credentials", {}))
    target = params.get("management_ip", "")
    if not target:
        logger.warning("Cannot build connector: management_ip is empty, connector_type=%s", connector_type)
        return None

    logger.info("Building connector: type=%s target=%s auth_method=%s", connector_type, target, "key_file" if "key_file" in creds else ("token" if "token" in creds else "username" if "username" in creds else "none"))
    if connector_type == "ssh":
        from plugin_framework.connectors.ssh import SSHConnector
        return SSHConnector(target, creds)
    elif connector_type == "telnet":
        from plugin_framework.connectors.telnet import TelnetConnector
        return TelnetConnector(target, creds)
    elif connector_type == "api":
        from plugin_framework.connectors.api import APIConnector
        return APIConnector(target, creds)
    return None
