"""Persistent domain models for LedgerSync.

The database is the source of truth. Redis stores temporary progress data, but
all financial records, state changes, and audit evidence live in PostgreSQL.
"""

import uuid
from decimal import Decimal

from django.conf import settings
from django.contrib.auth.models import AbstractUser, UserManager
from django.core.validators import (
    FileExtensionValidator,
    MaxValueValidator,
    MinValueValidator,
)
from django.db import models


class TimeStampedModel(models.Model):
    """Reusable timestamps for mutable business entities."""

    # auto_now_add records the first insertion time.
    created_at = models.DateTimeField(auto_now_add=True)
    # auto_now refreshes whenever the model is saved.
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        # Abstract models do not create their own database table.
        abstract = True


class UUIDModel(models.Model):
    """Reusable UUID primary key for externally safe identifiers."""

    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False,
    )

    class Meta:
        abstract = True


class Organization(UUIDModel, TimeStampedModel):
    """Tenant boundary for every LedgerSync customer."""

    name = models.CharField(max_length=255)
    slug = models.SlugField(max_length=100, unique=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name


class User(AbstractUser):
    """Application user with organization membership and a business role."""

    class Role(models.TextChoices):
        ADMIN = "ADMIN", "Administrator"
        FINANCE_MANAGER = "FINANCE_MANAGER", "Finance Manager"
        AUDITOR = "AUDITOR", "Auditor"

    # Null is allowed only for a technical Django superuser created before an
    # organization exists. Application API users always belong to a tenant.
    organization = models.ForeignKey(
        Organization,
        on_delete=models.PROTECT,
        related_name="users",
        null=True,
        blank=True,
    )
    role = models.CharField(
        max_length=30,
        choices=Role.choices,
        default=Role.AUDITOR,
    )

    objects = UserManager()

    class Meta:
        indexes = [
            models.Index(
                fields=["organization", "role"],
                name="user_org_role_idx",
            ),
            models.Index(
                fields=["organization", "is_active"],
                name="user_org_active_idx",
            ),
        ]


class Batch(UUIDModel, TimeStampedModel):
    """One uploaded ERP, bank, or gateway file."""

    class SourceType(models.TextChoices):
        ERP = "ERP", "ERP Ledger"
        BANK = "BANK", "Bank Statement"
        GATEWAY = "GATEWAY", "Payment Gateway"

    class Status(models.TextChoices):
        PENDING = "PENDING", "Pending"
        PROCESSING = "PROCESSING", "Processing"
        COMPLETED = "COMPLETED", "Completed"
        FAILED = "FAILED", "Failed"
        CANCELLED = "CANCELLED", "Cancelled"

    organization = models.ForeignKey(
        Organization,
        on_delete=models.PROTECT,
        related_name="batches",
    )
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="uploaded_batches",
    )
    source_type = models.CharField(
        max_length=20,
        choices=SourceType.choices,
    )
    original_filename = models.CharField(max_length=255)
    stored_file = models.FileField(
        upload_to="ledger-sync/batches/%Y/%m/%d/",
        validators=[
            FileExtensionValidator(
                allowed_extensions=["csv", "xlsx", "xls"]
            )
        ],
    )
    checksum = models.CharField(max_length=64)
    source_account = models.CharField(max_length=100, default="primary")
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.PENDING,
    )
    error_message = models.TextField(blank=True)
    total_records = models.PositiveIntegerField(default=0)
    processed_records = models.PositiveIntegerField(default=0)
    imported_records = models.PositiveIntegerField(default=0)
    duplicate_records = models.PositiveIntegerField(default=0)
    failed_records = models.PositiveIntegerField(default=0)
    processing_started_at = models.DateTimeField(null=True, blank=True)
    processing_completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        indexes = [
            models.Index(
                fields=["organization", "status", "-created_at"],
                name="batch_org_status_created_idx",
            ),
            models.Index(
                fields=["organization", "source_type", "-created_at"],
                name="batch_org_source_created_idx",
            ),
        ]
        constraints = [
            # A customer cannot upload the exact same complete file twice.
            models.UniqueConstraint(
                fields=["organization", "source_type", "source_account", "checksum"],
                name="unique_uploaded_file_per_org",
            ),
        ]

    @property
    def progress_percentage(self) -> int:
        """Return a bounded integer suitable for a progress bar."""

        if not self.total_records:
            return 0
        return min(
            100,
            round((self.processed_records / self.total_records) * 100),
        )

    def __str__(self) -> str:
        return f"{self.original_filename} ({self.source_type})"


