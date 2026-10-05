"""Conservative matching with atomic, bulk-written decisions."""

from collections import defaultdict
from datetime import timedelta
from decimal import Decimal

from django.db import transaction
from django.db.models import Subquery
from django.utils import timezone

from .importing import chunks
from .models import (
    AuditLog, Batch, BatchRow, Discrepancy, Organization,
    ReconciliationMatch, ReconciliationRun, Transaction,
)


def batch_transactions(batch):
    # A subquery avoids duplicated transactions when one file repeats a row.
    ids = BatchRow.objects.filter(batch=batch, transaction__isnull=False).values("transaction_id")
    return Transaction.objects.filter(
        organization_id=batch.organization_id, id__in=Subquery(ids)
    )


class ReconciliationService:
    """Process one run at a time per tenant; parallelism is across tenants.

    The tenant lock lasts for a complete run. This deliberately trades intra-
    tenant parallelism for straightforward correctness in this first version.
    Parsing still commits in chunks, and HTTP requests never wait for matching.
    """

    def __init__(self, *, run):
        self.run = run
        self.policy = run.rule_snapshot

    def execute(self):
        with transaction.atomic():
            Organization.objects.select_for_update().get(id=self.run.organization_id)
            self.run.refresh_from_db()
            if self.run.status == ReconciliationRun.Status.COMPLETED:
                return
            if (self.run.ledger_batch.status != Batch.Status.COMPLETED
                    or self.run.external_batch.status != Batch.Status.COMPLETED):
                raise ValueError("Both batches must finish ingestion first.")

            # All matching decisions commit together. A crash rolls the run
            # back completely, so redelivery can safely rerun the same work.
            ledger_query = batch_transactions(self.run.ledger_batch).order_by("id")
            external_query = batch_transactions(self.run.external_batch).order_by("id")
            ledger = list(ledger_query.select_for_update())
            external = list(external_query.select_for_update())
            if any(item.status != Transaction.Status.UNRECONCILED for item in ledger + external):
                raise ValueError("These files overlap transactions already processed by another run.")
            # Files are capped at 250k rows. Matching uses a reference index,
            # not a quadratic scan across all possible transaction pairs.
            if len(ledger) + len(external) > 100_000:
                raise ValueError("This release supports at most 100,000 source transactions per run.")
            self.run.status = ReconciliationRun.Status.PROCESSING
            self.run.save(update_fields=["status", "updated_at"])
            by_reference = defaultdict(list)
            for item in external:
                by_reference[item.normalized_reference].append(item)
            # Both sides of a repeated business key require review. Distinct
            # event IDs/timestamps survive ingestion and reveal duplicate debits.
            ledger_counts = defaultdict(int)
            for item in ledger:
                ledger_counts[(item.normalized_reference, item.currency, item.direction, item.amount)] += 1
            remaining = {item.id: item for item in external}
            matches, discrepancies, logs = [], [], []
            delta = timedelta(days=int(self.policy["date_variance_days"]))
            percent = Decimal(self.policy["amount_tolerance_percent"])

            def flag(primary, kind, secondary=None, reason="", candidates=None):
                discrepancy = Discrepancy(
                    organization_id=self.run.organization_id, reconciliation_run=self.run,
                    discrepancy_type=kind, primary_transaction=primary,
                    secondary_transaction=secondary,
                    expected_amount=primary.amount,
                    actual_amount=secondary.amount if secondary else None,
                    variance_amount=secondary.amount - primary.amount if secondary else None,
                    details={"reason": reason, "candidate_ids": candidates or []},
                )
                discrepancies.append(discrepancy)
                primary.status = Transaction.Status.DISCREPANCY
                if secondary:
                    secondary.status = Transaction.Status.DISCREPANCY
                    remaining.pop(secondary.id, None)
                logs.append(AuditLog(
                    organization_id=self.run.organization_id,
                    action=AuditLog.Action.DISCREPANCY_CREATED,
                    entity_type="Discrepancy", entity_id=discrepancy.id,
                    payload={"run_id": str(self.run.id), "type": kind},
                ))

            for item in ledger:
                if self.policy.get("exact_reference_match", True):
                    # This indexed lookup is the normal, high-confidence path.
                    candidates = [candidate for candidate in by_reference[item.normalized_reference]
                                  if candidate.id in remaining]
                else:
                    # This lower-confidence mode is intentionally explicit: it
                    # may match by amount/date but never silently wins ties.
                    candidates = [candidate for candidate in remaining.values()
                                  if candidate.id in remaining
                                  and candidate.direction == item.direction
                                  and abs(candidate.timestamp - item.timestamp) <= delta]
                key = (item.normalized_reference, item.currency, item.direction, item.amount)
                if ledger_counts[key] > 1:
                    flag(item, Discrepancy.Type.DUPLICATE_TRANSACTION,
                         reason="Repeated ledger reference, amount, currency and direction.")
                    continue
                eligible = [candidate for candidate in candidates
                            if (not self.policy.get("currency_must_match", True)
                                or candidate.currency == item.currency)
                            and candidate.direction == item.direction
                            and abs(candidate.timestamp - item.timestamp) <= delta
                            and abs(candidate.amount - item.amount) <= abs(item.amount) * percent / 100]
                if len(eligible) > 1:
                    flag(item, Discrepancy.Type.AMBIGUOUS_MATCH,
                         reason="Multiple eligible source records; no automatic choice made.",
                         candidates=[str(candidate.id) for candidate in eligible])
                elif len(eligible) == 1:
                    other = eligible[0]
                    match = ReconciliationMatch(
                        reconciliation_run=self.run, ledger_transaction=item,
                        external_transaction=other, reference_score=Decimal("1"),
                        amount_difference=other.amount - item.amount,
                        date_difference_days=abs((other.timestamp.date() - item.timestamp.date()).days),
                        matching_reason={"reference": "exact", "rule": self.policy},
                    )
                    matches.append(match)
                    item.status = other.status = Transaction.Status.MATCHED
                    remaining.pop(other.id)
                    logs.append(AuditLog(
                        organization_id=self.run.organization_id,
                        action=AuditLog.Action.TRANSACTION_MATCHED,
                        entity_type="ReconciliationMatch", entity_id=match.id,
                        payload={"run_id": str(self.run.id)},
                    ))
                elif len(candidates) == 1:
                    other = candidates[0]
                    if other.currency != item.currency:
                        kind = Discrepancy.Type.CURRENCY_MISMATCH
                    elif abs(other.timestamp - item.timestamp) > delta:
                        kind = Discrepancy.Type.DATE_VARIANCE
                    else:
                        kind = Discrepancy.Type.AMOUNT_VARIANCE
                    flag(item, kind, other, "Same reference failed a matching condition.")
                elif len(candidates) > 1:
                    flag(item, Discrepancy.Type.AMBIGUOUS_MATCH,
                         reason="Multiple same-reference exceptions require review.",
                         candidates=[str(candidate.id) for candidate in candidates])
                else:
                    flag(item, Discrepancy.Type.UNMATCHED_LEDGER,
                         reason="No external row has this reference.")

            for item in remaining.values():
                flag(item, Discrepancy.Type.UNMATCHED_EXTERNAL,
                     reason="No ledger row consumed this source record.")
            # Bulk operations avoid an insert/update query for every transaction.
            ReconciliationMatch.objects.bulk_create(matches, batch_size=1000)
            Discrepancy.objects.bulk_create(discrepancies, batch_size=1000)
            AuditLog.objects.bulk_create(logs, batch_size=1000)
            for group in chunks(iter(ledger + external), 1000):
                for item in group:
                    item.updated_at = timezone.now()
                Transaction.objects.bulk_update(group, ["status", "updated_at"], batch_size=1000)
            self.run.status = ReconciliationRun.Status.COMPLETED
            self.run.matched_count = len(matches)
            self.run.discrepancy_count = len(discrepancies)
            self.run.error_message = ""
            self.run.save(update_fields=[
                "status", "matched_count", "discrepancy_count", "error_message", "updated_at"
            ])
