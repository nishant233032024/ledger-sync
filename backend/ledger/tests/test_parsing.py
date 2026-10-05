from datetime import datetime, timezone
from decimal import Decimal

import pytest

from ledger.parsing import RowValidationError, build_transaction_hash, normalize_row


def test_normalize_row_accepts_sample_shape():
    row = normalize_row({
        "reference": " inv-1 ", "amount": "12.3400", "currency": "usd",
        "timestamp": "2026-01-01T00:00:00Z", "direction": "credit",
    })
    assert row.reference == "inv-1"
    assert row.amount == Decimal("12.3400")
    assert row.currency == "USD"
    assert row.timestamp == datetime(2026, 1, 1, tzinfo=timezone.utc)


def test_normalize_row_rejects_negative_money():
    with pytest.raises(RowValidationError, match="nonnegative"):
        normalize_row({
            "reference": "inv-1", "amount": "-1", "currency": "USD",
            "timestamp": "2026-01-01T00:00:00Z",
        })


def test_hash_is_stable_for_equal_normalized_values():
    first = normalize_row({
        "reference": "INV-1", "amount": "10", "currency": "USD",
        "timestamp": "2026-01-01T00:00:00Z",
    })
    second = normalize_row({
        "reference": " INV-1 ", "amount": "10.0000", "currency": "usd",
        "timestamp": "2026-01-01T00:00:00+00:00",
    })
    assert build_transaction_hash(first) == build_transaction_hash(second)
