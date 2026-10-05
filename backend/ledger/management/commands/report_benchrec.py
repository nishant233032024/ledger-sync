"""Evaluate saved LedgerSync decisions against separate, offline evidence."""

import csv
import json
from collections import Counter
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from ledger.models import Discrepancy, ReconciliationMatch, ReconciliationRun


def source_id(item):
    return str(item.metadata.get("source_id", ""))


class Command(BaseCommand):
    help = "Print an evidence-based report for a BenchRec run (no matching labels enter the engine)."

    def add_arguments(self, parser):
        parser.add_argument("--run-id", required=True)
        parser.add_argument("--evidence", required=True)

    def handle(self, *args, **options):
        run = ReconciliationRun.objects.get(id=options["run_id"])
        if run.status != ReconciliationRun.Status.COMPLETED:
            raise CommandError(f"The run is {run.status}, not COMPLETED: {run.error_message}")
        matches = list(ReconciliationMatch.objects.filter(reconciliation_run=run).select_related(
            "ledger_transaction", "external_transaction"
        ))
        discrepancies = list(Discrepancy.objects.filter(reconciliation_run=run).select_related(
            "primary_transaction", "secondary_transaction"
        ))
        actual_pairs = {(source_id(item.ledger_transaction), source_id(item.external_transaction)) for item in matches}
        actual_flags = Counter((
            source_id(item.primary_transaction), item.discrepancy_type,
            source_id(item.secondary_transaction) if item.secondary_transaction_id else None,
        ) for item in discrepancies)
        evidence = Path(options["evidence"])
        report = {
            "run_id": str(run.id), "status": run.status,
            "ledger_batch_id": str(run.ledger_batch_id), "bank_batch_id": str(run.external_batch_id),
            "policy": run.rule_snapshot, "matched_pairs": len(matches),
            "stored_input_sha256": {
                "ledger": run.ledger_batch.checksum, "bank": run.external_batch.checksum,
            },
            "discrepancy_count": len(discrepancies),
            "discrepancy_types": dict(Counter(item.discrepancy_type for item in discrepancies)),
            "ledger_ingestion": {
                "total": run.ledger_batch.total_records,
                "imported": run.ledger_batch.imported_records,
                "invalid": run.ledger_batch.failed_records,
            },
            "bank_ingestion": {
                "total": run.external_batch.total_records,
                "imported": run.external_batch.imported_records,
                "invalid": run.external_batch.failed_records,
            },
        }
        if evidence.suffix == ".json":
            manifest = json.loads(evidence.read_text())
            expected_flags = Counter((
                flag["primary_source_id"], flag["type"], flag["secondary_source_id"]
            ) for flag in manifest["expected_flags"])
            flags_equal = actual_flags == expected_flags
            count_equal = len(matches) == manifest["expected_matches"]
            pairs_equal = actual_pairs == {
                tuple(pair) for pair in manifest["expected_matched_source_pairs"]
            }
            # A count alone does not prove correct pairs. Inspect input row
            # provenance: remaining unmodified pairs have equal cash fields
            # and must have the same original reference on BOTH sides.
            match_values_valid = all(
                item.ledger_transaction.transaction_reference == item.external_transaction.transaction_reference
                and item.ledger_transaction.amount == item.external_transaction.amount
                and item.ledger_transaction.currency == item.external_transaction.currency
                and item.ledger_transaction.timestamp == item.external_transaction.timestamp
                and item.ledger_transaction.direction == item.external_transaction.direction
                for item in matches
            )
            report.update({
                "evaluation": "CONTROLLED_FAULT_INJECTION",
                "expected_matches": manifest["expected_matches"],
                "expected_discrepancy_count": manifest["expected_discrepancy_count"],
                "flags_exactly_equal_by_source_id": flags_equal,
                "match_count_equal": count_equal,
                "matched_source_pairs_exactly_equal": pairs_equal,
                "match_values_valid": match_values_valid,
                "verification": "PASS" if flags_equal and count_equal and pairs_equal and match_values_valid else "FAIL",
                "meaning": "Known injected defects; not original bank errors.",
            })
        else:
            with evidence.open(newline="", encoding="utf-8") as file_object:
                truth_rows = list(csv.DictReader(file_object))
            supplied_pairs = {(item["ledger_source_id"], item["bank_source_id"]) for item in truth_rows}
            correct = actual_pairs & supplied_pairs
            false_pairs = actual_pairs - supplied_pairs
            report.update({
                "evaluation": "CURATED_TRAINING_SAMPLE_NOT_HELD_OUT_BENCHMARK",
                "supplied_pairs": len(supplied_pairs), "correct_predicted_pairs": len(correct),
                "false_predicted_pairs": len(false_pairs),
                "pair_precision_percent": round(len(correct) / len(actual_pairs) * 100, 4) if actual_pairs else None,
                "pair_recall_percent": round(len(correct) / len(supplied_pairs) * 100, 4) if supplied_pairs else None,
                "false_pair_examples": [list(pair) for pair in sorted(false_pairs)[:10]],
                "meaning": "Unmatched/variance flags mean rule exceptions. Publisher labels describe matches, not proven missing funds or fraud.",
            })
        self.stdout.write(json.dumps(report, indent=2))
        if report.get("verification") == "FAIL":
            raise CommandError("The controlled exercise did not produce its documented flags.")
