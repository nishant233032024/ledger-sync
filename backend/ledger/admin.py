"""Useful Django Admin registrations for local investigation."""

from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from .models import (
    AuditLog,
    Batch,
    Discrepancy,
    Organization,
    ReconciliationMatch,
    ReconciliationRule,
    ReconciliationRun,
    Transaction,
    User,
)


@admin.register(User)
class LedgerUserAdmin(UserAdmin):
    """Add organization and business role to Django's user admin."""

    fieldsets = UserAdmin.fieldsets + (
        ("LedgerSync", {"fields": ("organization", "role")}),
    )
    list_display = ("username", "organization", "role", "is_active")
    list_filter = ("role", "is_active", "organization")


@admin.register(Organization)
class OrganizationAdmin(admin.ModelAdmin):
    list_display = ("name", "slug", "is_active", "created_at")
    search_fields = ("name", "slug")


@admin.register(Batch)
class BatchAdmin(admin.ModelAdmin):
    list_display = (
        "original_filename",
        "organization",
        "source_type",
        "status",
        "total_records",
        "imported_records",
        "duplicate_records",
    )
    list_filter = ("source_type", "status", "organization")
    search_fields = ("original_filename", "checksum")


@admin.register(Transaction)
class TransactionAdmin(admin.ModelAdmin):
    list_display = (
        "transaction_reference",
        "source_type",
        "amount",
        "currency",
        "status",
        "timestamp",
    )
    list_filter = ("source_type", "status", "currency")
    search_fields = ("transaction_reference", "normalized_reference")
    list_select_related = ("organization", "batch")


@admin.register(ReconciliationRule)
class ReconciliationRuleAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "organization",
        "date_variance_days",
        "amount_tolerance_percent",
        "is_active",
    )


@admin.register(ReconciliationRun)
class ReconciliationRunAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "organization",
        "status",
        "matched_count",
        "discrepancy_count",
        "created_at",
    )
    list_filter = ("status", "organization")


@admin.register(ReconciliationMatch)
class ReconciliationMatchAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "ledger_transaction",
        "external_transaction",
        "amount_difference",
        "created_at",
    )


@admin.register(Discrepancy)
class DiscrepancyAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "discrepancy_type",
        "status",
        "primary_transaction",
        "created_at",
    )
    list_filter = ("discrepancy_type", "status", "organization")
    search_fields = ("primary_transaction__transaction_reference",)


@admin.register(AuditLog)
class AuditLogAdmin(admin.ModelAdmin):
    list_display = (
        "action",
        "entity_type",
        "entity_id",
        "actor",
        "created_at",
    )
    list_filter = ("action", "entity_type", "organization")
    readonly_fields = (
        "organization",
        "actor",
        "action",
        "entity_type",
        "entity_id",
        "payload",
        "created_at",
    )

    def has_change_permission(self, request, obj=None):
        # Audit records must be append-only from the application's perspective.
        return False

    def has_delete_permission(self, request, obj=None):
        return False
