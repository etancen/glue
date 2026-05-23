import uuid
from django.contrib.auth.models import AbstractUser
from django.db import models


class User(AbstractUser):
    class Role(models.TextChoices):
        ADMIN = "admin"
        OPERATOR = "operator"
        READONLY = "readonly"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    role = models.CharField(max_length=20, choices=Role.choices, default=Role.READONLY)

    def __str__(self):
        return f"{self.username} ({self.role})"


class DeploymentPlan(models.Model):
    class Status(models.TextChoices):
        DRAFT = "draft"
        VALIDATED = "validated"
        QUEUED = "queued"
        RUNNING = "running"
        COMPLETED = "completed"
        FAILED = "failed"
        ROLLED_BACK = "rolled_back"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=255)
    cfg_content = models.JSONField()
    topology_graph = models.JSONField(null=True, blank=True)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.DRAFT)
    created_by = models.ForeignKey(User, on_delete=models.PROTECT, related_name="plans")
    created_at = models.DateTimeField(auto_now_add=True)
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]


class DeploymentNode(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    plan = models.ForeignKey(DeploymentPlan, on_delete=models.CASCADE, related_name="nodes")
    node_type = models.CharField(max_length=100)
    target_id = models.CharField(max_length=255)
    dependencies = models.JSONField(default=list)
    config_params = models.JSONField(default=dict)

    class Meta:
        unique_together = ["plan", "target_id"]


class Plugin(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=255, unique=True)
    version = models.CharField(max_length=50)
    plugin_dir_path = models.CharField(max_length=500)
    manifest = models.JSONField()
    is_active = models.BooleanField(default=True)


class DeploymentJob(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending"
        QUEUED = "queued"
        RUNNING = "running"
        SUCCESS = "success"
        FAILED = "failed"
        RETRYING = "retrying"
        ROLLING_BACK = "rolling_back"
        ROLLED_BACK = "rolled_back"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    plan = models.ForeignKey(DeploymentPlan, on_delete=models.CASCADE, related_name="jobs")
    node = models.OneToOneField(DeploymentNode, on_delete=models.CASCADE, related_name="job")
    plugin = models.ForeignKey(Plugin, on_delete=models.PROTECT)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING)
    parameters = models.JSONField(default=dict)
    result_log = models.JSONField(default=dict)
    celery_task_id = models.CharField(max_length=255, blank=True, default="")
    retry_count = models.IntegerField(default=0)
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)


class AuditLog(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(User, on_delete=models.PROTECT, related_name="audit_logs")
    action = models.CharField(max_length=255)
    target_plan = models.ForeignKey(DeploymentPlan, on_delete=models.SET_NULL, null=True, blank=True)
    detail = models.JSONField(default=dict)
    timestamp = models.DateTimeField(auto_now_add=True)
