from django.core.files.base import ContentFile
from django.test import override_settings

import pytest

from ledger.models import (
    Batch, Organization, ReconciliationRule, ReconciliationRun, User,
)
from ledger.tasks import process_batch, run_reconciliation


ERP_CSV = (
    "reference,amount,currency,timestamp,counterparty,direction\n"
    "INV-1,10.00,USD,2026-01-01T00:00:00Z,Acme,CREDIT\n"
    "INV-2,20.00,USD,2026-01-02T00:00:00Z,Globex,CREDIT\n"
)

BANK_CSV = (
    "reference,amount,currency,timestamp,counterparty,direction\n"
    "INV-1,10.00,USD,2026-01-01T04:00:00Z,Acme,CREDIT\n"
    "UNKNOWN,30.00,USD,2026-01-02T00:00:00Z,Unknown,CREDIT\n"
)


def make_batch(organization, user, filename, content, source_type):
    batch = Batch.objects.create(
        organization=organization, uploaded_by=user, source_type=source_type,
        original_filename=filename, checksum=filename + source_type,
    )
    batch.stored_file.save(filename, ContentFile(content.encode()), save=True)
    return batch


@pytest.mark.django_db
@override_settings(
    CACHES={"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}},
    CELERY_TASK_ALWAYS_EAGER=True,
)
def test_import_and_reconciliation_pipeline():
    organization = Organization.objects.create(name="Pipeline Co", slug="pipeline-co")
    user = User.objects.create_user(
        username="pipeline@example.com", password="Password123!",
        organization=organization, role=User.Role.FINANCE_MANAGER,
    )
    rule = ReconciliationRule.objects.create(
        organization=organization, name="Default", date_variance_days=2,
        amount_tolerance_percent="0",
    )
    ledger = make_batch(organization, user, "ledger.csv", ERP_CSV, Batch.SourceType.ERP)
    external = make_batch(organization, user, "bank.csv", BANK_CSV, Batch.SourceType.BANK)

    process_batch.delay(str(ledger.id))
    process_batch.delay(str(external.id))
    ledger.refresh_from_db()
    external.refresh_from_db()
    assert ledger.status == Batch.Status.COMPLETED
    assert ledger.imported_records == 2
    assert external.imported_records == 2

    run = ReconciliationRun.objects.create(
        organization=organization, ledger_batch=ledger, external_batch=external,
        rule=rule, rule_snapshot={
            "date_variance_days": 2,
            "amount_tolerance_percent": "0",
            "currency_must_match": True,
        },
    )
    run_reconciliation.delay(str(run.id))
    run.refresh_from_db()
    assert run.status == ReconciliationRun.Status.COMPLETED
    assert run.matched_count == 1
    assert run.discrepancy_count == 2