class Transaction(UUIDModel, TimeStampedModel):
    """One normalized source-system transaction."""

    class Status(models.TextChoices):
        UNRECONCILED = "UNRECONCILED", "Unreconciled"
        MATCHED = "MATCHED", "Matched"
        DISCREPANCY = "DISCREPANCY", "Discrepancy"
        IGNORED = "IGNORED", "Ignored"

    class Direction(models.TextChoices):
        DEBIT = "DEBIT", "Debit"
        CREDIT = "CREDIT", "Credit"

    organization = models.ForeignKey(
        Organization,
        on_delete=models.PROTECT,
        related_name="transactions",
    )
    batch = models.ForeignKey(
        Batch,
        on_delete=models.PROTECT,
        related_name="transactions",
    )
    source_type = models.CharField(
        max_length=20,
        choices=Batch.SourceType.choices,
    )
    source_account = models.CharField(max_length=100, default="primary")
    row_number = models.PositiveIntegerField()
    transaction_reference = models.CharField(max_length=255)
    normalized_reference = models.CharField(max_length=255)
    amount = models.DecimalField(max_digits=19, decimal_places=4)
    currency = models.CharField(max_length=3)
    timestamp = models.DateTimeField()
    counterparty = models.CharField(max_length=255, blank=True)
    direction = models.CharField(
        max_length=10,
        choices=Direction.choices,
    )
    description = models.TextField(blank=True)
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.UNRECONCILED,
    )
    # This hash identifies a row within one source type for one organization.
    source_row_hash = models.CharField(max_length=64)
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        indexes = [
            models.Index(
                fields=["organization", "batch", "row_number"],
                name="txn_org_batch_row_idx",
            ),
            models.Index(
                fields=["organization", "status", "-timestamp"],
                name="txn_org_status_time_idx",
            ),
            models.Index(
                fields=[
                    "organization",
                    "source_type",
                    "normalized_reference",
                    "timestamp",
                ],
                name="txn_org_source_ref_time_idx",
            ),
            models.Index(
                fields=[
                    "organization",
                    "amount",
                    "currency",
                    "timestamp",
                ],
                name="txn_org_amount_currency_idx",
            ),
        ]
        constraints = [
            # This allows the same reference to exist in ERP and BANK sources
            # while preventing repeat imports within one source type.
            models.UniqueConstraint(
                fields=["organization", "source_type", "source_account", "source_row_hash"],
                name="unique_source_transaction_per_org_type",
            ),
            models.CheckConstraint(
                condition=models.Q(amount__gte=Decimal("0.0000")),
                name="transaction_amount_non_negative",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.transaction_reference} - {self.amount} {self.currency}"


class BatchRow(UUIDModel):
    """Persist a row's outcome and retain membership in overlapping files.

    Transaction.batch is its first import. BatchRow links reused transactions
    to later batches too, so deduplication does not lose reconciliation scope.
    """

    class Outcome(models.TextChoices):
        IMPORTED = "IMPORTED", "Imported"
        REUSED = "REUSED", "Repeated source row"
        INVALID = "INVALID", "Invalid row"

    batch = models.ForeignKey(Batch, on_delete=models.PROTECT, related_name="rows")
    row_number = models.PositiveIntegerField()
    transaction = models.ForeignKey(
        Transaction, on_delete=models.PROTECT, null=True, related_name="batch_rows"
    )
    outcome = models.CharField(max_length=10, choices=Outcome.choices)
    error = models.CharField(max_length=500, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["batch", "row_number"], name="unique_batch_row"
            ),
        ]


