# LedgerSync: Copy-Paste Build Guide

This guide assumes you are learning Python full-stack engineering and want to
understand every layer instead of treating the project as a black box. The
repository already contains complete files. Copy a whole file from the path
shown below when you recreate it; do not merge individual snippets by hand.

## 0. What each service does

| Service | Port | Responsibility |
|---|---:|---|
| `frontend` | 3000 | Next.js dashboard and browser interactions |
| `web` | 8000 | Django REST API and Django Admin |
| `celery_worker` | none | File parsing, bulk import, matching |
| `celery_beat` | none | Periodic recovery and stale-job checks |
| `db` | 5432 | PostgreSQL source of truth |
| `redis` | 6379 | Celery broker, result backend, cache, locks |

The HTTP request never waits for a 100 MB file to finish processing. It stores
the upload, queues a task, and returns `202 Accepted`.

---

## 1. Prerequisites

Install:

- Git
- Docker Desktop with WSL integration, or Python 3.11+ and Node.js 20+
- An editor such as VS Code

Verify Docker before beginning:

```bash
docker --version
docker compose version
```

If you are using the already-created repository:

```bash
cd /home/nishantghuge/projects/my-new-project
```

If you are recreating it elsewhere, create the same directory structure and
copy the complete source files from the repository.

---

## 2. Configure secrets and services

Create a local environment file:

```bash
cp .env.example .env
```

For a personal local demo, the values in `.env.example` work. For a real
deployment, replace `DJANGO_SECRET_KEY` and the database password.

Start PostgreSQL, Redis, Django, workers, and Next.js:

```bash
docker compose up --build
```

What Docker does in this order:

1. Starts PostgreSQL and waits for `pg_isready`.
2. Starts Redis and waits for `redis-cli ping`.
3. Builds the backend image and installs `requirements/base.txt`.
4. Runs Django migrations.
5. Collects static files.
6. Starts Gunicorn on port 8000.
7. Starts Celery worker and beat as separate processes.
8. Builds and starts the Next.js standalone server on port 3000.

Open:

Dashboard: http://localhost:3000
Health:    http://localhost:8000/api/v1/health/
Admin:     http://localhost:8000/admin/
```

Create repeatable demo data:

```bash
docker compose exec web python manage.py seed_demo
```

Login credentials:

Username: admin@example.com
Password: Admin12345!
```

---

## 3. Understand the backend files in build order

### 3.1 `backend/config/settings.py`

Important lines and their purpose:

```python
AUTH_USER_MODEL = "ledger.User"
```

This tells Django to use the application user model instead of Django's
default user model. It must be configured before the first migration.

```python
DATABASES = {"default": database_from_environment()}
```

The helper selects PostgreSQL when `DATABASE_URL` exists and SQLite when it is
empty. Docker always supplies PostgreSQL. SQLite makes backend tests quick.

```python
CELERY_BROKER_URL = REDIS_URL
CELERY_RESULT_BACKEND = REDIS_URL
```

Celery publishes jobs to Redis and stores task results there. Django's cache
uses the same Redis service for short-lived progress objects.

```python
CELERY_TASK_ACKS_LATE = True
CELERY_TASK_REJECT_ON_WORKER_LOST = True
CELERY_WORKER_PREFETCH_MULTIPLIER = 1
```

These settings make worker failures safer: a task is acknowledged after work
finishes, abandoned work can return to the queue, and one worker does not take
many long jobs while another sits idle.

### 3.2 `backend/ledger/models.py`

The models represent the audit-safe financial domain:

1. `Organization` is the tenant boundary.
2. `User` stores Admin, Finance Manager, and Auditor roles.
3. `Batch` stores one source file and its processing counters.
4. `Transaction` stores normalized source data.
5. `BatchRow` stores the outcome for every source row.
6. `ReconciliationRule` stores matching tolerances.
7. `ReconciliationRun` records one ERP-versus-bank comparison.
8. `ReconciliationMatch` stores successful one-to-one pairs.
9. `Discrepancy` stores exceptions that need a human decision.
10. `AuditLog` stores append-only business events.

The most important constraint is:

```python
models.UniqueConstraint(
    fields=["organization", "source_type", "source_account", "source_row_hash"],
    name="unique_source_transaction_per_org_type",
)
```

The source type is intentionally included. If an ERP row and bank row have the
same reference and amount, they must both exist so the matching engine can pair
them. A repeat import within the same source is the duplicate.

`PROTECT` is used on financial foreign keys. A user cannot accidentally delete
an organization, batch, or transaction that is needed for an audit.

### 3.3 Migrations

The complete initial migration is:

```text
backend/ledger/migrations/0001_initial.py
```

After changing a model, run:

```bash
docker compose exec web python manage.py makemigrations
docker compose exec web python manage.py migrate
```

Always inspect a generated migration before applying it. A migration is part
of the source code and must be committed with the model change.

