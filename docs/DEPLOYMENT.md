# Deploy the interview demo for free

The public demo uses **Vercel Hobby** for Next.js, a **Render free Python web
service** for Django, and **Neon Free** for persistent PostgreSQL. Each provider
requires your own account. Select the free plans during setup.

## Current published deployment

- Dashboard: <https://ledger-sync-black.vercel.app>
- API: <https://ledgersync-api.onrender.com/api/v1>
- Repository: <https://github.com/nishant233032024/ledger-sync>
- Neon resource: `ledgersync-demo`, **Free**, Oregon (`pdx1`), provisioned through
  the Vercel marketplace. A separate Neon sign-in was not needed for this setup.

Vercel is connected to `nishant233032024/ledger-sync` with **Production Branch**
set to `main`, **Root Directory** set to `frontend`, and the **Next.js** framework.
Pushes to `main` automatically deploy the frontend to the production dashboard.
Render also deploys `main` automatically, using the repository root for the API
and shipped reconciliation fixtures.

Verification completed: 15 backend tests, frontend lint/build, production
dependency audit, Render Blueprint validation, live API checks, and a fresh
browser session covering sign-in, scenarios, pagination, reference search,
read-only controls, JWT refresh, and sign-out. The production dependency audit
reported zero vulnerabilities; build-only development dependencies have
separate audit findings.

Recheck the published API with:

```bash
python3 tools/verify_public_demo.py --api-url https://ledgersync-api.onrender.com/api/v1 --frontend-origin https://ledger-sync-black.vercel.app
```

## What the public link demonstrates

Sign in with `demo@example.com` / `Demo12345!`. This account is an **Auditor**,
with no Django Admin access. The dashboard opens the controlled 2023 exercise:
200 source rows, 93 matched pairs, and 11 known injected exception flags.

Use the scenario selector to compare all four verified exercises:

| Scenario | ERP / bank rows | Matched pairs | Flags |
| --- | --- | --- | --- |
| Historical 2022 | 1,000 / 1,000 | 118 | 1,764 |
| Historical 2023 | 1,000 / 1,000 | 144 | 1,712 |
| Compatible 2023 baseline | 100 / 100 | 100 | 0 |
| Controlled 2023 defects | 100 / 100 | 93 | 11 |

The actual importer and reconciliation service compute these results at initial
startup. A separate evaluator checks source-ID pairs and flags afterward; no
answer labels enter the matching inputs. Subsequent startups reuse the results.
Transactions, outcomes, and audit events persist in PostgreSQL.

The hosted API blocks financial write endpoints. The full interactive workflow
is demonstrated locally with Docker's Redis, Celery worker, and beat services.
Free Render does not provide a standalone free Celery worker or persistent
upload disk. Its web service sleeps when idle; first sign-in may take about a
minute. Neon also suspends idle compute. Open the link before your interview.
Free-plan quotas and provider policies can change; check each dashboard.

## 1. Publish the GitHub repository

From the project root, authenticate with GitHub CLI:

```bash
gh auth login --hostname github.com --git-protocol https --web
```

If you are using this prepared environment, the downloaded CLI is at
`/tmp/omnirush/gh_2.102.0_linux_amd64/bin/gh`; use that full path in place of `gh`.

Initialize Git if it has not been initialized yet, and inspect the files:

```bash
git init -b main
git status --short
git check-ignore .env backend/db.sqlite3 backend/media frontend/node_modules frontend/.next
```

Stage the project sources and public fixtures, inspect the staged changes, then
create the first commit and public repository:

```bash
git add .gitattributes .gitignore .env.example README.md docker-compose.yml render.yaml backend frontend docs sample_data tools
git diff --cached --stat
git diff --cached
git commit -m "Build LedgerSync reconciliation workspace and public demo"
gh repo create ledger-sync --public --source=. --remote=origin --push
```

The BenchRec archive and derived samples are deliberately public, attributed
fixtures. `.env`, local databases, media uploads, dependencies, and generated
build files are ignored.

## 2. Create persistent PostgreSQL on Neon

1. Sign in at <https://console.neon.tech> and create a **Free** project named
   `ledger-sync-demo`. Choose a region near Render's Oregon region.
2. Create/use a database named `neondb` or `ledger_sync`.
3. Copy the PostgreSQL connection string from **Connect**. Keep its query
   parameters, including `sslmode=require` and `channel_binding=require` if
   present. Django now passes those options to psycopg.
4. Save this string directly in Render's `DATABASE_URL` field in the next step.

The connection string contains the database password. Store it in the provider's
environment settings, not in a source file or chat message.

## 3. Deploy Django on Render

