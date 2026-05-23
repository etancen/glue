"""
Django App 配置：注册 core 应用至项目。

Core 是平台最基础的应用，承载数据模型、REST API、权限和认证路由。
"""

from django.apps import AppConfig


class CoreConfig(AppConfig):
    """Glue 核心应用配置，使用 BigAutoField 作为默认主键类型。"""
    default_auto_field = "django.db.models.BigAutoField"
    name = "core"
