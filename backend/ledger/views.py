"""HTTP adapters: validate input, scope tenants, then call domain services."""

import logging

from django.core.cache import cache
from django.conf import settings
from django.db import IntegrityError, transaction
from django.db.models import Count, Q, Subquery, Sum
from django.db.models.functions import Abs
from django.shortcuts import get_object_or_404
from django.utils import timezone
from kombu.exceptions import OperationalError as BrokerError
from redis.exceptions import RedisError
from rest_framework import status
from rest_framework.exceptions import ValidationError
from rest_framework.generics import ListAPIView
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.views import TokenObtainPairView

from .filters import DiscrepancyFilter, TransactionFilter
from .importing import batch_status, progress_key
from .models import AuditLog, Batch, BatchRow, Discrepancy, Organization, ReconciliationRule, ReconciliationRun, Transaction
from .parsing import calculate_file_sha256
from .permissions import IsAdmin, IsFinanceManagerOrAdmin, IsTenantMember
from .serializers import (
    BatchSerializer, BatchUploadSerializer, DiscrepancySerializer,
    LedgerTokenSerializer, ResolveDiscrepancySerializer, RuleSerializer,
    StartReconciliationSerializer, TransactionSerializer,
)
from .tasks import process_batch, run_reconciliation

logger = logging.getLogger(__name__)


def data_response(data, http_status=200):
    return Response({"data": data}, status=http_status)


def conflict(code, message):
    return Response({"error": {"code": code, "message": message}}, status=409)


def enqueue(task, identifier):
    """Only call this AFTER committing a database job record.

    The durable PENDING record is the recovery source if publication fails.
    Beat republishes pending jobs; workers treat duplicate deliveries safely.
    """
    try:
        return task.delay(str(identifier)).id
    except (BrokerError, RedisError, OSError):
        logger.exception("Publication failed; beat will dispatch pending job %s", identifier)
        return None


class LedgerTokenView(TokenObtainPairView):
    serializer_class = LedgerTokenSerializer


class HealthView(APIView):
    # Liveness does not require authentication. Compose uses it to gate workers.
    permission_classes = [AllowAny]
    authentication_classes = []

    def get(self, request):
        return data_response({"status": "ok", "service": "ledger-sync-api"})


class MeView(APIView):
    permission_classes = [IsTenantMember]

    def get(self, request):
        return data_response({
            "username": request.user.username, "role": request.user.role,
            "organization": request.user.organization.name,
            "read_only": settings.LEDGERSYNC_PUBLIC_DEMO or request.user.role == "AUDITOR",
            "public_demo": settings.LEDGERSYNC_PUBLIC_DEMO,
        })


class BatchUploadView(APIView):
    permission_classes = [IsTenantMember, IsFinanceManagerOrAdmin]

    def post(self, request):
        # DRF turns invalid serializer input into a structured HTTP 400.
        serializer = BatchUploadSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        values = serializer.validated_data
        uploaded_file = values["file"]
        scope = {
            "organization": request.user.organization,
            "source_type": values["source_type"],
            "source_account": values["source_account"],
            "checksum": calculate_file_sha256(uploaded_file),
        }
        if Batch.objects.filter(**scope).exists():
            return conflict("DUPLICATE_FILE", "This source/account already imported this exact file.")
        try:
            with transaction.atomic():
                # File storage and SQL are distinct resources. Generated paths
                # prevent overwriting source evidence from a different upload.
                batch = Batch.objects.create(
                    **scope, uploaded_by=request.user,
                    original_filename=uploaded_file.name, stored_file=uploaded_file,
                )
                AuditLog.objects.create(
                    organization=request.user.organization, actor=request.user,
                    action=AuditLog.Action.BATCH_UPLOADED, entity_type="Batch",
                    entity_id=batch.id, payload={"filename": batch.original_filename},
                )
        except IntegrityError:
            # The unique constraint covers a concurrent repeat upload too.
            return conflict("DUPLICATE_FILE", "This file was uploaded concurrently.")
        task_id = enqueue(process_batch, batch.id)
        return data_response({
            "id": str(batch.id), "status": Batch.Status.PENDING,
            "task_id": task_id, "filename": batch.original_filename,
            "source_type": batch.source_type,
        }, http_status=status.HTTP_202_ACCEPTED)


class BatchListView(APIView):
    permission_classes = [IsTenantMember]

    def get(self, request):
        # The upload selector intentionally displays the newest 100 batches.
        queryset = Batch.objects.filter(organization=request.user.organization).order_by("-created_at")
        return data_response(BatchSerializer(queryset[:100], many=True).data)


class BatchStatusView(APIView):
    permission_classes = [IsTenantMember]

    def get(self, request, batch_id):
        batch = get_object_or_404(Batch, id=batch_id, organization=request.user.organization)
        # Terminal database state overrides stale or evicted Redis progress.
        if batch.status in {Batch.Status.COMPLETED, Batch.Status.FAILED, Batch.Status.CANCELLED}:
            return data_response(batch_status(batch))
        try:
            cached = cache.get(progress_key(batch.id))
        except RedisError:
            cached = None
        return data_response(cached or batch_status(batch))


