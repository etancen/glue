"""
DRF 序列化器：模型 ↔ JSON 转换 + 输入校验。

每个序列化器对应一个模型，控制字段暴露范围和只读约束。
列表视图使用轻量序列化器避免传输 cfg_content 等大字段。
"""

from rest_framework import serializers
from core.models import (
    User, DeploymentPlan, DeploymentNode, DeploymentJob, Plugin, AuditLog
)


class UserSerializer(serializers.ModelSerializer):
    """用户序列化：仅暴露 id、username、role、is_active，不泄露密码等敏感字段。"""
    class Meta:
        model = User
        fields = ("id", "username", "role", "is_active")
        read_only_fields = ("id",)


class DeploymentNodeSerializer(serializers.ModelSerializer):
    """部署节点序列化：plan 只读，创建时由父计划自动关联。"""
    class Meta:
        model = DeploymentNode
        fields = ("id", "plan", "node_type", "target_id", "dependencies", "config_params")
        read_only_fields = ("id", "plan")


class DeploymentJobSerializer(serializers.ModelSerializer):
    """部署作业序列化：展平 node.target_id 和 plugin.name 便于前端展示。"""
    node_target_id = serializers.CharField(source="node.target_id", read_only=True)
    plugin_name = serializers.CharField(source="plugin.name", read_only=True)

    class Meta:
        model = DeploymentJob
        fields = (
            "id", "plan", "node", "node_target_id", "plugin", "plugin_name",
            "status", "parameters", "result_log", "retry_count",
            "started_at", "finished_at",
        )
        # celery_task_id 不对外暴露，属于内部调度信息
        read_only_fields = ("id", "plan", "node", "plugin", "celery_task_id")


class DeploymentPlanSerializer(serializers.ModelSerializer):
    """计划详情序列化器：包含完整嵌套节点和作业数据。

    create() 自动将当前用户设为 created_by，避免前端传入。
    """
    nodes = DeploymentNodeSerializer(many=True, read_only=True)
    jobs = DeploymentJobSerializer(many=True, read_only=True)
    created_by_username = serializers.CharField(source="created_by.username", read_only=True)

    class Meta:
        model = DeploymentPlan
        fields = (
            "id", "name", "cfg_content", "topology_graph", "status",
            "created_by", "created_by_username", "nodes", "jobs",
            "created_at", "started_at", "finished_at",
        )
        read_only_fields = ("id", "created_by", "topology_graph", "status", "created_at", "started_at", "finished_at")

    def create(self, validated_data):
        """创建时自动注入当前请求用户为创建者。"""
        validated_data["created_by"] = self.context["request"].user
        return super().create(validated_data)


class DeploymentPlanListSerializer(serializers.ModelSerializer):
    """计划列表轻量序列化器——排除 cfg_content 和嵌套数据，仅返回摘要字段。

    列表页可能返回数百条记录，排除大字段可显著减少响应体积和查询耗时。
    """
    created_by_username = serializers.CharField(source="created_by.username", read_only=True)
    node_count = serializers.SerializerMethodField()

    class Meta:
        model = DeploymentPlan
        fields = ("id", "name", "status", "created_by_username", "node_count", "created_at", "started_at", "finished_at")

    def get_node_count(self, obj):
        """返回计划下的节点数量，用于列表摘要展示。"""
        return obj.nodes.count()


class PluginSerializer(serializers.ModelSerializer):
    """插件序列化：暴露插件名、版本、manifest 能力声明和激活状态。

    plugin_dir_path 不对外暴露，属于服务端内部路径。
    """
    class Meta:
        model = Plugin
        fields = ("id", "name", "version", "manifest", "is_active")


class AuditLogSerializer(serializers.ModelSerializer):
    """审计日志序列化：全字段只读，通过 API 仅支持查看不允许修改。"""
    class Meta:
        model = AuditLog
        fields = ("id", "user", "action", "target_plan", "detail", "timestamp")