1. Sign in at <https://dashboard.render.com> and connect GitHub.
2. Choose **New → Blueprint** and select the `ledger-sync` repository.
3. Render reads `render.yaml` from the repository root. Confirm the web service
   plan is **Free**. Keep the repository root as the build root: the seed command
   needs both `backend/` and `sample_data/`.
4. Fill the prompted variables:

   | Variable | Value |
   | --- | --- |
   | `DJANGO_SECRET_KEY` | A newly generated random string of at least 50 characters |
   | `DATABASE_URL` | Your Neon PostgreSQL connection string |
   | `DJANGO_CORS_ALLOWED_ORIGINS` | Your final Vercel origin, e.g. `https://your-project.vercel.app` |
   | `DJANGO_CSRF_TRUSTED_ORIGINS` | Your Render HTTPS origin; update it once the actual hostname is known |

   Generate a secret locally with:

   ```bash
   python3 -c 'import secrets; print(secrets.token_urlsafe(64))'
   ```

   If the Vercel origin is not known yet, use `http://localhost:3000` temporarily
   and update it after step 4. Multiple allowed origins are comma-separated.

5. Deploy. The Blueprint installs Python dependencies and collects static files.
   `backend/deploy.py` then applies migrations, seeds and verifies the four
   exercises, cleans expired JWT records, and starts Gunicorn on Render's `PORT`.
6. Copy the actual service URL from Render. Check:

   ```text
   https://YOUR-ACTUAL-API.onrender.com/api/v1/health/
   ```

   Expected response:

   ```json
   {"data":{"status":"ok","service":"ledger-sync-api"}}
   ```

The Blueprint sets `DJANGO_DEBUG=0`, `LEDGERSYNC_PUBLIC_DEMO=1`, and
`DJANGO_TRUST_PROXY=1`. Django automatically allows `RENDER_EXTERNAL_HOSTNAME`
and trusts Render's forwarded HTTPS header, preventing redirect loops.
Never run `seed_demo` on this hosted service; `seed_public_demo` creates the
read-only account instead. The public-mode guard rejects the local admin seeder.

## 4. Deploy Next.js on Vercel

1. Sign in at <https://vercel.com> and import the GitHub repository.
2. Set **Root Directory** to `frontend` and **Framework Preset** to Next.js.
3. Add these environment variables for **Production**:

   ```text
   NEXT_PUBLIC_API_URL=https://YOUR-ACTUAL-API.onrender.com/api/v1
   NEXT_PUBLIC_DEMO=1
   ```

4. Deploy. `frontend/vercel.json` uses the lockfile and skips the Cypress binary
   download during install. The project builds on patched Next.js 15.5.x.
5. Copy the stable production origin, not a per-deployment preview URL.
6. In Render, set `DJANGO_CORS_ALLOWED_ORIGINS` to that exact HTTPS origin
   **without a trailing slash**. Set `DJANGO_CSRF_TRUSTED_ORIGINS` to the actual
   Render HTTPS origin. Save and wait for the backend redeploy.

`NEXT_PUBLIC_*` values are built into the browser bundle. Changing the API URL or
demo setting requires a new Vercel build. Never put secrets in these variables.

CLI sign-in is also available:

```bash
npm exec --yes --package=vercel -- vercel login
```

## 5. Verify the deployed API and browser

From the project root:

```bash
python3 tools/verify_public_demo.py --api-url https://YOUR-ACTUAL-API.onrender.com/api/v1 --frontend-origin https://YOUR-ACTUAL-APP.vercel.app
```

This verifies login, refresh, all scenario counts, transaction pagination,
discrepancy filters, denied writes, and browser CORS without printing JWTs.

Then open the Vercel URL in a private browser window and check:

1. Sign in with the public account. Confirm the read-only banner.
2. Controlled faults: 200 uploaded rows, 93% match rate, 11 open discrepancies.
3. Transactions: navigate to the second page and search a reference.
4. Discrepancies: inspect amount, date, currency, duplicate, ambiguous, and
   unmatched flags.
5. Baseline: 100% match rate, zero open flags.
6. Historical scenarios: explain why exact-reference matching has low recall
   and why those exceptions do not establish bank errors.
7. Sign out and sign in again. Refresh the page to verify session restoration.

## Interview explanation

> “This public link is a persistent, read-only view of results produced by my
> Django reconciliation engine. I use historical BenchRec data with documented
> attribution, and a separately labeled fault-injection exercise for precise
> correctness checks. In the full Docker deployment, ingestion and matching run
> asynchronously through Celery and Redis. I preserve source-row membership,
> snapshot matching rules, scope every query to a tenant, and record resolution
> events in the audit trail. PostgreSQL stores the durable state.”

Data provenance and detailed evidence are documented in
[`sample_data/public/benchrec/README.md`](../sample_data/public/benchrec/README.md).
