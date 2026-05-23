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

    @action(detail=True, methods=["post"])
    def execute(self, request, pk=None):
        plan = self.get_object()
        if plan.status not in (DeploymentPlan.Status.DRAFT, DeploymentPlan.Status.VALIDATED):
            return Response({"error": f"Cannot execute plan in status '{plan.status}'"}, status=400)
        orchestrate_plan(str(plan.id), str(request.user.id))
        plan.refresh_from_db()
        return Response(DeploymentPlanSerializer(plan).data)

    @action(detail=True, methods=["post"])
    def cancel(self, request, pk=None):
        plan = self.get_object()
        if plan.status not in (DeploymentPlan.Status.QUEUED, DeploymentPlan.Status.RUNNING):
            return Response({"error": f"Cannot cancel plan in status '{plan.status}'"}, status=400)
        plan.status = DeploymentPlan.Status.FAILED
        plan.save(update_fields=["status"])
        return Response(DeploymentPlanSerializer(plan).data)

    @action(detail=True, methods=["get"], url_path="jobs")
    def list_jobs(self, request, pk=None):
        plan = self.get_object()
        jobs = plan.jobs.all()
        page = self.paginate_queryset(jobs)
        if page is not None:
            return self.get_paginated_response(DeploymentJobSerializer(page, many=True).data)
        return Response(DeploymentJobSerializer(jobs, many=True).data)

    @action(detail=True, methods=["get"], url_path="jobs/(?P<job_id>[^/.]+)")
    def job_detail(self, request, pk=None, job_id=None):
        plan = self.get_object()
        job = get_object_or_404(DeploymentJob, plan=plan, id=job_id)
        return Response(DeploymentJobSerializer(job).data)

    @action(detail=True, methods=["get"], url_path="jobs/(?P<job_id>[^/.]+)/log")
    def job_log(self, request, pk=None, job_id=None):
        plan = self.get_object()
        job = get_object_or_404(DeploymentJob, plan=plan, id=job_id)
        return Response({"job_id": str(job.id), "result_log": job.result_log, "status": job.status})

    @action(detail=True, methods=["post"], url_path="jobs/(?P<job_id>[^/.]+)/retry")
    def job_retry(self, request, pk=None, job_id=None):
        plan = self.get_object()
        job = get_object_or_404(DeploymentJob, plan=plan, id=job_id)
        if job.status != DeploymentJob.Status.FAILED:
            return Response({"error": "Can only retry failed jobs"}, status=400)
        job.status = DeploymentJob.Status.RETRYING
        job.save(update_fields=["status"])
        from execution.tasks import execute_job_task
        execute_job_task.apply_async(kwargs={"job_id": str(job.id)})
        return Response(DeploymentJobSerializer(job).data)


class PluginViewSet(viewsets.GenericViewSet):
    queryset = Plugin.objects.all()
    serializer_class = PluginSerializer
    permission_classes = [IsAuthenticated]

    def list(self, request):
        plugins = Plugin.objects.all()
        return Response(PluginSerializer(plugins, many=True).data)

    @action(detail=False, methods=["post"])
    def scan(self, request):
        if request.user.role != "admin":
            return Response({"error": "Admin only"}, status=403)
        scan_and_load_plugins()
        installed = []
        for p in registry.list_all():
            obj, _ = Plugin.objects.update_or_create(
                name=p.name,
                defaults={"version": p.version, "manifest": p.manifest, "is_active": True},
            )
            installed.append(PluginSerializer(obj).data)
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
        if request.user.is_authenticated and request.user.role == "admin":
            from deploy_platform.celery import app
            stats = app.control.inspect().stats() or {}
            return Response({"workers": list(stats.keys())})
        return Response({"error": "Admin only"}, status=403)
