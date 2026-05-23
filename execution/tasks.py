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
    """Execute a single deployment job. Handles retry and failure escalation."""
    try:
        job = DeploymentJob.objects.select_related("plan", "node", "plugin").get(id=job_id)
    except DeploymentJob.DoesNotExist:
        logger.error(f"Job {job_id} not found")
        return

    if job.status not in (DeploymentJob.Status.PENDING, DeploymentJob.Status.QUEUED, DeploymentJob.Status.RETRYING):
        return

    # Update plan status if first job starting
    plan = job.plan
    if plan.status == DeploymentPlan.Status.QUEUED:
        plan.status = DeploymentPlan.Status.RUNNING
        plan.save(update_fields=["status"])

    plugin_name = job.plugin.name
    plugin = registry.get(plugin_name)
    if plugin is None:
        _fail_job(job, f"Plugin '{plugin_name}' not found in registry")
        _maybe_rollback_plan(plan)
        return

    connector_type = job.parameters.get("_connector_type", "ssh")
    connector = _build_connector(connector_type, job.parameters)
    if connector is None:
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

    try:
        with connector:
            result = plugin.deploy(job.parameters, connector, ctx)
            job.result_log = {"output": result.output, "message": result.message}
            if result.success:
                verified = False
                try:
                    verified = plugin.verify(job.parameters, connector)
                except Exception:
                    verified = False
                if verified:
                    job.status = DeploymentJob.Status.SUCCESS
                    job.finished_at = dj_timezone.now()
                    job.save(update_fields=["status", "result_log", "finished_at"])
                    _check_plan_complete(plan)
                else:
                    _handle_failure(job, plan, "Post-deploy verification failed")
            else:
                _handle_failure(job, plan, result.message or "Deployment returned failure")
    except RetryableError as e:
        job.status = DeploymentJob.Status.RETRYING
        job.retry_count += 1
        job.result_log = {"error": str(e), "retry_count": job.retry_count}
        if job.retry_count > settings.RETRY_MAX_COUNT:
            job.status = DeploymentJob.Status.FAILED
            job.finished_at = dj_timezone.now()
            job.save(update_fields=["status", "result_log", "retry_count", "finished_at"])
            _maybe_rollback_plan(plan)
        else:
            backoff_idx = min(job.retry_count - 1, len(settings.RETRY_BACKOFF_SECONDS) - 1)
            backoff = settings.RETRY_BACKOFF_SECONDS[backoff_idx]
            job.save(update_fields=["status", "result_log", "retry_count"])
            execute_job_task.apply_async(kwargs={"job_id": job_id}, countdown=backoff)
    except FatalError as e:
        job.status = DeploymentJob.Status.FAILED
        job.result_log = {"error": str(e), "fatal": True}
        job.finished_at = dj_timezone.now()
        job.save(update_fields=["status", "result_log", "finished_at"])
        _maybe_rollback_plan(plan)
    except Exception as e:
        logger.exception(f"Unexpected error in job {job_id}")
        _handle_failure(job, plan, str(e))


def _handle_failure(job, plan, error_msg):
    job.status = DeploymentJob.Status.FAILED
    job.result_log = job.result_log or {}
    job.result_log["error"] = error_msg
    job.finished_at = dj_timezone.now()
    job.save(update_fields=["status", "result_log", "finished_at"])
    _maybe_rollback_plan(plan)


def _fail_job(job, error_msg):
    job.status = DeploymentJob.Status.FAILED
    job.result_log = {"error": error_msg}
    job.finished_at = dj_timezone.now()
    job.save(update_fields=["status", "result_log", "finished_at"])


def _maybe_rollback_plan(plan):
    """Check if plan should be rolled back (any job failed)."""
    if plan.status == DeploymentPlan.Status.ROLLED_BACK:
        return
    plan.status = DeploymentPlan.Status.FAILED
    plan.save(update_fields=["status"])
    orchestrate_rollback(str(plan.id))


def _check_plan_complete(plan):
    """If all jobs are SUCCESS, mark plan COMPLETED."""
    pending = DeploymentJob.objects.filter(plan=plan).exclude(
        status__in=(DeploymentJob.Status.SUCCESS, DeploymentJob.Status.ROLLED_BACK)
    )
    if not pending.exists():
        plan.status = DeploymentPlan.Status.COMPLETED
        plan.finished_at = dj_timezone.now()
        plan.save(update_fields=["status", "finished_at"])


def _build_connector(connector_type: str, params: dict):
    """Build a connector instance from job parameters."""
    creds = params.get("admin_creds", params.get("credentials", {}))
    target = params.get("management_ip", "")
    if not target:
        return None

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
