"""Precompute public BenchRec results without a worker or Redis service."""

import hashlib
import json
from decimal import Decimal
from io import StringIO

from django.conf import settings
from django.core.files import File
from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from ledger.models import AuditLog, Batch, Organization, ReconciliationRule, ReconciliationRun, User
from ledger.tasks import process_batch, run_reconciliation


SCENARIOS = {
    "historical_2022": (118, 1764),
    "historical_2023": (144, 1712),
    "control_baseline_2023": (100, 0),
    "controlled_faults_2023": (93, 11),
}


class Command(BaseCommand):
    help = "Seed and verify a persistent, read-only public interview demo."

    def handle(self, *args, **options):
        if not settings.LEDGERSYNC_PUBLIC_DEMO:
            raise CommandError("Set LEDGERSYNC_PUBLIC_DEMO=1 before seeding the public demo.")
        fixtures = settings.BASE_DIR.parent / "sample_data/public/benchrec"
        if not (fixtures / "normalized").is_dir():
            raise CommandError("Deploy from the repository root so the BenchRec fixtures are available.")
        # Serialize concurrent deploys. Reruns reuse completed batches and runs;
        # they never erase records, resolutions, or audit history.
        with transaction.atomic():
            organization, _ = Organization.objects.get_or_create(
                slug="ledger-sync-public-demo", defaults={"name": "LedgerSync Public Demo"},
            )
            Organization.objects.select_for_update().get(id=organization.id)
            user, _ = User.objects.get_or_create(username="demo@example.com")
            user.email = user.username
            user.organization = organization
            user.role = User.Role.AUDITOR
            user.is_staff = False
            user.is_superuser = False
            user.is_active = True
            if not user.check_password("Demo12345!"):
                user.set_password("Demo12345!")
            user.save()
            rule, _ = ReconciliationRule.objects.get_or_create(
                organization=organization, name="BenchRec exact reference, zero amount tolerance",
                defaults={"priority": 1, "date_variance_days": 2, "amount_tolerance_percent": Decimal("0")},
            )
            if (not rule.exact_reference_match or rule.date_variance_days != 2
                    or rule.amount_tolerance_percent != 0 or not rule.currency_must_match or not rule.is_active):
                raise CommandError("The public demo rule differs from the documented fixture policy.")
            snapshot = {
                "exact_reference_match": True, "date_variance_days": 2,
                "amount_tolerance_percent": "0", "currency_must_match": True,
            }
            for scenario, expected in SCENARIOS.items():
                paths = [fixtures / "normalized" / f"{scenario}_{side}.csv" for side in ("ledger", "bank")]
                hashes = [hashlib.sha256(path.read_bytes()).hexdigest() for path in paths]
                account = "public-" + scenario.replace("_", "-") + "-" + hashes[0][:6] + hashes[1][:6]
                batches = []
                for path, digest, source in zip(paths, hashes, (Batch.SourceType.ERP, Batch.SourceType.BANK)):
                    batch, created = Batch.objects.get_or_create(
                        organization=organization, source_type=source, source_account=account, checksum=digest,
                        defaults={"uploaded_by": user, "original_filename": path.name},
                    )
                    if batch.status != Batch.Status.COMPLETED:
                        # Render's disk is ephemeral; restore the shipped source
                        # file when resuming an incomplete seed after a restart.
                        with path.open("rb") as source_file:
                            batch.stored_file.save(path.name, File(source_file), save=True)
                        if created:
                            AuditLog.objects.create(
                                organization=organization, actor=user, action=AuditLog.Action.BATCH_UPLOADED,
                                entity_type="Batch", entity_id=batch.id,
                                payload={"filename": path.name, "source": "public demo seed"},
                            )
                        process_batch.apply(args=[str(batch.id)], throw=True)
                        batch.refresh_from_db()
                    if batch.failed_records:
                        raise CommandError(f"Invalid input rows in {path.name}.")
                    batches.append(batch)
                run, _ = ReconciliationRun.objects.get_or_create(
                    organization=organization, ledger_batch=batches[0], external_batch=batches[1],
                    defaults={"rule": rule, "rule_snapshot": snapshot},
                )
                if run.status != ReconciliationRun.Status.COMPLETED:
                    run_reconciliation.apply(args=[str(run.id)], throw=True)
                    run.refresh_from_db()
                if (run.matched_count, run.discrepancy_count) != expected:
                    raise CommandError(f"Unexpected results for {scenario}: {run.matched_count}, {run.discrepancy_count}.")
                # Ground truth is consumed ONLY after matching, by the offline
                # evaluator. It is never sent to the reconciliation engine.
                evidence = "controlled_faults_2023.json" if scenario == "controlled_faults_2023" else f"{scenario}_ground_truth.csv"
                output = StringIO()
                call_command("report_benchrec", run_id=str(run.id), evidence=str(fixtures / "evidence" / evidence), stdout=output)
                report = json.loads(output.getvalue())
                if report.get("false_predicted_pairs", 0):
                    raise CommandError(f"Incorrect predicted pairs in {scenario}.")
                self.stdout.write(f"{scenario}: {run.matched_count} matches, {run.discrepancy_count} flags (verified)")
        self.stdout.write(self.style.SUCCESS("Public demo ready: demo@example.com / Demo12345! (Auditor, no admin access)."))
