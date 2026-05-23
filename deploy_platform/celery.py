import os
from celery import Celery

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "deploy_platform.settings")

app = Celery("deploy_platform")
app.config_from_object("django.conf:settings", namespace="CELERY")
app.autodiscover_tasks()
