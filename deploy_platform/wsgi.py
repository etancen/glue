"""WSGI 入口 — 生产环境下由 gunicorn/uwsgi 加载，提供 HTTP 服务。"""
import os
from django.core.wsgi import get_wsgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "deploy_platform.settings")
application = get_wsgi_application()
