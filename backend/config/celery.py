"""Celery application configuration."""

import os

from celery import Celery


# Celery needs to know which Django settings module to load.
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

# Create the Celery application with a descriptive project name.
app = Celery("ledger_sync")

# Read CELERY_* values from Django settings.
app.config_from_object("django.conf:settings", namespace="CELERY")

# Automatically discover tasks.py files inside installed Django apps.
app.autodiscover_tasks()