class RetryBatchView(APIView):
    permission_classes = [IsTenantMember, IsFinanceManagerOrAdmin]

    def post(self, request, batch_id):
        with transaction.atomic():
            batch = get_object_or_404(
                Batch.objects.select_for_update(), id=batch_id,
                organization=request.user.organization,
            )
            if batch.status != Batch.Status.FAILED:
                return conflict("BATCH_NOT_FAILED", "Only failed batches can be retried.")
            batch.status = Batch.Status.PENDING
            batch.error_message = ""
            batch.save(update_fields=["status", "error_message", "updated_at"])
            AuditLog.objects.create(
                organization=request.user.organization, actor=request.user,
                action=AuditLog.Action.STATUS_CHANGED, entity_type="Batch", entity_id=batch.id,
                payload={"from": "FAILED", "to": "PENDING", "reason": "Manual retry"},
            )
        return data_response({"id": str(batch.id), "task_id": enqueue(process_batch, batch.id)}, 202)


class TransactionListView(ListAPIView):
    permission_classes = [IsTenantMember]
    serializer_class = TransactionSerializer
    filterset_class = TransactionFilter
    ordering_fields = ["timestamp", "amount", "transaction_reference"]
    ordering = ["-timestamp", "-id"]

    def get_queryset(self):
        return Transaction.objects.filter(organization=self.request.user.organization)


class DiscrepancyListView(ListAPIView):
    permission_classes = [IsTenantMember]
    serializer_class = DiscrepancySerializer
    filterset_class = DiscrepancyFilter
    ordering_fields = ["created_at", "variance_amount"]
    ordering = ["-created_at", "-id"]

    def get_queryset(self):
        # select_related prevents extra queries per displayed discrepancy.
        return Discrepancy.objects.filter(
            organization=self.request.user.organization
        ).select_related("primary_transaction", "secondary_transaction")


class ResolveDiscrepancyView(APIView):
    permission_classes = [IsTenantMember, IsFinanceManagerOrAdmin]

    def post(self, request, discrepancy_id):
        serializer = ResolveDiscrepancySerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        with transaction.atomic():
            # Follow the same tenant-before-record lock order as matching.
            Organization.objects.select_for_update().get(id=request.user.organization_id)
            discrepancy = get_object_or_404(
                Discrepancy.objects.select_for_update(), id=discrepancy_id,
                organization=request.user.organization,
            )
            if discrepancy.status in {Discrepancy.Status.RESOLVED, Discrepancy.Status.IGNORED}:
                return conflict("ALREADY_RESOLVED", "This discrepancy is already closed.")
            resolution = serializer.validated_data["resolution"]
            discrepancy.status = (
                Discrepancy.Status.IGNORED if resolution == "IGNORED" else Discrepancy.Status.RESOLVED
            )
            discrepancy.resolved_by = request.user
            discrepancy.resolved_at = timezone.now()
            discrepancy.resolution_note = serializer.validated_data["note"]
            discrepancy.details = {**discrepancy.details, "resolution": resolution}
            discrepancy.save(update_fields=[
                "status", "resolved_by", "resolved_at", "resolution_note", "details", "updated_at"
            ])
            # Closing an investigation is not proof of a match. We preserve the
            # detected transaction state instead of inventing a match record.
            AuditLog.objects.create(
                organization=request.user.organization, actor=request.user,
                action=AuditLog.Action.DISCREPANCY_RESOLVED, entity_type="Discrepancy",
                entity_id=discrepancy.id,
                payload={"resolution": resolution, "note": discrepancy.resolution_note},
            )
        return data_response(DiscrepancySerializer(discrepancy).data)


class RuleView(APIView):
    permission_classes = [IsTenantMember]

    def get(self, request):
        rules = ReconciliationRule.objects.filter(organization=request.user.organization)
        return data_response(RuleSerializer(rules, many=True).data)

    def post(self, request):
        # Auditors can inspect rules; only Admin can create configuration.
        if not IsAdmin().has_permission(request, self):
            from rest_framework.exceptions import PermissionDenied
            raise PermissionDenied("Only administrators can create rules.")
        serializer = RuleSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            with transaction.atomic():
                serializer.save(organization=request.user.organization)
        except IntegrityError as exc:
            raise ValidationError({"name": "This rule name already exists."}) from exc
        return data_response(serializer.data, 201)


