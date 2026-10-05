"""Load the Celery application whenever Django loads the project package."""

from .celery import app as celery_app

__all__ = ("celery_app",)
