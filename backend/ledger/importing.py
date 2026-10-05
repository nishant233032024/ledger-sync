"""Retry-safe, bounded-memory bulk ingestion."""

from itertools import islice

from django.core.cache import cache
from django.db import transaction
from django.db.models import Count, Q
from django.utils import timezone
from redis.exceptions import RedisError

from .models import Batch, BatchRow, Organization, Transaction
from .parsing import RowValidationError, build_transaction_hash, normalize_reference, normalize_row


def chunks(iterator, size=1000):
    """Consume an iterator in fixed-size groups rather than loading everything."""
    iterator = iter(iterator)
    while group := list(islice(iterator, size)):
        yield group


def progress_key(batch_id) -> str:
    return f"ledger-sync:batch:{batch_id}:progress"


def batch_status(batch: Batch) -> dict:
    return {
        "id": str(batch.id), "state": batch.status,
        "percentage": 100 if batch.status == Batch.Status.COMPLETED else batch.progress_percentage,
        "processed_records": batch.processed_records, "total_records": batch.total_records,
        "imported_records": batch.imported_records, "duplicate_records": batch.duplicate_records,
        "failed_records": batch.failed_records, "error": batch.error_message or None,
    }


def cache_progress(batch: Batch) -> None:
    # Redis failure must not roll back committed financial records.
    try:
        cache.set(progress_key(batch.id), batch_status(batch), timeout=3600)
    except RedisError:
        pass


class TransactionImporter:
    def __init__(self, *, batch, chunk_size=1000):
        self.batch = batch
        self.chunk_size = chunk_size

    def import_rows(self, rows):
        for group in chunks(rows, self.chunk_size):
            self._flush(group)
            self.refresh_counts()

    def _flush(self, group):
        # A short tenant-row lock serializes ingestion chunks within a tenant.
        # This makes insert counts exact and avoids broad ignore_conflicts.
        with transaction.atomic():
            Organization.objects.select_for_update().get(id=self.batch.organization_id)
            done = set(BatchRow.objects.filter(
                batch=self.batch, row_number__in=[number for number, _ in group]
            ).values_list("row_number", flat=True))
            valid = []
            records = []
            for number, raw in group:
                if number in done:
                    continue  # A retry has already committed this source row.
                try:
                    row = normalize_row(raw)
                    valid.append((number, row, build_transaction_hash(row)))
                except RowValidationError as exc:
                    records.append(BatchRow(
                        batch=self.batch, row_number=number,
                        outcome=BatchRow.Outcome.INVALID, error=str(exc)[:500],
                    ))
            hashes = {digest for _, _, digest in valid}
            existing = {
                item.source_row_hash: item
                for item in Transaction.objects.filter(
                    organization_id=self.batch.organization_id,
                    source_type=self.batch.source_type,
                    source_account=self.batch.source_account,
                    source_row_hash__in=hashes,
                )
            }
            new = []
            for number, row, digest in valid:
                item = existing.get(digest)
                outcome = BatchRow.Outcome.REUSED
                if item is None:
                    item = Transaction(
                        organization_id=self.batch.organization_id,
                        batch=self.batch, source_type=self.batch.source_type,
                        source_account=self.batch.source_account, row_number=number,
                        transaction_reference=row.reference,
                        normalized_reference=normalize_reference(row.reference),
                        amount=row.amount, currency=row.currency, timestamp=row.timestamp,
                        counterparty=row.counterparty, direction=row.direction,
                        description=row.description, metadata={**row.metadata, "source_id": row.source_id},
                        source_row_hash=digest,
                    )
                    existing[digest] = item  # Deduplicate inside this chunk too.
                    new.append(item)
                    outcome = BatchRow.Outcome.IMPORTED
                records.append(BatchRow(
                    batch=self.batch, row_number=number, transaction=item, outcome=outcome,
                ))
            Transaction.objects.bulk_create(new, batch_size=self.chunk_size)
            BatchRow.objects.bulk_create(records, batch_size=self.chunk_size)

    def refresh_counts(self):
        # Counts are derived from durable row outcomes, not a worker's memory.
        counts = self.batch.rows.aggregate(
            processed=Count("id"),
            imported=Count("id", filter=Q(outcome=BatchRow.Outcome.IMPORTED)),
            reused=Count("id", filter=Q(outcome=BatchRow.Outcome.REUSED)),
            invalid=Count("id", filter=Q(outcome=BatchRow.Outcome.INVALID)),
        )
        Batch.objects.filter(id=self.batch.id).update(
            processed_records=counts["processed"], imported_records=counts["imported"],
            duplicate_records=counts["reused"], failed_records=counts["invalid"],
            updated_at=timezone.now(),
        )
        self.batch.refresh_from_db()
        cache_progress(self.batch)
