import logging
from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated, AllowAny
from django.shortcuts import get_object_or_404
from core.models import DeploymentPlan, DeploymentJob, Plugin, AuditLog
from core.serializers import (
    DeploymentPlanSerializer, DeploymentPlanListSerializer,
    DeploymentJobSerializer, PluginSerializer, AuditLogSerializer,
)
from core.permissions import IsAdmin, IsOperatorOrAdmin
from execution.orchestrator import orchestrate_plan
from plugin_framework.loader import scan_and_load_plugins
from plugin_framework.registry import registry

logger = logging.getLogger(__name__)


class DeploymentPlanViewSet(viewsets.ModelViewSet):
    queryset = DeploymentPlan.objects.prefetch_related("nodes", "jobs")

    def get_serializer_class(self):
        if self.action == "list":
            return DeploymentPlanListSerializer
        return DeploymentPlanSerializer

    def get_permissions(self):
        if self.action in ("create", "update", "partial_update", "destroy"):
            return [IsAuthenticated(), IsOperatorOrAdmin()]
        return [IsAuthenticated()]

    def list(self, request, *args, **kwargs):
        logger.info("Plan list: user=%s role=%s", request.user.username, request.user.role)
        return super().list(request, *args, **kwargs)

    def create(self, request, *args, **kwargs):
        logger.info("Plan create: user=%s data_keys=%s", request.user.username, sorted(request.data.keys()) if request.data else [])
        return super().create(request, *args, **kwargs)

    def retrieve(self, request, *args, **kwargs):
        logger.info("Plan retrieve: pk=%s user=%s", kwargs.get("pk"), request.user.username)
        return super().retrieve(request, *args, **kwargs)

    def update(self, request, *args, **kwargs):
        logger.info("Plan update: pk=%s user=%s", kwargs.get("pk"), request.user.username)
        return super().update(request, *args, **kwargs)

    def destroy(self, request, *args, **kwargs):
        logger.info("Plan destroy: pk=%s user=%s", kwargs.get("pk"), request.user.username)
        return super().destroy(request, *args, **kwargs)

    @action(detail=True, methods=["post"])
    def execute(self, request, pk=None):
        plan = self.get_object()
        logger.info("Plan execute requested: plan_id=%s status=%s user=%s", plan.id, plan.status, request.user.username)
        if plan.status not in (DeploymentPlan.Status.DRAFT, DeploymentPlan.Status.VALIDATED):
            logger.warning("Plan execute rejected: plan_id=%s status=%s (must be DRAFT or VALIDATED)", plan.id, plan.status)
            return Response({"error": f"Cannot execute plan in status '{plan.status}'"}, status=400)
        orchestrate_plan(str(plan.id), str(request.user.id))
        plan.refresh_from_db()
        logger.info("Plan execute done: plan_id=%s new_status=%s", plan.id, plan.status)
        return Response(DeploymentPlanSerializer(plan).data)

    @action(detail=True, methods=["post"])
    def cancel(self, request, pk=None):
        plan = self.get_object()
        logger.info("Plan cancel requested: plan_id=%s status=%s user=%s", plan.id, plan.status, request.user.username)
        if plan.status not in (DeploymentPlan.Status.QUEUED, DeploymentPlan.Status.RUNNING):
            logger.warning("Plan cancel rejected: plan_id=%s status=%s (must be QUEUED or RUNNING)", plan.id, plan.status)
            return Response({"error": f"Cannot cancel plan in status '{plan.status}'"}, status=400)
        plan.status = DeploymentPlan.Status.FAILED
        plan.save(update_fields=["status"])
        logger.info("Plan cancelled: plan_id=%s", plan.id)
        return Response(DeploymentPlanSerializer(plan).data)

    @action(detail=True, methods=["get"], url_path="jobs")
    def list_jobs(self, request, pk=None):
        plan = self.get_object()
        jobs = plan.jobs.all()
        logger.info("Job list: plan_id=%s job_count=%d user=%s", plan.id, jobs.count(), request.user.username)
        page = self.paginate_queryset(jobs)
        if page is not None:
            return self.get_paginated_response(DeploymentJobSerializer(page, many=True).data)
        return Response(DeploymentJobSerializer(jobs, many=True).data)

    @action(detail=True, methods=["get"], url_path="jobs/(?P<job_id>[^/.]+)")
    def job_detail(self, request, pk=None, job_id=None):
        plan = self.get_object()
        logger.info("Job detail: plan_id=%s job_id=%s user=%s", plan.id, job_id, request.user.username)
        job = get_object_or_404(DeploymentJob, plan=plan, id=job_id)
        return Response(DeploymentJobSerializer(job).data)

    @action(detail=True, methods=["get"], url_path="jobs/(?P<job_id>[^/.]+)/log")
    def job_log(self, request, pk=None, job_id=None):
        plan = self.get_object()
        logger.info("Job log: plan_id=%s job_id=%s user=%s", plan.id, job_id, request.user.username)
        job = get_object_or_404(DeploymentJob, plan=plan, id=job_id)
        return Response({"job_id": str(job.id), "result_log": job.result_log, "status": job.status})

    @action(detail=True, methods=["post"], url_path="jobs/(?P<job_id>[^/.]+)/retry")
    def job_retry(self, request, pk=None, job_id=None):
        plan = self.get_object()
        job = get_object_or_404(DeploymentJob, plan=plan, id=job_id)
        logger.info("Job retry requested: plan_id=%s job_id=%s status=%s user=%s", plan.id, job_id, job.status, request.user.username)
        if job.status != DeploymentJob.Status.FAILED:
            logger.warning("Job retry rejected: job_id=%s status=%s (must be FAILED)", job_id, job.status)
            return Response({"error": "Can only retry failed jobs"}, status=400)
        job.status = DeploymentJob.Status.RETRYING
        job.save(update_fields=["status"])
        from execution.tasks import execute_job_task
        execute_job_task.apply_async(kwargs={"job_id": str(job.id)})
        logger.info("Job re-queued for retry: job_id=%s", job.id)
        return Response(DeploymentJobSerializer(job).data)


