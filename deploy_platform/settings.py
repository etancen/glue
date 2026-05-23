"""Django 全局配置 — 数据库、认证、Celery、日志、插件和重试策略。

所有可调参数均支持通过环境变量覆盖，方便开发/生产环境切换。
"""
import os
from pathlib import Path
from datetime import timedelta

BASE_DIR = Path(__file__).resolve().parent.parent

# === 安全配置 ===
# SECRET_KEY 务必在生产环境通过环境变量设置，默认值仅用于开发
SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", "dev-secret-change-in-production")
DEBUG = os.environ.get("DJANGO_DEBUG", "True").lower() == "true"
ALLOWED_HOSTS = os.environ.get("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1").split(",")

# === 应用注册 ===
INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    # 第三方
    "rest_framework",              # DRF REST API 框架
    "rest_framework_simplejwt",    # JWT 认证
    "drf_spectacular",             # OpenAPI 3.0 文档自动生成
    # 项目应用
    "core",                        # 核心业务逻辑（模型、视图、权限）
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "deploy_platform.urls"

# === 模板配置 ===
# 纯 REST API 后端，不需要前端模板目录，仅保留 Django admin 所需的基础配置
TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "deploy_platform.wsgi.application"

# === 数据库配置 ===
# 开发环境使用 SQLite，生产环境使用 PostgreSQL（通过环境变量覆盖）
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": BASE_DIR / "db.sqlite3",
    }
}

# === 认证配置 ===
# 使用自定义 User 模型（core.User），支持 UUID 主键和 RBAC 角色
AUTH_USER_MODEL = "core.User"

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
]

# === 国际化 ===
LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# === DRF 配置 ===
# 全局 JWT 认证 + 分页 + OpenAPI schema
REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "rest_framework_simplejwt.authentication.JWTAuthentication",
    ],
    "DEFAULT_PERMISSION_CLASSES": [
        # 默认要求认证，仅 SystemViewSet.health 等端点显式设为 AllowAny
        "rest_framework.permissions.IsAuthenticated",
    ],
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
    "DEFAULT_PAGINATION_CLASS": "rest_framework.pagination.PageNumberPagination",
    "PAGE_SIZE": 50,
}

# === JWT 配置 ===
# access token 1 小时有效，refresh token 7 天有效
# ROTATE_REFRESH_TOKENS=True：每次刷新时换发新 refresh token，减少被盗用风险
SIMPLE_JWT = {
    "ACCESS_TOKEN_LIFETIME": timedelta(hours=1),
    "REFRESH_TOKEN_LIFETIME": timedelta(days=7),
    "ROTATE_REFRESH_TOKENS": True,
}

# === Celery 异步任务队列配置 ===
# broker 和 result backend 均使用 Redis，任务序列化统一为 JSON
CELERY_BROKER_URL = os.environ.get("CELERY_BROKER_URL", "redis://localhost:6379/0")
CELERY_RESULT_BACKEND = os.environ.get("CELERY_RESULT_BACKEND", "redis://localhost:6379/0")
CELERY_ACCEPT_CONTENT = ["json"]
CELERY_TASK_SERIALIZER = "json"
CELERY_RESULT_SERIALIZER = "json"
CELERY_TIMEZONE = "UTC"

# === 插件系统配置 ===
# PLUGINS_DIR 指定插件扫描目录，通过环境变量可指向不同路径
PLUGINS_DIR = os.environ.get("PLUGINS_DIR", str(BASE_DIR / "plugins_dir"))

# === 重试策略 ===
# 最多重试 3 次，退避间隔递增（30s → 60s → 120s），避免瞬时故障导致虚假失败
RETRY_MAX_COUNT = 3
RETRY_BACKOFF_SECONDS = [30, 60, 120]

# === 日志配置 ===
# LOG_LEVEL 控制全局日志级别：DEBUG/INFO/WARNING/ERROR
# DJANGO_LOG_LEVEL 单独控制 Django 框架日志（默认 WARNING，避免刷屏）
# 各业务模块（plugin_framework、cfg_engine、execution、core）跟随 LOG_LEVEL
LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO")

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "verbose": {
            "format": "{levelname} {asctime} [{name}] {message}",
            "style": "{",
            "datefmt": "%Y-%m-%d %H:%M:%S",
        },
        "simple": {
            "format": "{levelname} [{name}] {message}",
            "style": "{",
        },
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "verbose",
            "level": LOG_LEVEL,
        },
    },
    "root": {
        "handlers": ["console"],
        "level": LOG_LEVEL,
    },
    "loggers": {
        "django": {
            "handlers": ["console"],
            "level": os.environ.get("DJANGO_LOG_LEVEL", "WARNING"),
            "propagate": False,
        },
        "plugin_framework": {
            "handlers": ["console"],
            "level": LOG_LEVEL,
            "propagate": False,
        },
        "cfg_engine": {
            "handlers": ["console"],
            "level": LOG_LEVEL,
            "propagate": False,
        },
        "execution": {
            "handlers": ["console"],
            "level": LOG_LEVEL,
            "propagate": False,
        },
        "core": {
            "handlers": ["console"],
            "level": LOG_LEVEL,
            "propagate": False,
        },
    },
}