### 3.4 `backend/ledger/parsing.py`

The parser protects memory and data quality:

- CSV is read row by row.
- XLSX uses `openpyxl` read-only mode.
- XLS is capped and read through `xlrd`.
- Headers are validated before rows are inserted.
- Every row is normalized into `NormalizedTransaction`.
- Invalid rows produce a `BatchRow.INVALID` result instead of crashing the
  whole file.
- Amounts cannot be negative, infinite, or more precise than four decimals.
- Timestamps become UTC-aware values.

The hash is created from canonical values:

```python
values = [
    normalize_reference(row.reference),
    f"{row.amount:.4f}",
    row.timestamp.isoformat(),
    row.currency,
    row.direction,
    row.source_id,
]
```

This makes whitespace, case, and decimal formatting differences harmless while
retaining source identity fields.

### 3.5 `backend/ledger/importing.py`

`chunks()` is the memory boundary. It never loads the entire file:

```python
while group := list(islice(iterator, size)):
    yield group
```

Each chunk uses one database transaction:

1. Lock the organization briefly so concurrent importer counters are stable.
2. Skip source rows already committed to `BatchRow` during a retry.
3. Normalize valid rows.
4. Find source hashes already present for the same organization/source/account.
5. Bulk-create genuinely new `Transaction` records.
6. Bulk-create `BatchRow` outcomes.
7. Derive progress counters from durable `BatchRow` rows.
8. Write a short-lived progress object to Redis.

If a worker dies after a chunk commits, its retry sees the same batch row
numbers and safely skips those rows. This is the idempotency guarantee.

### 3.6 `backend/ledger/tasks.py`

`process_batch` is a Celery task, not a Django view. The Redis lock prevents
two deliveries of the same logical task from running at once. The task state
is still stored in PostgreSQL, so Redis is not a correctness dependency.

`dispatch_pending_jobs` is a small outbox-style recovery mechanism. If the API
successfully creates a batch but the broker is briefly unavailable, Celery Beat
eventually notices the `PENDING` record and dispatches it.

`mark_stale_batches` gives operators a visible failure state for jobs that have
been processing for more than two hours.

### 3.7 `backend/ledger/reconciliation.py`

The engine first locks the organization and then locks all source records in
the run. This release deliberately processes one reconciliation run at a time
per tenant, which is easy to reason about while demonstrating real concurrency
control.

For each ERP record:

1. Look up same-reference external candidates using the indexed normalized
   reference column.
2. Apply currency, direction, date-window, and amount-tolerance rules.
3. Match exactly one candidate.
4. Flag zero candidates as unmatched.
5. Flag multiple candidates as ambiguous.
6. Flag a same-reference candidate that fails one rule as a typed variance.
7. Mark unused external rows as unmatched external records.

Successful matches and discrepancies are bulk-written. Every decision also
gets an `AuditLog` record.

---

## 4. Run backend without Docker (optional)

This is useful if Docker is unavailable. Python's `venv` module must be
installed by your operating system first.

```bash
cd backend
python3.11 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements/development.txt
python manage.py migrate
python manage.py seed_demo
python manage.py runserver
```

In a second terminal, start Redis and a worker:

```bash
redis-server
cd backend
source .venv/bin/activate
celery -A config worker --loglevel=INFO
```

If you only want to run parser tests, Redis and PostgreSQL are not needed:

```bash
cd backend
source .venv/bin/activate
pytest -q
```

---

## 5. Use the API with copy-paste commands

These commands work from the project root when the Docker stack is running.

### 5.1 Get a JWT access token

```bash
LOGIN_RESPONSE=$(curl -sS -X POST http://localhost:8000/api/v1/auth/token/ \
  -H 'Content-Type: application/json' \
  -d '{"username":"admin@example.com","password":"Admin12345!"}')

echo "$LOGIN_RESPONSE"
ACCESS_TOKEN=$(python3 -c 'import json,sys; print(json.load(sys.stdin)["access"])' <<< "$LOGIN_RESPONSE")
```

The access token is short-lived. The refresh token is used at
`/api/v1/auth/token/refresh/` when a frontend needs a new access token.

### 5.2 Upload the ERP file

```bash
ERP_RESPONSE=$(curl -sS -X POST http://localhost:8000/api/v1/batches/upload/ \
  -H "Authorization: Bearer $ACCESS_TOKEN" \
  -F 'file=@sample_data/erp_transactions.csv' \
  -F 'source_type=ERP')

echo "$ERP_RESPONSE"
ERP_BATCH_ID=$(python3 -c 'import json,sys; print(json.load(sys.stdin)["data"]["id"])' <<< "$ERP_RESPONSE")
```

### 5.3 Upload the bank file