class ReconciliationRule(UUIDModel, TimeStampedModel):
    """Organization-configurable matching tolerances."""

    organization = models.ForeignKey(
        Organization,
        on_delete=models.PROTECT,
        related_name="reconciliation_rules",
    )
    name = models.CharField(max_length=255)
    priority = models.PositiveIntegerField(default=100)
    exact_reference_match = models.BooleanField(default=True)
    date_variance_days = models.PositiveSmallIntegerField(
        default=2,
        validators=[MaxValueValidator(365)],
    )
    amount_tolerance_percent = models.DecimalField(
        max_digits=7,
        decimal_places=4,
        default=Decimal("0.0000"),
        validators=[
            MinValueValidator(Decimal("0")),
            MaxValueValidator(Decimal("100")),
        ],
    )
    currency_must_match = models.BooleanField(default=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["priority", "name"]
        indexes = [
            models.Index(
                fields=["organization", "is_active", "priority"],
                name="rule_org_active_priority_idx",
            ),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "name"],
                name="unique_rule_name_per_org",
            ),
            models.CheckConstraint(
                condition=models.Q(amount_tolerance_percent__gte=0)
                & models.Q(amount_tolerance_percent__lte=100),
                name="valid_rule_amount_tolerance",
            ),
            models.CheckConstraint(
                condition=models.Q(date_variance_days__lte=365),
                name="valid_rule_date_window",
            ),
        ]

    def __str__(self) -> str:
        return self.name


class ReconciliationRun(UUIDModel, TimeStampedModel):
    """One comparison between a completed ledger and external batch."""

    class Status(models.TextChoices):
        PENDING = "PENDING", "Pending"
        PROCESSING = "PROCESSING", "Processing"
        COMPLETED = "COMPLETED", "Completed"
        FAILED = "FAILED", "Failed"

    organization = models.ForeignKey(
        Organization,
        on_delete=models.PROTECT,
        related_name="reconciliation_runs",
    )
    ledger_batch = models.ForeignKey(
        Batch,
        on_delete=models.PROTECT,
        related_name="ledger_reconciliation_runs",
    )
    external_batch = models.ForeignKey(
        Batch,
        on_delete=models.PROTECT,
        related_name="external_reconciliation_runs",
    )
    rule = models.ForeignKey(
        ReconciliationRule,
        on_delete=models.PROTECT,
        related_name="runs",
    )
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.PENDING,
    )
    matched_count = models.PositiveIntegerField(default=0)
    discrepancy_count = models.PositiveIntegerField(default=0)
    error_message = models.TextField(blank=True)
    # Snapshot the rule at creation. Editing a rule cannot change queued work.
    rule_snapshot = models.JSONField(default=dict)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "ledger_batch", "external_batch"],
                name="unique_batch_pair_run",
            ),
            models.CheckConstraint(
                condition=~models.Q(ledger_batch=models.F("external_batch")),
                name="different_run_batches",
            ),
        ]
        indexes = [
            models.Index(
                fields=["organization", "status", "-created_at"],
                name="run_org_status_created_idx",
            ),
        ]

    def __str__(self) -> str:
        return f"Run {self.id} ({self.status})"


class ReconciliationMatch(UUIDModel, TimeStampedModel):
    """A successful one-to-one relationship between two source records."""

    reconciliation_run = models.ForeignKey(
        ReconciliationRun,
        on_delete=models.PROTECT,
        related_name="matches",
    )
    ledger_transaction = models.OneToOneField(
        Transaction,
        on_delete=models.PROTECT,
        related_name="ledger_match",
    )
    external_transaction = models.OneToOneField(
        Transaction,
        on_delete=models.PROTECT,
        related_name="external_match",
    )
    reference_score = models.DecimalField(
        max_digits=6,
        decimal_places=4,
        default=Decimal("0"),
    )
    amount_difference = models.DecimalField(
        max_digits=19,
        decimal_places=4,
        default=Decimal("0"),
    )
    date_difference_days = models.IntegerField(default=0)
    matching_reason = models.JSONField(default=dict)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=[
                    "reconciliation_run",
                    "ledger_transaction",
                    "external_transaction",
                ],
                name="unique_match_per_run",
            ),
        ]

    def __str__(self) -> str:
        return f"Match {self.ledger_transaction_id} -> {self.external_transaction_id}"


