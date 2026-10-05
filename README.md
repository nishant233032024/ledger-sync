# LedgerSync

LedgerSync is a production-oriented financial reconciliation learning project.
It accepts ERP, bank, and payment-gateway files, imports them asynchronously,
deduplicates source rows, matches internal and external transactions, and lets
authorized finance users resolve discrepancies with an audit trail.

The repository is intentionally written as a modular Django application with
Celery workers. This gives you real enterprise patterns while keeping the
project understandable for a first professional portfolio application.

## Live interview demo

- **Dashboard:** https://ledger-sync-black.vercel.app
- **API health:** https://ledgersync-api.onrender.com/api/v1/health/
- **Source:** https://github.com/nishant233032024/ledger-sync
- **Sign in:** `demo@example.com` / `Demo12345!`

The public dashboard opens the controlled 2023 scenario: **200 source rows,
93 matched pairs, and 11 known injected exception flags**. Use the scenario
selector to compare the compatible baseline and historical 2022/2023 samples.
The account has read-only Auditor access. The free Render backend may take
about a minute to wake up after being idle.

The frontend runs on Vercel Hobby, the Python API on Render Free, and persistent
PostgreSQL on Neon's Free plan through Vercel's marketplace. See
[`docs/DEPLOYMENT.md`](docs/DEPLOYMENT.md) for hosting and interview details.
Pushes to `main` automatically deploy the frontend on Vercel and the API on Render.

## What you will build

```text
Next.js dashboard
        |
        v
Django REST Framework API
        |
        +------------------+
        |                  |
        v                  v
PostgreSQL            Redis + Celery
        |                  |
        +------ Docker ----+
```

## Fastest start with Docker

1. Install Docker Desktop and enable WSL integration if you use Windows WSL.
2. Copy the environment file:

   ```bash
   cp .env.example .env
   ```

3. Start all services:

   ```bash
   docker compose up --build
   ```

4. In another terminal, create an administrator:

   ```bash
   docker compose exec web python manage.py seed_demo
   ```

   The command creates a demo organization and user:

   ```text
   username: admin@example.com
   password: Admin12345!
   ```

5. Open the frontend at http://localhost:3000.
6. Open the API health endpoint at http://localhost:8000/api/v1/health/.

## Important Docker note

Your current terminal must be able to run both commands below before the Docker
steps can work:

```bash
docker --version
docker compose version
```

If WSL says that Docker cannot be found, open Docker Desktop, enable the WSL
integration for this distro, restart the terminal, and retry.

## Local backend without Docker

The settings automatically use SQLite when `DATABASE_URL` is empty. Redis is
still needed for normal asynchronous processing. This mode is useful for
learning Django models and running unit tests.

```bash
cd backend
python3.11 -m venv .venv
source .venv/bin/activate
pip install -r requirements/development.txt
python manage.py migrate
python manage.py seed_demo
python manage.py runserver
```

In another terminal, run Redis and a worker:

```bash
redis-server
cd backend
source .venv/bin/activate
celery -A config worker --loglevel=INFO
```

## Workflow demonstration

1. Log in with the demo user.
2. Upload `sample_data/erp_transactions.csv` with source type `ERP`.
3. Upload `sample_data/bank_transactions.csv` with source type `BANK`.
4. Copy both batch IDs from the upload responses or the Batches page.
5. Start a reconciliation run using the API request in `docs/STEP_BY_STEP.md`.
6. Review discrepancies in the dashboard.
7. Resolve an open discrepancy with a mandatory note.
8. Inspect the audit event in Django Admin or the API response.

## Real historical public data for interviews

The downloaded BenchRec archive contains production-derived, obfuscated ledger
and bank transaction records with historical value dates. The ready-to-upload
2022/2023 samples preserve published amounts and dates and keep answer labels
out of matching inputs. A separate, explicitly modified exercise demonstrates
known discrepancy outcomes.

See the provenance, measured results, and interview instructions in:

```text
sample_data/public/benchrec/README.md
```

With the Docker stack running, run from this project root:

```bash
python3 tools/validate_benchrec_files.py
python3 tools/run_benchrec_demo.py --scenario all
```

The historical engine flags are rule-review exceptions, not proof of bank errors.
The controlled exercise has verified 93 matches and all 11 expected flags.

## Documentation

The free public interview-demo deployment guide is
[`docs/DEPLOYMENT.md`](docs/DEPLOYMENT.md). It covers GitHub, Neon PostgreSQL,
Render's Python backend, Vercel, and end-to-end verification. The hosted demo
uses a read-only Auditor account with verified precomputed scenarios; Docker
provides the full asynchronous workflow.

The complete copy-paste learning guide is in:

```text
docs/STEP_BY_STEP.md
```

It explains the project in build order, every important file, API calls, data
flow, testing, and interview talking points.

## Verification commands

Backend:

```bash
cd backend
python manage.py check
python manage.py makemigrations --check --dry-run
pytest -q
```

Frontend:

```bash
cd frontend
npm run lint
npm run build
npx cypress install
npm run e2e
```

The Cypress command expects the Docker services to be running and the demo
account to exist. The frontend package includes a lockfile, so Docker uses
`npm ci` for reproducible dependency installation.

## Deliberate production choices

- PostgreSQL is the source of truth; Redis is a fast progress read model.
- The complete uploaded file has a checksum for repeat-file detection.
- Each source row has a normalized SHA-256 hash for repeat-row detection.
- Source type is part of the row uniqueness key so identical ERP and bank rows
  can still be reconciled against one another.
- Matching uses PostgreSQL row locks and uniqueness constraints.
- Celery tasks are retry-safe and return HTTP 202 for long-running work.
- Every manual resolution appends an audit event; Django Admin disables edits
  and deletes. Database-enforced immutability is a further production hardening step.
- Every API queryset is scoped to the authenticated organization.
