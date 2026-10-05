"""Check provenance, decimal preservation and absence of answer leakage.

Run: python3 tools/validate_benchrec_files.py
This reads the raw archive and independently checks every unmodified export.
"""

import csv
import io
import json
from decimal import Decimal
from zipfile import ZipFile

from prepare_benchrec_demo import (
    ARCHIVE, ARCHIVE_SHA256, EVIDENCE, INPUT_FIELDS, NORMALIZED,
    TRAIN_MEMBER, normalized_row, sha256,
)

FORBIDDEN = {
    "matchId", "match_id", "match_group", "matchDate", "matchRule", "matchedBy",
    "targetAllocation", "target_allocation", "A_allocation", "ledger_allocation",
    "expected_outcome", "relationship", "wasPreviouslyMismatched",
}


def read_csv(path):
    with path.open(newline="", encoding="utf-8") as file_object:
        reader = csv.DictReader(file_object)
        fields = reader.fieldnames
        rows = list(reader)
    return fields, rows


def main():
    if sha256(ARCHIVE) != ARCHIVE_SHA256:
        raise ValueError("The original archive differs from the verified source snapshot.")
    source = {}
    with ZipFile(ARCHIVE) as archive, archive.open(TRAIN_MEMBER) as binary_file:
        reader = csv.DictReader(io.TextIOWrapper(binary_file, encoding="utf-8-sig", newline=""))
        for number, row in enumerate(reader, start=2):
            row["_source_line"] = number
            for side in ("A", "B"):
                if row[f"{side}_id"]:
                    source[(side, row[f"{side}_id"])] = row
    result = {}
    for scenario in ("historical_2022", "historical_2023", "control_baseline_2023"):
        for label, side in (("ledger", "A"), ("bank", "B")):
            name = f"{scenario}_{label}.csv"
            fields, rows = read_csv(NORMALIZED / name)
            if set(fields) & FORBIDDEN:
                raise ValueError(f"Answer labels leaked into {name}.")
            if fields != INPUT_FIELDS:
                raise ValueError(f"Unexpected schema in {name}.")
            if len(rows) != len({row["source_id"] for row in rows}):
                raise ValueError(f"Repeated source IDs in {name}.")
            for row in rows:
                original = source[(side, row["source_id"])]
                expected = {key: str(value) for key, value in normalized_row(original, side).items()}
                if row != expected:
                    raise ValueError(f"Source preservation failed in {name}: {row['source_id']}.")
                if Decimal(row["amount"]) != abs(Decimal(original[f"{side}_amount"])):
                    raise ValueError("Financial precision was lost.")
            result[name] = {"rows": len(rows), "source_preservation": "PASS", "answer_leakage": "NONE"}
        _, truth = read_csv(EVIDENCE / f"{scenario}_ground_truth.csv")
        for item in truth:
            a = source[("A", item["ledger_source_id"])]
            b = source[("B", item["bank_source_id"])]
            if a["matchId"] != b["matchId"] or a["matchId"] != item["match_id"]:
                raise ValueError("Ground-truth source grouping differs.")
            if Decimal(item["signed_amount_difference"]) != Decimal(b["B_amount"]) - Decimal(a["A_amount"]):
                raise ValueError("An observed difference was calculated incorrectly.")
    # Independently reconstruct the documented mutations from the unmodified
    # source-derived baseline; any other changes must fail validation.
    manifest = json.loads((EVIDENCE / "controlled_faults_2023.json").read_text())
    expected = {}
    for label in ("ledger", "bank"):
        _, rows = read_csv(NORMALIZED / f"control_baseline_2023_{label}.csv")
        expected[label] = {row["source_id"]: row for row in rows}
    for mutation in manifest["mutations"]:
        kind = mutation["kind"]
        if kind.startswith("remove_"):
            side = "bank" if kind == "remove_bank_row" else "ledger"
            del expected[side][mutation["source_id"]]
        elif kind.startswith("change_"):
            field = kind.removeprefix("change_")
            row = expected["bank"][mutation["source_id"]]
            if row[field] != mutation["before"]:
                raise ValueError("A mutation's before-value differs from the source baseline.")
            row[field] = mutation["after"]
        else:
            side = "ledger" if kind == "duplicate_ledger_row" else "bank"
            row = dict(expected[side][mutation["original_id"]])
            row["source_id"] = mutation["injected_id"]
            row["description"] = (
                "CONTROLLED INJECTION: duplicate posting; not an original BenchRec event"
                if side == "ledger" else
                "CONTROLLED INJECTION: second eligible candidate; not an original BenchRec event"
            )
            expected[side][row["source_id"]] = row
    for side in expected.values():
        for row in side.values():
            row["description"] = "CONTROLLED LAB / " + row["description"]
    for label in ("ledger", "bank"):
        fields, rows = read_csv(NORMALIZED / f"controlled_faults_2023_{label}.csv")
        if set(fields) & FORBIDDEN or not all(row["description"].startswith("CONTROLLED LAB") for row in rows):
            raise ValueError("Controlled lab is not explicitly labeled or leaked answers.")
        if len(rows) != len(expected[label]) or {row["source_id"]: row for row in rows} != expected[label]:
            raise ValueError("A controlled fixture has undocumented changes.")
    report = {"status": "PASS", "files": result,
              "controlled_lab": "Mutations are explicit; originals remain separate."}
    (EVIDENCE / "file_validation.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
