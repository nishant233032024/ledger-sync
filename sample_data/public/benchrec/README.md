# Historical general-ledger and bank transactions for LedgerSync

**Downloaded and validated: BenchRec by Operartis, Kaggle release v3.**
It is a production-derived, obfuscated reconciliation benchmark, not a named
business's unredacted bank statement or audited proof of financial losses.

## Source and attribution

> Derived from **BenchRec: A Real-World Cash Reconciliation Dataset**, published
> by BenchRec / Operartis; originally introduced at ICAIF 2023.
> Source: https://www.kaggle.com/datasets/benchmarkteam/benchrec-real-world-cash-reconciliation-dataset
> License: **Creative Commons Attribution 4.0 International (CC BY 4.0)**,
> https://creativecommons.org/licenses/by/4.0/.
> LedgerSync adaptations: subset selection, CSV column mapping, first-token
> reference extraction, signed-amount/direction normalization and date-only
> timestamps. The controlled exercise additionally modifies seven cases, all
> documented in a separate manifest. No publisher endorsement is implied.

The publisher describes the training/evaluation files as obfuscated matched
general-ledger and bank transactions taken from a production reconciliation
at a Tier-1 financial institution:

- Publisher: https://www.operartis.com/benchrec
- Conference listing: https://ai-finance.org/icaif-23-competitions-datasets/
- Original competition: https://sites.google.com/view/fintranmatch-competition-icaif
- Saved license/description evidence: `evidence/kaggle-metadata.json`
- Original release archive: `raw/benchrec-v3.zip`
- Verified archive SHA-256:
  `46d6851a47f1888a7295ac5f7d49295f845b5041ddd18965fef7b79be1b86b4b`
- Downloaded: 2026-10-05; dataset v3 published 2026-02-22.

**2023 is the original competition year, not the release date of this Kaggle
snapshot.** The supplied transaction dates are older, as shown below.

## What was downloaded

The archive preserves these source files byte-for-byte. Unzip it if you want
to inspect the original CSVs; the preparation scripts read it directly.

| Original archive member | Source rows | Notes |
|---|---:|---|
| `BenchRec_cash_v1.0_train.csv` | 149,854 | 80,879 A-ledger + 68,975 B-bank records |
| `BenchRec_cash_v1.0_eval.csv` | 69,171 | 37,123 A-ledger + 32,048 B-bank records |
| `BenchRec_cash_v1.0_solution.csv` | 32,048 | Evaluation B allocation labels, not extra transactions |
| `MatcherByChatGPT_submission.csv` | 32,048 | Third-party predictions, **not ground truth** |

The training and evaluation source files contain **219,025 transaction rows**
combined. Published value dates span **2015-03-08 through 2023-05-31**. Most
usable records are from 2022 and 2023; sparse older dates should not be presented
as complete annual ledgers. The data does not supply opening/closing bank
balances, named counterparties, or a complete audited company's books.

`evidence/dataset_profile.json` contains counts, date ranges and checksums for
each original member.

## Ready-to-upload scenarios

| Scenario | Ledger CSV | Bank CSV | Rows per side |
|---|---|---|---:|
| Historical 2022 | `normalized/historical_2022_ledger.csv` | `normalized/historical_2022_bank.csv` | 1,000 |
| Historical 2023 | `normalized/historical_2023_ledger.csv` | `normalized/historical_2023_bank.csv` | 1,000 |
| Compatible baseline | `normalized/control_baseline_2023_ledger.csv` | `normalized/control_baseline_2023_bank.csv` | 100 |
| Explicit fault injection | `normalized/controlled_faults_2023_ledger.csv` | `normalized/controlled_faults_2023_bank.csv` | 100 |

The historical samples retain complete, publisher-labeled 1:1 training groups.
Each year's sample selects the first 1,000 qualifying groups in lexicographic
`matchId` order with both value dates in that year. These are reproducible
**training subsets**, not random samples or independent held-out benchmarks.

### Normalization rules

- Financial conversions use `Decimal`, never float rounding.
- Source signed amounts are retained in `source_signed_amount`.
- Upload amount is `abs(source_signed_amount)`; its cash sign maps to
  `DEBIT`/`CREDIT`. A and B use opposite DR/CR source conventions.
- Upload timestamp is value date at midnight UTC. The original has no exact
  transaction time or timezone; this is an explicit application convention.
- Upload reference is the **first whitespace-delimited token of that row's
  own source reference**. This imperfect heuristic does not look at its answer
  label or counterpart. Full narration is preserved in `source_reference`.
- No counterparty is invented. `counterparty` is empty.
- Original IDs, accounts, dates, archive member and source CSV row number are
  included so each row can be traced to the raw download.
- Bank and ledger exports are sorted independently by their native source IDs,
  so CSV row ordering does not reveal the matching answer.
- `matchId`, `targetAllocation`, allocation answers, publisher matching rules
  and expected outcomes are kept **only in offline evidence files**. They are
  never passed to ingestion or used as matching references.

**This prevents answer leakage.** Using a ground-truth match ID as both inputs'
reference would create an artificially perfect demo, not a valid matching test.

## Verified results from the live Docker stack

The samples were uploaded over HTTP, processed by Celery, then matched in
PostgreSQL. A diagnostic command compared actual source-ID pairs to the
separate publisher evidence.

| Scenario | Matched pairs | Correct predicted pairs | Pair recall | Flags |
|---|---:|---:|---:|---:|
| Historical 2022 | 118 | 118 | 11.8% | 1,764 |
| Historical 2023 | 144 | 144 | 14.4% | 1,712 |
| Compatible baseline | 100 | 100 | 100% | 0 |
| Controlled faults | 93 | 93, source-ID checked | N/A: controlled test | 11 |

