"""
RBAC 权限类：基于用户 role 字段的细粒度接口访问控制。

- IsAdmin: 仅 admin 角色可访问
- IsOperatorOrAdmin: operator 和 admin 角色可访问
两段式权限：先验证 is_authenticated，再检查 role，避免非认证用户访问。
"""

from rest_framework.permissions import BasePermission
from core.models import User


class IsAdmin(BasePermission):
    """仅允许 admin 角色用户访问。

    适用场景：插件扫描、Worker 状态查询等系统管理接口。
    """
    def has_permission(self, request, view):
        return request.user.is_authenticated and request.user.role == User.Role.ADMIN


class IsOperatorOrAdmin(BasePermission):
    """允许 operator 和 admin 角色用户访问。

    适用场景：计划创建、修改、删除等写操作接口。
    readonly 用户和匿名用户均被拒绝。
    """
    def has_permission(self, request, view):
        return request.user.is_authenticated and request.user.role in (User.Role.ADMIN, User.Role.OPERATOR)
