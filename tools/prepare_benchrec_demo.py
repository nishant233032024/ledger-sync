"""Build historical samples and an explicitly modified training exercise.

Run from the repository root: python3 tools/prepare_benchrec_demo.py

Financial calculations use Decimal. Publisher labels are ONLY written to
separate ground-truth files, never to matching inputs or transaction metadata.
"""

import csv
import hashlib
import io
import json
from collections import Counter, defaultdict
from copy import deepcopy
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path
from zipfile import ZipFile

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "sample_data/public/benchrec"
ARCHIVE = BASE / "raw/benchrec-v3.zip"
ARCHIVE_SHA256 = "46d6851a47f1888a7295ac5f7d49295f845b5041ddd18965fef7b79be1b86b4b"
TRAIN_MEMBER = "BenchRec_cash_v1.0_train.csv"
NORMALIZED = BASE / "normalized"
EVIDENCE = BASE / "evidence"

# These are deliberately small, curated TRAINING samples, not a held-out score
# for the complete benchmark. All amounts and source dates remain unchanged.
HISTORICAL_CASES_PER_YEAR = 1000
CONTROLLED_BASELINE_CASES = 100
INPUT_FIELDS = [
    "reference", "amount", "currency", "timestamp", "direction",
    "counterparty", "description", "source_id", "source_reference",
    "source_account", "source_signed_amount", "source_debit_or_credit",
    "source_value_date", "source_import_date", "source_member", "source_line",
]
TRUTH_FIELDS = [
    "match_id", "ledger_source_id", "bank_source_id", "ledger_allocation",
    "bank_target_allocation", "publisher_match_rule", "previously_mismatched",
    "ledger_source_reference", "bank_source_reference",
    "ledger_signed_amount", "bank_signed_amount", "signed_amount_difference",
    "absolute_amount_difference", "ledger_value_date", "bank_value_date",
    "date_difference_days", "meaning",
]


def sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as file_object:
        for part in iter(lambda: file_object.read(1024 * 1024), b""):
            digest.update(part)
    return digest.hexdigest()


