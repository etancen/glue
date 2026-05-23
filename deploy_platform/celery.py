"""Celery 应用配置 — 异步任务队列的入口，自动发现所有 @shared_task 装饰的任务。"""
import os
from celery import Celery

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "deploy_platform.settings")

app = Celery("deploy_platform")
# 从 Django settings 中以 CELERY_ 为前缀读取配置项（broker、backend、序列化器等）
app.config_from_object("django.conf:settings", namespace="CELERY")
# 自动扫描各 app 下 tasks.py 中的 @shared_task 任务
app.autodiscover_tasks()
