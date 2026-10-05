"""Asynchronous ingestion and reconciliation jobs."""

from celery import shared_task
from django.core.cache import cache
from django.utils import timezone

from .importing import TransactionImporter, cache_progress
from .models import Batch, ReconciliationRun
from .parsing import count_batch_rows, iter_batch_rows
from .reconciliation import ReconciliationService


def lock_key(kind: str, identifier: str) -> str:
    """Use one predictable Redis key per logical job."""
    return f"ledger-sync:{kind}:{identifier}:lock"


@shared_task(
    bind=True,
    autoretry_for=(OSError, ConnectionError),
    retry_backoff=True,
    retry_backoff_max=600,
    retry_jitter=True,
    max_retries=5,
)
def process_batch(self, batch_id: str) -> None:
    """Import a source file without blocking an API worker."""
    key = lock_key("batch", batch_id)
    if not cache.add(key, self.request.id, timeout=60 * 60):
        return
    try:
        batch = Batch.objects.select_related("organization").get(id=batch_id)
        # A redelivered task is a safe no-op after successful completion.
        if batch.status == Batch.Status.COMPLETED:
            return
        Batch.objects.filter(id=batch.id).update(
            status=Batch.Status.PROCESSING,
            processing_started_at=timezone.now(),
            error_message="",
            updated_at=timezone.now(),
        )
        batch.refresh_from_db()
        batch.total_records = count_batch_rows(batch)
        Batch.objects.filter(id=batch.id).update(
            total_records=batch.total_records,
            updated_at=timezone.now(),
        )
        cache_progress(batch)
        TransactionImporter(batch=batch).import_rows(iter_batch_rows(batch))
        batch.refresh_from_db()
        batch.status = Batch.Status.COMPLETED
        batch.processing_completed_at = timezone.now()
        batch.save(update_fields=["status", "processing_completed_at", "updated_at"])
        cache_progress(batch)
    except Exception as exc:
        Batch.objects.filter(id=batch_id).update(
            status=Batch.Status.FAILED,
            error_message=str(exc)[:2_000],
            updated_at=timezone.now(),
        )
        raise
    finally:
        cache.delete(key)


@shared_task(bind=True, max_retries=3, default_retry_delay=10)
def run_reconciliation(self, run_id: str) -> None:
    """Run a completed ledger/external batch comparison in Celery."""
    key = lock_key("run", run_id)
    if not cache.add(key, self.request.id, timeout=60 * 60):
        return
    try:
        run = ReconciliationRun.objects.select_related(
            "ledger_batch", "external_batch", "rule"
        ).get(id=run_id)
        if run.status == ReconciliationRun.Status.COMPLETED:
            return
        if (run.ledger_batch.status != Batch.Status.COMPLETED
                or run.external_batch.status != Batch.Status.COMPLETED):
            raise ValueError("Both batches must be COMPLETED before matching.")
        ReconciliationService(run=run).execute()
    except Exception as exc:
        ReconciliationRun.objects.filter(id=run_id).update(
            status=ReconciliationRun.Status.FAILED,
            error_message=str(exc)[:2_000],
            updated_at=timezone.now(),
        )
        raise
    finally:
        cache.delete(key)


@shared_task
def dispatch_pending_jobs() -> int:
    """Recover uploads whose API request committed before enqueueing.

    The upload view writes the batch before calling Celery. If the broker is
    briefly unavailable after the database commit, beat eventually dispatches
    the PENDING batch instead of losing the user's work.
    """
    dispatched = 0
    for batch_id in Batch.objects.filter(status=Batch.Status.PENDING).values_list("id", flat=True)[:100]:
        process_batch.delay(str(batch_id))
        dispatched += 1
    return dispatched


@shared_task
def mark_stale_batches() -> int:
    """Mark abandoned processing batches so operators can retry them."""
    cutoff = timezone.now() - timezone.timedelta(hours=2)
    return Batch.objects.filter(
        status=Batch.Status.PROCESSING,
        processing_started_at__lt=cutoff,
    ).update(
        status=Batch.Status.FAILED,
        error_message="Processing exceeded the two-hour safety window.",
        updated_at=timezone.now(),
    )