class Discrepancy(UUIDModel, TimeStampedModel):
    """An exception that requires review or a documented decision."""

    class Type(models.TextChoices):
        UNMATCHED_LEDGER = "UNMATCHED_LEDGER", "Unmatched Ledger"
        UNMATCHED_EXTERNAL = "UNMATCHED_EXTERNAL", "Unmatched External"
        AMOUNT_VARIANCE = "AMOUNT_VARIANCE", "Amount Variance"
        DATE_VARIANCE = "DATE_VARIANCE", "Date Variance"
        DUPLICATE_TRANSACTION = "DUPLICATE_TRANSACTION", "Duplicate"
        CURRENCY_MISMATCH = "CURRENCY_MISMATCH", "Currency Mismatch"
        AMBIGUOUS_MATCH = "AMBIGUOUS_MATCH", "Ambiguous Match"

    class Status(models.TextChoices):
        OPEN = "OPEN", "Open"
        IN_REVIEW = "IN_REVIEW", "In Review"
        RESOLVED = "RESOLVED", "Resolved"
        IGNORED = "IGNORED", "Ignored"

    organization = models.ForeignKey(
        Organization,
        on_delete=models.PROTECT,
        related_name="discrepancies",
    )
    reconciliation_run = models.ForeignKey(
        ReconciliationRun,
        on_delete=models.PROTECT,
        related_name="discrepancies",
    )
    discrepancy_type = models.CharField(max_length=40, choices=Type.choices)
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.OPEN,
    )
    primary_transaction = models.ForeignKey(
        Transaction,
        on_delete=models.PROTECT,
        related_name="primary_discrepancies",
    )
    secondary_transaction = models.ForeignKey(
        Transaction,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="secondary_discrepancies",
    )
    expected_amount = models.DecimalField(
        max_digits=19,
        decimal_places=4,
        null=True,
        blank=True,
    )
    actual_amount = models.DecimalField(
        max_digits=19,
        decimal_places=4,
        null=True,
        blank=True,
    )
    variance_amount = models.DecimalField(
        max_digits=19,
        decimal_places=4,
        null=True,
        blank=True,
    )
    details = models.JSONField(default=dict, blank=True)
    resolved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="resolved_discrepancies",
    )
    resolved_at = models.DateTimeField(null=True, blank=True)
    resolution_note = models.TextField(blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["reconciliation_run", "primary_transaction"],
                name="one_discrepancy_per_run_primary",
            ),
        ]
        indexes = [
            models.Index(
                fields=["organization", "status", "-created_at"],
                name="disc_org_status_created_idx",
            ),
            models.Index(
                fields=["organization", "discrepancy_type", "status"],
                name="disc_org_type_status_idx",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.get_discrepancy_type_display()} ({self.status})"


class AuditLog(UUIDModel):
    """Append-only business audit event."""

    class Action(models.TextChoices):
        BATCH_UPLOADED = "BATCH_UPLOADED", "Batch Uploaded"
        BATCH_PROCESSING = "BATCH_PROCESSING", "Batch Processing"
        TRANSACTION_MATCHED = "TRANSACTION_MATCHED", "Transaction Matched"
        DISCREPANCY_CREATED = "DISCREPANCY_CREATED", "Discrepancy Created"
        DISCREPANCY_RESOLVED = "DISCREPANCY_RESOLVED", "Discrepancy Resolved"
        STATUS_CHANGED = "STATUS_CHANGED", "Status Changed"

    organization = models.ForeignKey(
        Organization,
        on_delete=models.PROTECT,
        related_name="audit_logs",
    )
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="audit_logs",
    )
    action = models.CharField(max_length=50, choices=Action.choices)
    entity_type = models.CharField(max_length=100)
    entity_id = models.UUIDField()
    payload = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(
                fields=[
                    "organization",
                    "entity_type",
                    "entity_id",
                    "-created_at",
                ],
                name="audit_org_entity_created_idx",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.action} - {self.entity_type} {self.entity_id}"