class RunView(APIView):
    permission_classes = [IsTenantMember]

    def get(self, request):
        runs = ReconciliationRun.objects.filter(organization=request.user.organization).order_by("-created_at")[:50]
        return data_response([{
            "id": str(run.id), "status": run.status,
            "ledger_batch_id": str(run.ledger_batch_id), "external_batch_id": str(run.external_batch_id),
            "matched_count": run.matched_count, "discrepancy_count": run.discrepancy_count,
            "error_message": run.error_message,
        } for run in runs])

    def post(self, request):
        if not IsFinanceManagerOrAdmin().has_permission(request, self):
            from rest_framework.exceptions import PermissionDenied
            raise PermissionDenied("Only finance managers and administrators may start runs.")
        serializer = StartReconciliationSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        values = serializer.validated_data
        organization = request.user.organization
        ledger = get_object_or_404(Batch, id=values["ledger_batch_id"], organization=organization)
        external = get_object_or_404(Batch, id=values["external_batch_id"], organization=organization)
        if ledger.source_type != Batch.SourceType.ERP:
            raise ValidationError({"ledger_batch_id": "Choose an ERP batch."})
        if external.source_type not in {Batch.SourceType.BANK, Batch.SourceType.GATEWAY}:
            raise ValidationError({"external_batch_id": "Choose a BANK or GATEWAY batch."})
        if ledger.status != Batch.Status.COMPLETED or external.status != Batch.Status.COMPLETED:
            return conflict("BATCH_NOT_READY", "Both batches must finish processing first.")
        rules = ReconciliationRule.objects.filter(organization=organization, is_active=True)
        rule = get_object_or_404(rules, id=values["rule_id"]) if "rule_id" in values else rules.first()
        if rule is None:
            raise ValidationError({"rule_id": "Create an active rule first (or run seed_demo)."})
        snapshot = {
            "exact_reference_match": rule.exact_reference_match,
            "date_variance_days": rule.date_variance_days,
            "amount_tolerance_percent": str(rule.amount_tolerance_percent),
            "currency_must_match": True,
        }
        try:
            with transaction.atomic():
                run = ReconciliationRun.objects.create(
                    organization=organization, ledger_batch=ledger,
                    external_batch=external, rule=rule, rule_snapshot=snapshot,
                )
        except IntegrityError:
            return conflict("RUN_ALREADY_EXISTS", "This pair already has a run. Retry a failed run instead.")
        return data_response({
            "id": str(run.id), "status": run.status,
            "task_id": enqueue(run_reconciliation, run.id),
        }, 202)


class RetryRunView(APIView):
    permission_classes = [IsTenantMember, IsFinanceManagerOrAdmin]

    def post(self, request, run_id):
        with transaction.atomic():
            run = get_object_or_404(
                ReconciliationRun.objects.select_for_update(), id=run_id,
                organization=request.user.organization,
            )
            if run.status != ReconciliationRun.Status.FAILED:
                return conflict("RUN_NOT_FAILED", "Only failed runs may be retried.")
            run.status = ReconciliationRun.Status.PENDING
            run.error_message = ""
            run.save(update_fields=["status", "error_message", "updated_at"])
        return data_response({"id": str(run.id), "task_id": enqueue(run_reconciliation, run.id)}, 202)


class SummaryView(APIView):
    permission_classes = [IsTenantMember]

    def get(self, request):
        all_transactions = Transaction.objects.filter(organization=request.user.organization)
        run = None
        if request.query_params.get("run_id"):
            # Validate UUIDs before passing them to the ORM.
            from rest_framework.fields import UUIDField
            run_id = UUIDField().run_validation(request.query_params["run_id"])
            run = get_object_or_404(
                ReconciliationRun, id=run_id, organization=request.user.organization,
            )
            members = BatchRow.objects.filter(
                batch_id__in=[run.ledger_batch_id, run.external_batch_id],
            ).values("transaction_id")
            all_transactions = all_transactions.filter(id__in=Subquery(members))
        ledger_transactions = all_transactions.filter(source_type=Batch.SourceType.ERP)
        totals = all_transactions.aggregate(total=Count("id"))
        ledger_totals = ledger_transactions.aggregate(
            total=Count("id"), matched=Count("id", filter=Q(status=Transaction.Status.MATCHED)),
        )
        opened = Discrepancy.objects.filter(
            organization=request.user.organization,
            status__in=[Discrepancy.Status.OPEN, Discrepancy.Status.IN_REVIEW],
        )
        if run:
            opened = opened.filter(reconciliation_run=run)
            ledger_totals["matched"] = run.matches.count()
        # Currency-grouped absolute variance prevents cancellation and avoids
        # adding USD to INR without an explicit foreign-exchange valuation.
        grouped = opened.filter(variance_amount__isnull=False).values(
            "primary_transaction__currency"
        ).annotate(total=Sum(Abs("variance_amount")))
        variance_by_currency = {
            entry["primary_transaction__currency"]: str(entry["total"])
            for entry in grouped
        }
        return data_response({
            "total_uploaded": totals["total"], "matched": ledger_totals["matched"],
            # Match rate is measured against the ERP population, not double-
            # counted ERP + external rows.
            "match_rate": round(ledger_totals["matched"] / ledger_totals["total"] * 100, 2)
            if ledger_totals["total"] else 0,
            "pending_discrepancies": opened.count(),
            # The card is a single-currency convenience value. Mixed currencies
            # remain explicit in variance_by_currency instead of being added.
            "total_variance": next(iter(variance_by_currency.values()), None)
            if len(variance_by_currency) == 1 else None,
            "variance_by_currency": variance_by_currency,
        })
