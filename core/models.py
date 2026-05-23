"""
Glue 核心数据模型。

定义了部署平台的所有核心实体：用户、部署计划、部署节点、
插件注册表、部署作业和审计日志，以及对应的状态机。
"""

import uuid
from django.contrib.auth.models import AbstractUser
from django.db import models


class User(AbstractUser):
    """扩展 Django 用户模型，增加 RBAC 角色字段。

    三种角色：admin（全权限）、operator（操作权限）、readonly（只读）。
    新用户默认为 readonly 角色，遵循最小权限原则。
    """
    class Role(models.TextChoices):
        ADMIN = "admin"
        OPERATOR = "operator"
        READONLY = "readonly"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    role = models.CharField(max_length=20, choices=Role.choices, default=Role.READONLY)

    def __str__(self):
        return f"{self.username} ({self.role})"


class DeploymentPlan(models.Model):
    """部署计划：顶层编排单元，包含拓扑结构和配置模板。

    状态机流转：DRAFT → VALIDATED → QUEUED → RUNNING → COMPLETED/FAILED，
    失败后可手动回滚至 ROLLED_BACK。
    """
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
    """部署节点：计划中的单个部署目标，有拓扑依赖关系和参数覆盖。

    每个节点对应一个物理/虚拟设备，节点间通过 dependencies 声明执行顺序。
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    plan = models.ForeignKey(DeploymentPlan, on_delete=models.CASCADE, related_name="nodes")
    node_type = models.CharField(max_length=100)
    target_id = models.CharField(max_length=255)
    # 节点间依赖列表，确保拓扑顺序执行
    dependencies = models.JSONField(default=list)
    config_params = models.JSONField(default=dict)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["plan", "target_id"], name="uq_plan_target")
        ]


class Plugin(models.Model):
    """插件注册表：记录已扫描并安装的部署插件元信息。

    通过 manifest JSON 字段存储插件的完整能力声明，is_active 控制可用性。
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=255, unique=True)
    version = models.CharField(max_length=50)
    plugin_dir_path = models.CharField(max_length=500)
    manifest = models.JSONField()
    is_active = models.BooleanField(default=True)


class DeploymentJob(models.Model):
    """部署作业：节点级执行单元，与 Celery 任务一一对应。

    状态机：PENDING → QUEUED → RUNNING → SUCCESS/FAILED，
    失败后进入 RETRYING 重新入队，或 ROLLING_BACK → ROLLED_BACK。
    """
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
    plugin = models.ForeignKey(Plugin, on_delete=models.PROTECT, related_name="jobs")
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING)
    parameters = models.JSONField(default=dict)
    result_log = models.JSONField(default=dict)
    # celery_task_id 关联 Celery 异步任务，用于任务追踪和撤销
    celery_task_id = models.CharField(max_length=255, blank=True, default="")
    retry_count = models.IntegerField(default=0)
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)


class AuditLog(models.Model):
    """审计日志：记录所有用户操作，支持事后追溯和安全审计。

    action 字段存储操作名称（如 plan.create、plan.execute），
    detail 以 JSON 记录操作上下文。
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(User, on_delete=models.PROTECT, related_name="audit_logs")
    action = models.CharField(max_length=255)
    target_plan = models.ForeignKey(DeploymentPlan, on_delete=models.SET_NULL, null=True, blank=True)
    detail = models.JSONField(default=dict)
    timestamp = models.DateTimeField(auto_now_add=True)
