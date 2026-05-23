import logging
from core.models import DeploymentJob, DeploymentPlan, DeploymentNode, AuditLog
from plugin_framework.registry import registry
from plugin_framework.base import TaskContext
from cfg_engine.dag import build_dag, reverse_topological_order

logger = logging.getLogger(__name__)


def orchestrate_rollback(plan_id: str):
    """Orchestrate rollback for all completed nodes in reverse topological order."""
    plan = DeploymentPlan.objects.get(id=plan_id)
    if plan.status == DeploymentPlan.Status.ROLLED_BACK:
        return

    # Gather nodes that need rollback: only SUCCESS nodes
    success_jobs = DeploymentJob.objects.filter(
        plan=plan, status=DeploymentJob.Status.SUCCESS
    ).select_related("node", "plugin")

    if not success_jobs.exists():
        plan.status = DeploymentPlan.Status.ROLLED_BACK
        plan.save(update_fields=["status"])
        return

    # Build DAG from stored topology or from plan nodes
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
        # If DAG fails, just roll back all success jobs
        for job in success_jobs:
            _rollback_job(job)
        plan.status = DeploymentPlan.Status.ROLLED_BACK
        plan.save(update_fields=["status"])
        return

    reverse_order = reverse_topological_order(dag)

    for node_id in reverse_order:
        try:
            job = success_jobs.get(node__target_id=node_id)
        except DeploymentJob.DoesNotExist:
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


def _rollback_job(job):
    job.status = DeploymentJob.Status.ROLLING_BACK
    job.save(update_fields=["status"])

    plugin = registry.get(job.plugin.name)
    if plugin is None:
        job.status = DeploymentJob.Status.ROLLED_BACK
        job.save(update_fields=["status"])
        return

    connector_type = job.parameters.get("_connector_type", "ssh")
    creds = job.parameters.get("admin_creds", job.parameters.get("credentials", {}))
    target = job.parameters.get("management_ip", "")

    if connector_type == "ssh":
        from plugin_framework.connectors.ssh import SSHConnector
        connector = SSHConnector(target, creds)
    elif connector_type == "telnet":
        from plugin_framework.connectors.telnet import TelnetConnector
        connector = TelnetConnector(target, creds)
    else:
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
                job.result_log["rollback"] = {"output": result.output, "message": result.message}
    except Exception as e:
        job.result_log["rollback_error"] = str(e)

    job.status = DeploymentJob.Status.ROLLED_BACK
    job.save(update_fields=["status", "result_log"])
