from rest_framework import serializers
from core.models import (
    User, DeploymentPlan, DeploymentNode, DeploymentJob, Plugin, AuditLog
)


class UserSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ("id", "username", "role", "is_active")
        read_only_fields = ("id",)


class DeploymentNodeSerializer(serializers.ModelSerializer):
    class Meta:
        model = DeploymentNode
        fields = ("id", "plan", "node_type", "target_id", "dependencies", "config_params")
        read_only_fields = ("id", "plan")


class DeploymentJobSerializer(serializers.ModelSerializer):
    node_target_id = serializers.CharField(source="node.target_id", read_only=True)
    plugin_name = serializers.CharField(source="plugin.name", read_only=True)

    class Meta:
        model = DeploymentJob
        fields = (
            "id", "plan", "node", "node_target_id", "plugin", "plugin_name",
            "status", "parameters", "result_log", "retry_count",
            "started_at", "finished_at",
        )
        read_only_fields = ("id", "plan", "node", "plugin", "celery_task_id")


class DeploymentPlanSerializer(serializers.ModelSerializer):
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
        validated_data["created_by"] = self.context["request"].user
        return super().create(validated_data)


class DeploymentPlanListSerializer(serializers.ModelSerializer):
    """Lightweight serializer for list view — excludes cfg_content and nested data."""
    created_by_username = serializers.CharField(source="created_by.username", read_only=True)
    node_count = serializers.SerializerMethodField()

    class Meta:
        model = DeploymentPlan
        fields = ("id", "name", "status", "created_by_username", "node_count", "created_at", "started_at", "finished_at")

    def get_node_count(self, obj):
        return obj.nodes.count()


class PluginSerializer(serializers.ModelSerializer):
    class Meta:
        model = Plugin
        fields = ("id", "name", "version", "manifest", "is_active")


class AuditLogSerializer(serializers.ModelSerializer):
    class Meta:
        model = AuditLog
        fields = ("id", "user", "action", "target_plan", "detail", "timestamp")