```bash
BANK_RESPONSE=$(curl -sS -X POST http://localhost:8000/api/v1/batches/upload/ \
  -H "Authorization: Bearer $ACCESS_TOKEN" \
  -F 'file=@sample_data/bank_transactions.csv' \
  -F 'source_type=BANK')

echo "$BANK_RESPONSE"
BANK_BATCH_ID=$(python3 -c 'import json,sys; print(json.load(sys.stdin)["data"]["id"])' <<< "$BANK_RESPONSE")
```

The response is `202 Accepted` because the worker is processing the file.

### 5.4 Poll a batch

```bash
curl -sS "http://localhost:8000/api/v1/batches/$ERP_BATCH_ID/status/" \
  -H "Authorization: Bearer $ACCESS_TOKEN"
```

Wait until the JSON state is `COMPLETED`. You can also open the dashboard and
watch the progress bar.

### 5.5 Start reconciliation

```bash
RUN_RESPONSE=$(curl -sS -X POST http://localhost:8000/api/v1/reconciliation/runs/ \
  -H "Authorization: Bearer $ACCESS_TOKEN" \
  -H 'Content-Type: application/json' \
  -d "{\"ledger_batch_id\":\"$ERP_BATCH_ID\",\"external_batch_id\":\"$BANK_BATCH_ID\"}")

echo "$RUN_RESPONSE"
```

### 5.6 Review transactions and discrepancies

```bash
curl -sS 'http://localhost:8000/api/v1/transactions/?page_size=50&status=MATCHED' \
  -H "Authorization: Bearer $ACCESS_TOKEN"

curl -sS 'http://localhost:8000/api/v1/discrepancies/?status=OPEN' \
  -H "Authorization: Bearer $ACCESS_TOKEN"
```

### 5.7 Resolve one discrepancy

Copy an ID from the discrepancy response:

```bash
DISCREPANCY_ID='replace-with-an-open-discrepancy-uuid'

curl -sS -X POST "http://localhost:8000/api/v1/discrepancies/$DISCREPANCY_ID/resolve/" \
  -H "Authorization: Bearer $ACCESS_TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{"resolution":"ACCEPTED_VARIANCE","note":"Approved after finance review of the settlement fee."}'
```

The database update and audit event are committed in one transaction.

---

## 6. Understand the frontend

The complete frontend is in `frontend/`.

```bash
cd frontend
npm install
npm run dev
```

Important files:

| File | Purpose |
|---|---|
| `app/page.tsx` | Browser authentication gate |
| `components/ledger-dashboard.tsx` | Dashboard, upload, tables, resolution |
| `components/query-provider.tsx` | TanStack Query cache provider |
| `components/ui.tsx` | Small shadcn-style reusable UI primitives |
| `lib/api.ts` | JWT-aware API client and upload progress |
| `lib/types.ts` | Backend response types |

The transaction table requests at most 100 server-side rows and uses TanStack
Virtual to render only visible rows. Virtualization reduces DOM work; it does
not replace server-side filtering and pagination.

The upload uses `XMLHttpRequest` because it exposes browser upload progress.
After the server returns a batch ID, TanStack Query polls the status endpoint
every 1.5 seconds until it reaches `COMPLETED` or `FAILED`.

Build the frontend exactly as CI would:

```bash
npm run build
```

Run the Cypress smoke test after the Docker stack is up and the demo account
has been created:

```bash
npx cypress install
npm run e2e
```

The test logs in, verifies the dashboard heading, and verifies the upload card.

---

## 7. Test and quality workflow

Run backend checks:

```bash
cd backend
source .venv/bin/activate
python manage.py check
python manage.py makemigrations --check --dry-run
pytest -q
```

The included tests cover:

- Normalization and UTC timestamps
- Negative money rejection
- Stable source hashing
- Public health endpoint
- RBAC-protected upload
- Full import, deduplication, matching, and discrepancy pipeline

When you add a feature, add a test for its business invariant rather than only
testing that a function was called. Examples:

- A repeated task cannot create a second transaction.
- A second worker cannot match the same transaction.
- An auditor cannot upload or resolve a discrepancy.
- A user cannot read another organization's records.

---

## 8. Production hardening checklist

Before a real deployment:

1. Replace local media storage with S3-compatible object storage.
2. Use managed PostgreSQL and Redis.
3. Keep secrets in the hosting platform's secret manager.
4. Use HTTPS and set production allowed hosts.
5. Add structured JSON logging and a request ID middleware.
6. Add rate limiting to login and upload endpoints.
7. Add antivirus/file scanning for untrusted uploads.
8. Use a staging table plus PostgreSQL `COPY` for multi-million-row files.
9. Add database backups and restore drills.
10. Add CI that runs migrations, backend tests, and `npm run build`.

The portfolio version already demonstrates the architecture patterns that
matter in a hiring discussion: tenant isolation, asynchronous work,
idempotency, bulk operations, indexing, concurrency controls, and auditability.