class PluginViewSet(viewsets.GenericViewSet):
    queryset = Plugin.objects.all()
    serializer_class = PluginSerializer
    permission_classes = [IsAuthenticated]

    def list(self, request):
        logger.info("Plugin list: user=%s", request.user.username)
        plugins = Plugin.objects.all()
        return Response(PluginSerializer(plugins, many=True).data)

    @action(detail=False, methods=["post"])
    def scan(self, request):
        logger.info("Plugin scan requested: user=%s role=%s", request.user.username, request.user.role)
        if request.user.role != "admin":
            logger.warning("Plugin scan rejected: user=%s role=%s (admin required)", request.user.username, request.user.role)
            return Response({"error": "Admin only"}, status=403)
        scan_and_load_plugins()
        installed = []
        for p in registry.list_all():
            obj, _ = Plugin.objects.update_or_create(
                name=p.name,
                defaults={"version": p.version, "manifest": p.manifest, "is_active": True},
            )
            installed.append(PluginSerializer(obj).data)
        logger.info("Plugin scan complete: %d plugin(s) installed — %s", len(installed), [p["name"] for p in installed])
        return Response({"plugins": installed})


class SystemViewSet(viewsets.GenericViewSet):
    permission_classes = [AllowAny]

    @action(detail=False, methods=["get"], url_path="health")
    def health(self, request):
        from django.db import connection
        try:
            connection.ensure_connection()
            db_ok = True
        except Exception:
            db_ok = False
        return Response({"status": "ok" if db_ok else "degraded", "database": db_ok})

    @action(detail=False, methods=["get"], url_path="workers")
    def workers(self, request):
        logger.info("Workers status requested: user=%s authenticated=%s", request.user.username if request.user.is_authenticated else "anonymous", request.user.is_authenticated)
        if request.user.is_authenticated and request.user.role == "admin":
            from deploy_platform.celery import app
            stats = app.control.inspect().stats() or {}
            logger.info("Workers status: %d worker(s) — %s", len(stats), list(stats.keys()))
            return Response({"workers": list(stats.keys())})
        logger.warning("Workers status rejected: user=%s role=%s (admin required)", request.user.username if request.user.is_authenticated else "anonymous", request.user.role if request.user.is_authenticated else "N/A")
        return Response({"error": "Admin only"}, status=403)
