from django.apps import AppConfig


class LedgerConfig(AppConfig):
    """Django application configuration for LedgerSync's domain."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "ledger"
