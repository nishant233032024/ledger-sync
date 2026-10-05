"""Inspect the downloaded source without modifying it or guessing its labels."""

import csv
import io
from collections import Counter, defaultdict
from decimal import Decimal
from pathlib import Path
from zipfile import ZipFile

ROOT = Path(__file__).resolve().parents[1]
ARCHIVE = ROOT / "sample_data/public/benchrec/raw/benchrec-v3.zip"


def main():
    with ZipFile(ARCHIVE) as archive:
        with archive.open("BenchRec_cash_v1.0_train.csv") as member:
            rows = list(csv.DictReader(io.TextIOWrapper(member, encoding="utf-8-sig", newline="")))
    grouped = defaultdict(lambda: {"A": [], "B": []})
    print("Training rows:", len(rows))
    for side in ("A", "B"):
        selected = [row for row in rows if row[f"{side}_id"]]
        print(side, "rows:", len(selected), "dates:", min(row[f"{side}_valueDate"] for row in selected),
              "to", max(row[f"{side}_valueDate"] for row in selected))
        print(side, "reference length", max(len(row[f"{side}_transactionReferences"].strip()) for row in selected))
        print(side, "blank references", sum(not row[f"{side}_transactionReferences"].strip() for row in selected))
        print(side, "signed amount range", min(Decimal(row[f"{side}_amount"]) for row in selected),
              max(Decimal(row[f"{side}_amount"]) for row in selected))
    for row in rows:
        if row["matchId"]:
            for side in ("A", "B"):
                if row[f"{side}_id"]:
                    grouped[row["matchId"]][side].append(row)
    categories = Counter()
    first_token_categories = Counter()
    examples = defaultdict(list)
    for match_id, sides in grouped.items():
        if len(sides["A"]) != 1 or len(sides["B"]) != 1:
            continue
        a, b = sides["A"][0], sides["B"][0]
        # These are supplied matched pairs, NOT labels for fraud or missing funds.
        same_ref = " ".join(a["A_transactionReferences"].upper().split()) == " ".join(b["B_transactionReferences"].upper().split())
        same_amount = Decimal(a["A_amount"]) == Decimal(b["B_amount"])
        same_date = a["A_valueDate"] == b["B_valueDate"]
        year = a["A_valueDate"][:4]
        key = (year, same_ref, same_amount, same_date)
        categories[key] += 1
        first_token_categories[(year,
            a["A_transactionReferences"].split()[0] == b["B_transactionReferences"].split()[0],
            same_amount, same_date)] += 1
        if len(examples[key]) < 2:
            examples[key].append({"match_id": match_id,
                "a_id": a["A_id"], "b_id": b["B_id"],
                "a_ref": a["A_transactionReferences"].strip(),
                "b_ref": b["B_transactionReferences"].strip(),
                "a_amount": a["A_amount"], "b_amount": b["B_amount"],
                "a_date": a["A_valueDate"], "b_date": b["B_valueDate"],
                "previous_mismatch": (a["wasPreviouslyMismatched"], b["wasPreviouslyMismatched"]),
            })
    print("One-to-one categories (year, equal reference, equal signed amount, equal date):")
    for key, count in sorted(categories.items()):
        print(key, count)
        if key[1] and not key[2]:
            print("  example:", examples[key][0])
    print("First-token categories (year, equal first token, equal signed amount, equal date):")
    for key, count in sorted(first_token_categories.items()):
        print(key, count)


if __name__ == "__main__":
    main()