All **4,400 uploaded rows** across the four scenarios imported with **zero
invalid rows**. Historical predicted-pair precision was 100% on these selected
subsets; that does not establish production or full-benchmark precision.

Historical flagged rows are **rule exceptions**, often caused by differently
encoded references. The publisher labels all selected historical groups as
matches. Therefore the 1,764/1,712 flags must not be described as discovered
missing funds, fraud, or genuine unreconciled business errors.

### Published numerical differences worth showing in an interview

These values are copied from labeled source pairs, without changing amounts:

| Value date | Ledger ID | Bank ID | Ledger signed amount | Bank signed amount | Bank minus ledger |
|---|---|---|---:|---:|---:|
| 2022-10-08 | `221175352414` | `822317838268` | 34,132,298.50 | 34,132,298.51 | +0.01 |
| 2023-02-15 | `999999971244` | `847060414303` | 2,235,043.10 | 2,235,043.11 | +0.01 |

Another 2023 pair, ledger `283871585919` and bank `852666314193`, has the same
published amount but value dates **2023-01-06 and 2023-01-27**, a 21-day gap.

The historical files contain **20 amount-difference pairs in 2022** and
**25 in 2023**; date differences occur in **4 and 21 pairs**, respectively.
They are independently computed in:

```text
evidence/historical_2022_observed_differences.csv
evidence/historical_2023_observed_differences.csv
```

The publisher labels these as matched records. The difference is observable;
its business cause is not supplied. Do not invent a bank-fee or fraud explanation.
The current first-token rule often cannot identify these pairs automatically;
the offline evidence report shows why they need better reference extraction
or human review.

### Exactly known discrepancies: the controlled exercise

This exercise starts with 100 naturally compatible 2023 source pairs. It then
explicitly removes/changes records in seven cases. Its known results are:

| Flag | Expected and verified |
|---|---:|
| Unmatched ledger | 1 |
| Amount variance | 1 |
| Date variance | 1 |
| Currency mismatch | 1 |
| Duplicate ledger transactions | 2 |
| Ambiguous match | 1 |
| Unmatched external | 4 |
| **Total flags** | **11** |

Why eleven flags from seven mutations? Duplicate/ambiguous cases flag multiple
records and leave external records for review. Every mutation, before/after
value, expected primary/secondary source ID and expected matched pair is in:

```text
evidence/controlled_faults_2023.json
```

Actual flags and matched pairs were checked by source IDs, not just counts:

```text
evidence/controlled_faults_2023_live_report.json
verification: PASS
```

**These are injected test defects, not original errors at the source institution.**
They provide a correct, reproducible exception workflow demo without making
unsupported claims about a real business.

## Run it again

From the project root, with the existing Docker stack running:

```bash
python3 tools/validate_benchrec_files.py
python3 tools/run_benchrec_demo.py --scenario all
```

Or run a single scenario:

```bash
python3 tools/run_benchrec_demo.py --scenario controlled_faults_2023
```

The loader uses the seeded `Demo Finance Co.` account, creates a dedicated
zero-amount-tolerance rule, waits for jobs to finish, and writes live reports
under `evidence/`. It reuses completed runs on repeated execution and does not
delete existing application data. Distinct `source_account` namespaces include
the input hashes, keeping baseline/historical/modified versions from
deduplicating against each other or silently reusing an older fixture.

On Windows WSL it automatically uses this Docker CLI if available:

```text
/mnt/c/Users/nisha/AppData/Local/Programs/DockerDesktop/resources/bin/docker.exe
```

On another machine use `--docker-command /path/to/docker` if required. Run the
script from the project root so Docker Compose finds the correct project.

### View the verified controlled flags

The current controlled run ID is recorded in its live report. The run tested
on this workspace is `558fdccc-b218-4be8-a57f-0778b7a61631`.
Use the Postman collection's login and then:

```text
GET /api/v1/discrepancies/?run_id=558fdccc-b218-4be8-a57f-0778b7a61631&page_size=50
```

The dashboard's newest open discrepancies also include these test flags. The
loader has already performed all four runs; do not start an identical pair again.

### Re-download and regenerate

```bash
python3 tools/download_benchrec.py
python3 tools/prepare_benchrec_demo.py
python3 tools/validate_benchrec_files.py
```

The downloader pins version 3, checks its archive hash, records the metadata,
and refuses silently changed license/version declarations. Preserve this
attribution file when sharing the dataset.

## Honest interview summary

> “I evaluated LedgerSync with production-derived, anonymized GL and bank
> transaction data published by Operartis/BenchRec for the ICAIF benchmark.
> I retained raw-source hashes and row provenance, kept answer labels out of
> matching inputs, and tested 2022 and 2023 training subsets. My simple rule
> matched only 11.8–14.4% of labeled pairs, with no false predicted pairs in
> those subsets. Separately, I injected seven documented faults into a compatible
> fixture and verified all eleven expected exception flags by source ID.”

Useful discussion points:

1. **Precision versus coverage:** rejecting unsafe matches is valuable, but low
   recall shows where the reference adapter must improve.
2. **Ground truth versus business truth:** supplied match labels are not labels
   for fraud or missing cash. The publisher acknowledges an estimated 0.2%
   label-error rate; do not promise that every published pairing is infallible.
3. **Grouped settlements:** the full archive has 1:N, N:1, same-side netting,
   and more complex cases. They need match lines and allocation-based evaluation,
   beyond the current one-to-one application.
4. **Independent evaluation:** the untouched eval/solution members remain
   available. A true held-out evaluation should use allocation targets and the
   publisher's metrics, not claim this curated training result as its score.
