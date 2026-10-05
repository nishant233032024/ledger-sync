"""Request validation and response serialization."""

from pathlib import Path

from django.conf import settings
from rest_framework import serializers
from rest_framework.exceptions import AuthenticationFailed
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer

from .models import Batch, Discrepancy, ReconciliationRule, Transaction, User


class LedgerTokenSerializer(TokenObtainPairSerializer):
    """Add tenant and role information to the access token response."""

    @classmethod
    def get_token(cls, user):
        token = super().get_token(user)
        token["organization_id"] = str(user.organization_id or "")
        token["role"] = user.role
        return token

    def validate(self, attrs):
        values = super().validate(attrs)
        if not self.user.organization_id or not self.user.organization.is_active:
            raise AuthenticationFailed("An active organization membership is required.")
        return values


class BatchUploadSerializer(serializers.Serializer):
    """Validate only inexpensive upload properties in the HTTP process."""

    file = serializers.FileField()
    source_type = serializers.ChoiceField(choices=Batch.SourceType.choices)
    source_account = serializers.RegexField(
        regex=r"^[A-Za-z0-9._-]{1,100}$",
        default="primary",
    )

    def validate_file(self, uploaded_file):
        suffix = Path(uploaded_file.name).suffix.lower()
        if suffix not in {".csv", ".xlsx", ".xls"}:
            raise serializers.ValidationError("Only CSV, XLSX and XLS files are supported.")
        maximum = settings.MAX_UPLOAD_SIZE
        if suffix == ".xls":
            maximum = min(maximum, 10 * 1024 * 1024)
        if uploaded_file.size > maximum:
            raise serializers.ValidationError(f"The file cannot exceed {maximum // (1024 * 1024)} MB.")
        # Never rely on a browser MIME type for security; the worker validates
        # the actual file structure before inserting rows.
        return uploaded_file


class ResolveDiscrepancySerializer(serializers.Serializer):
    resolution = serializers.ChoiceField(choices=[
        ("ACCEPTED_VARIANCE", "Accepted variance"),
        ("MARKED_DUPLICATE", "Marked duplicate"),
        ("CORRECTED_EXTERNALLY", "Corrected externally"),
        ("IGNORED", "Ignored"),
    ])
    note = serializers.CharField(min_length=10, max_length=2_000)


class StartReconciliationSerializer(serializers.Serializer):
    ledger_batch_id = serializers.UUIDField()
    external_batch_id = serializers.UUIDField()
    rule_id = serializers.UUIDField(required=False)

    def validate(self, attrs):
        if attrs["ledger_batch_id"] == attrs["external_batch_id"]:
            raise serializers.ValidationError("Choose two different batches.")
        return attrs


class TransactionSerializer(serializers.ModelSerializer):
    reference = serializers.CharField(source="transaction_reference")
    batch_id = serializers.UUIDField(source="batch.id", read_only=True)

    class Meta:
        model = Transaction
        fields = [
            "id", "reference", "batch_id", "source_type", "amount", "currency",
            "timestamp", "counterparty", "direction", "status", "description",
        ]


class RuleSerializer(serializers.ModelSerializer):
    class Meta:
        model = ReconciliationRule
        fields = [
            "id", "name", "priority", "exact_reference_match", "date_variance_days",
            "amount_tolerance_percent", "is_active",
        ]


class DiscrepancySerializer(serializers.ModelSerializer):
    primary_reference = serializers.CharField(
        source="primary_transaction.transaction_reference", read_only=True
    )
    primary_amount = serializers.DecimalField(
        source="primary_transaction.amount", max_digits=19, decimal_places=4, read_only=True
    )
    secondary_reference = serializers.CharField(
        source="secondary_transaction.transaction_reference", read_only=True, allow_null=True
    )
    secondary_amount = serializers.DecimalField(
        source="secondary_transaction.amount", max_digits=19, decimal_places=4,
        read_only=True, allow_null=True
    )

    class Meta:
        model = Discrepancy
        fields = [
            "id", "discrepancy_type", "status", "primary_reference", "primary_amount",
            "secondary_reference", "secondary_amount", "expected_amount", "actual_amount",
            "variance_amount", "details", "created_at", "resolution_note",
        ]


class BatchSerializer(serializers.ModelSerializer):
    progress_percentage = serializers.IntegerField(read_only=True)

    class Meta:
        model = Batch
        fields = [
            "id", "original_filename", "source_type", "source_account", "status",
            "total_records", "processed_records", "imported_records", "duplicate_records",
            "failed_records", "progress_percentage", "error_message", "created_at",
        ]