def write_csv(path, fields, rows):
    # Independent source-ID ordering removes any accidental positional pairing
    # signal between the ledger and bank CSVs. Labels stay in evidence only.
    if fields == INPUT_FIELDS:
        rows = sorted(rows, key=lambda row: row["source_id"])
    with path.open("w", newline="", encoding="utf-8") as file_object:
        writer = csv.DictWriter(file_object, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def reference_from_source(value):
    """A simple, row-local adapter, independent of ANY answer labels.

    Source narrations contain several tokens. The first token is treated as a
    candidate reference for this application's exact-reference contract. This
    is an imperfect heuristic; the full source narration is retained for review.
    """
    return value.split()[0].upper()


def normalized_row(row, side):
    signed_amount = Decimal(row[f"{side}_amount"])
    value_date = date.fromisoformat(row[f"{side}_valueDate"])
    reference = row[f"{side}_transactionReferences"].strip()
    return {
        "reference": reference_from_source(reference),
        "amount": f"{abs(signed_amount):.4f}",
        "currency": row[f"{side}_currencyCode"],
        # The source has date-only values: midnight UTC is a normalization
        # convention, not a claim about the actual transaction's time of day.
        "timestamp": f"{value_date.isoformat()}T00:00:00Z",
        "direction": "DEBIT" if signed_amount < 0 else "CREDIT",
        "counterparty": "",  # No counterparty identity is supplied by BenchRec.
        "description": f"BenchRec production-derived, obfuscated source side {side}",
        "source_id": row[f"{side}_id"],
        "source_reference": reference,
        "source_account": row[f"{side}_account"],
        "source_signed_amount": str(signed_amount),
        "source_debit_or_credit": row[f"{side}_debitOrCredit"],
        "source_value_date": value_date.isoformat(),
        "source_import_date": row[f"{side}_importDate"],
        "source_member": TRAIN_MEMBER,
        "source_line": row["_source_line"],
    }


def ground_truth(match_id, a, b):
    a_amount, b_amount = Decimal(a["A_amount"]), Decimal(b["B_amount"])
    return {
        "match_id": match_id,
        "ledger_source_id": a["A_id"], "bank_source_id": b["B_id"],
        "ledger_allocation": a["A_allocation"],
        "bank_target_allocation": b["targetAllocation"],
        "publisher_match_rule": a["matchRule"] or b["matchRule"],
        "previously_mismatched": f"A={a['wasPreviouslyMismatched']};B={b['wasPreviouslyMismatched']}",
        "ledger_source_reference": a["A_transactionReferences"].strip(),
        "bank_source_reference": b["B_transactionReferences"].strip(),
        "ledger_signed_amount": str(a_amount), "bank_signed_amount": str(b_amount),
        "signed_amount_difference": str(b_amount - a_amount),
        "absolute_amount_difference": str(abs(b_amount) - abs(a_amount)),
        "ledger_value_date": a["A_valueDate"], "bank_value_date": b["B_valueDate"],
        "date_difference_days": abs((date.fromisoformat(a["A_valueDate"]) - date.fromisoformat(b["B_valueDate"])).days),
        "meaning": "Publisher-labeled 1:1 match; numerical differences are review evidence, not a fraud/loss label.",
    }


def load_source():
    grouped = defaultdict(lambda: {"A": [], "B": []})
    file_profiles = {}
    with ZipFile(ARCHIVE) as archive:
        # Count and checksum EVERY original member, including eval + solutions.
        # The third-party MatcherByChatGPT submission is not ground truth.
        for info in archive.infolist():
            digest = hashlib.sha256()
            with archive.open(info.filename) as file_object:
                for chunk in iter(lambda: file_object.read(1024 * 1024), b""):
                    digest.update(chunk)
            with archive.open(info.filename) as file_object:
                reader = csv.DictReader(io.TextIOWrapper(file_object, encoding="utf-8-sig", newline=""))
                counts = Counter()
                dates = defaultdict(list)
                total = 0
                for line, row in enumerate(reader, start=2):
                    total += 1
                    for side in ("A", "B"):
                        if row.get(f"{side}_id"):
                            counts[side] += 1
                            if row.get(f"{side}_valueDate"):
                                dates[side].append(row[f"{side}_valueDate"])
                            if info.filename == TRAIN_MEMBER:
                                row["_source_line"] = line
                                grouped[row["matchId"]][side].append(row)
                file_profiles[info.filename] = {
                    "rows": total, "uncompressed_bytes": info.file_size,
                    "sha256": digest.hexdigest(), "sides": dict(counts),
                    "value_date_ranges": {
                        side: {"first": min(values), "last": max(values)}
                        for side, values in dates.items()
                    },
                }
    return grouped, file_profiles


def make_controlled_lab(one_to_one):
    """Create test-only mutations whose causes and expected flags are known."""
    selected, seen = [], set()
    for match_id, a, b in one_to_one:
        if a["A_valueDate"][:4] != "2023" or b["B_valueDate"][:4] != "2023":
            continue
        na, nb = normalized_row(a, "A"), normalized_row(b, "B")
        if (na["reference"] != nb["reference"] or na["reference"] in seen
                or Decimal(a["A_amount"]) != Decimal(b["B_amount"])
                or na["timestamp"] != nb["timestamp"] or Decimal(na["amount"]) == 0):
            continue
        seen.add(na["reference"])
        selected.append((match_id, a, b))
        if len(selected) == CONTROLLED_BASELINE_CASES:
            break
    if len(selected) != CONTROLLED_BASELINE_CASES:
        raise ValueError("Not enough naturally matching unique 2023 reference tokens.")
    ledger = [normalized_row(a, "A") for _, a, _ in selected]
    bank = [normalized_row(b, "B") for _, _, b in selected]
    baseline_truth = [ground_truth(mid, a, b) for mid, a, b in selected]
    write_csv(NORMALIZED / "control_baseline_2023_ledger.csv", INPUT_FIELDS, ledger)
    write_csv(NORMALIZED / "control_baseline_2023_bank.csv", INPUT_FIELDS, bank)
    write_csv(EVIDENCE / "control_baseline_2023_ground_truth.csv", TRUTH_FIELDS, baseline_truth)

    modified_ledger, modified_bank = deepcopy(ledger), deepcopy(bank)
    expected_flags = []
    mutations = []

    def expect(row, kind, secondary=None):
        expected_flags.append({
            "reference": row["reference"], "primary_source_id": row["source_id"],
            "type": kind, "secondary_source_id": secondary["source_id"] if secondary else None,
        })

    # 1. A missing bank row simulates an unobserved settlement.
    modified_bank.remove(modified_bank[0])
    mutations.append({"kind": "remove_bank_row", "source_id": bank[0]["source_id"], "reason": "Controlled missing-settlement test."})
    expect(ledger[0], "UNMATCHED_LEDGER")

    # 2. Changing an amount is a KNOWN lab error, not an accusation about the bank.
    amount_row = next(row for row in modified_bank if row["source_id"] == bank[1]["source_id"])
    amount_row["amount"] = f"{Decimal(amount_row['amount']) + Decimal('1.25'):.4f}"
    mutations.append({"kind": "change_amount", "source_id": amount_row["source_id"], "before": bank[1]["amount"], "after": amount_row["amount"]})
    expect(ledger[1], "AMOUNT_VARIANCE", amount_row)

    # 3. Delay a posting beyond the configured +/- 2-day rule window.
    date_row = next(row for row in modified_bank if row["source_id"] == bank[2]["source_id"])
    date_row["timestamp"] = f"{date.fromisoformat(bank[2]['source_value_date']) + timedelta(days=10)}T00:00:00Z"
    mutations.append({"kind": "change_timestamp", "source_id": date_row["source_id"], "before": bank[2]["timestamp"], "after": date_row["timestamp"]})
    expect(ledger[2], "DATE_VARIANCE", date_row)

    # 4. Change currency while retaining a record of the original source value.
    currency_row = next(row for row in modified_bank if row["source_id"] == bank[3]["source_id"])
    currency_row["currency"] = "EUR"
    mutations.append({"kind": "change_currency", "source_id": currency_row["source_id"], "before": bank[3]["currency"], "after": "EUR"})
    expect(ledger[3], "CURRENCY_MISMATCH", currency_row)

    # 5. A distinct, marked event ID simulates a duplicate ledger posting.
    duplicate = deepcopy(ledger[4])
    duplicate["source_id"] += "-INJECTED-DUPLICATE"
    duplicate["description"] = "CONTROLLED INJECTION: duplicate posting; not an original BenchRec event"
    modified_ledger.append(duplicate)
    mutations.append({"kind": "duplicate_ledger_row", "original_id": ledger[4]["source_id"], "injected_id": duplicate["source_id"]})
    expect(ledger[4], "DUPLICATE_TRANSACTION")
    expect(duplicate, "DUPLICATE_TRANSACTION")
    expect(bank[4], "UNMATCHED_EXTERNAL")

    # 6. Remove its ledger counterpart to simulate an unrecorded receipt.
    modified_ledger.remove(next(row for row in modified_ledger if row["source_id"] == ledger[5]["source_id"]))
    mutations.append({"kind": "remove_ledger_row", "source_id": ledger[5]["source_id"], "reason": "Controlled bank-only receipt test."})
    expect(bank[5], "UNMATCHED_EXTERNAL")

    # 7. Two eligible bank candidates must be escalated, not arbitrarily chosen.
    ambiguous = deepcopy(bank[6])
    ambiguous["source_id"] += "-INJECTED-AMBIGUITY"
    ambiguous["description"] = "CONTROLLED INJECTION: second eligible candidate; not an original BenchRec event"
    modified_bank.append(ambiguous)
    mutations.append({"kind": "duplicate_bank_candidate", "original_id": bank[6]["source_id"], "injected_id": ambiguous["source_id"]})
    expect(ledger[6], "AMBIGUOUS_MATCH")
    expect(bank[6], "UNMATCHED_EXTERNAL")
    expect(ambiguous, "UNMATCHED_EXTERNAL")

    for row in modified_ledger + modified_bank:
        row["description"] = "CONTROLLED LAB / " + row["description"]
    write_csv(NORMALIZED / "controlled_faults_2023_ledger.csv", INPUT_FIELDS, modified_ledger)
    write_csv(NORMALIZED / "controlled_faults_2023_bank.csv", INPUT_FIELDS, modified_bank)
    report = {
        "kind": "CONTROLLED_FAULT_INJECTION_NOT_ORIGINAL_BANK_ERRORS",
        "derived_from": "100 naturally compatible labeled 2023 BenchRec pairs",
        "rule": {"exact_reference_match": True, "date_variance_days": 2, "amount_tolerance_percent": "0", "currency_must_match": True},
        "ledger_rows": len(modified_ledger), "bank_rows": len(modified_bank),
        "expected_matches": len(selected) - 7,
        "expected_matched_source_pairs": [
            [a["A_id"], b["B_id"]] for _, a, b in selected[7:]
        ],
        "expected_discrepancy_count": len(expected_flags),
        "expected_discrepancy_types": dict(Counter(flag["type"] for flag in expected_flags)),
        "mutations": mutations, "expected_flags": expected_flags,
    }
    (EVIDENCE / "controlled_faults_2023.json").write_text(json.dumps(report, indent=2) + "\n")
    return report


def main():
    if not ARCHIVE.exists():
        raise SystemExit("Download the BenchRec v3 archive with tools/download_benchrec.py first.")
    if sha256(ARCHIVE) != ARCHIVE_SHA256:
        raise SystemExit("Archive checksum changed. Review the new source before adapting it.")
    NORMALIZED.mkdir(parents=True, exist_ok=True)
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    groups, profiles = load_source()
    # Selecting complete labeled 1:1 groups preserves their counterpart rows.
    # A-only/B-only groups may represent same-side netting; they are NOT assumed
    # to be genuine missing payments or losses.
    one_to_one = sorted([
        (match_id, sides["A"][0], sides["B"][0])
        for match_id, sides in groups.items()
        if match_id and len(sides["A"]) == len(sides["B"]) == 1
    ], key=lambda group: group[0])
    scenarios = {}
    for year in ("2022", "2023"):
        selected = [group for group in one_to_one
                    if group[1]["A_valueDate"][:4] == year and group[2]["B_valueDate"][:4] == year][:HISTORICAL_CASES_PER_YEAR]
        ledger = [normalized_row(a, "A") for _, a, _ in selected]
        bank = [normalized_row(b, "B") for _, _, b in selected]
        truth = [ground_truth(mid, a, b) for mid, a, b in selected]
        write_csv(NORMALIZED / f"historical_{year}_ledger.csv", INPUT_FIELDS, ledger)
        write_csv(NORMALIZED / f"historical_{year}_bank.csv", INPUT_FIELDS, bank)
        write_csv(EVIDENCE / f"historical_{year}_ground_truth.csv", TRUTH_FIELDS, truth)
        differences = [row for row in truth if Decimal(row["signed_amount_difference"]) != 0 or row["date_difference_days"] != 0]
        write_csv(EVIDENCE / f"historical_{year}_observed_differences.csv", TRUTH_FIELDS, differences)
        scenarios[year] = {
            "publisher_labeled_pairs": len(selected), "ledger_rows": len(ledger), "bank_rows": len(bank),
            "first_value_date": min(row["source_value_date"] for row in ledger + bank),
            "last_value_date": max(row["source_value_date"] for row in ledger + bank),
            "pairs_with_signed_amount_difference": sum(Decimal(row["signed_amount_difference"]) != 0 for row in truth),
            "pairs_with_date_difference": sum(row["date_difference_days"] != 0 for row in truth),
            "reference_tokens_agree": sum(a["reference"] == b["reference"] for a, b in zip(ledger, bank, strict=True)),
        }
    lab = make_controlled_lab(one_to_one)
    profile = {"archive_sha256": ARCHIVE_SHA256, "original_members": profiles,
               "normalized_file_sha256": {
                   path.name: sha256(path) for path in sorted(NORMALIZED.glob("*.csv"))
               },
               "historical_training_samples": scenarios,
               "controlled_lab": {key: lab[key] for key in ("ledger_rows", "bank_rows", "expected_matches", "expected_discrepancy_count", "expected_discrepancy_types")}}
    (EVIDENCE / "dataset_profile.json").write_text(json.dumps(profile, indent=2) + "\n")
    print(json.dumps(profile, indent=2))


if __name__ == "__main__":
    main()
