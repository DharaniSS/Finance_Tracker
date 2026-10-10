# SpendWise

SpendWise is a personal expense tracker with authenticated accounts, transaction management, category budgets, database-backed reporting, CSV preview/import, and explainable local anomaly analysis.

## Architecture

- `app.py`: Flask routes, authentication, transaction/category/budget/dashboard/anomaly APIs.
- `extensions.py`: shared SQLAlchemy, Flask-Login, Flask-Session, and CSRF extensions.
- `models.py`: users, categories, transactions, monthly budgets, import receipts, anomaly results.
- `services.py`: monthly budget calculations and local historical anomaly scoring.
- `templates/`, `static/`: existing HTML/CSS/JavaScript interface and Plotly charts.
- `migrations/`: Flask-Migrate/Alembic migration history.
- `init_db.py`: explicit, non-destructive database initialization and schema verification.
- `tests/`: isolated SQLite-backed authentication, transaction, category, budget, dashboard, anomaly, import, and security tests.

Transaction, category, budget, dashboard, and anomaly API queries are scoped to the authenticated user. Browser JavaScript holds only short-lived response data in memory; it does not use localStorage as the authority for financial records.

## Setup

Prerequisites: Python 3.12 or newer and PowerShell on Windows (commands below use the project virtual environment).

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

Set a stable secret for development sessions. Use a secret manager/environment configuration in deployment; never commit an actual key.

```powershell
$env:SPENDWISE_SECRET_KEY = "<replace-with-a-random-secret>"
```

For HTTPS deployments, also set `$env:SPENDWISE_COOKIE_SECURE = "1"`. Leave it unset for local HTTP. `SPENDWISE_DATABASE_PATH` and `SPENDWISE_SESSION_DIR` can point to isolated paths for local/test configurations; by default the SQLite database and server-side filesystem sessions live below `instance/`.

## Database and Migrations

The default database is `instance/spendwise.db`. For a fresh development database:

```powershell
python init_db.py
python -m flask --app app db upgrade
```

For an existing database with the original SpendWise base tables, apply reviewed schema revisions with:

```powershell
python -m flask --app app db upgrade
```

The current migration adds the case-folded category key, import digest support, and anomaly-analysis table/indexes without dropping tables or rows. It stops before applying the category uniqueness index if existing names conflict under Unicode case-folding. Resolve any reported conflict deliberately, then rerun the migration. `init_db.py` is explicit and non-destructive; it creates missing tables and supported additive columns, and verifies SQLite foreign-key enforcement. It is not run automatically at app startup.

Back up the SQLite file before applying future schema revisions. Do not use `drop_all()` against user data. The current migration is forward-only; rollback requires restoring a verified backup.

## Run and Test

```powershell
python app.py
```

Open `http://127.0.0.1:5000/`. Run the complete isolated test suite with:

```powershell
python -m unittest discover -s tests -v
```

Tests redirect the app to a temporary SQLite database before Flask initializes its engine and remove that database afterward. They do not use `instance/spendwise.db`.

## CSV Import

The expenses page accepts UTF-8 `.csv` files up to 1 MB and 100 transaction rows. Required headers are `date`, `description`, `amount`, and `category`; header capitalization, separators, and surrounding whitespace are normalized. `merchant` is optional and defaults to `description`. Dates must use `YYYY-MM-DD`. Amounts must be positive, with at most two decimal places; negative amounts are rejected. Categories are matched by name against the signed-in user's active categories.

The server validates the full file and previews valid and invalid rows before confirmation. Invalid rows are shown with reasons and excluded; no transaction is saved before confirmation. A confirmed preview is idempotent, and the exact same file bytes cannot be imported twice for one account. Legitimate recurring purchases are not deduplicated just because their values match. Uploaded files are processed in memory, not stored permanently.

## Budgets

Monthly budgets belong to a user/category/year/month and are protected by a database uniqueness constraint. The category page’s month selector can view and edit historical budget records without changing other months. Spending totals use transaction dates and Decimal amounts. Thresholds are category-configurable (default 80%): below threshold is normal, threshold-to-under-100% is warning, and 100% or more is exceeded. A zero/no budget is reported as unbudgeted, with no percentage division. Uncategorized transactions count toward total spending but not a category budget.

## Anomaly Analysis

Anomaly analysis is local and deterministic; it makes no external AI/API calls. On explicit user request, each categorized transaction is compared only with earlier transactions in its category. The service uses the historical median and median absolute deviation, with a three-times-median floor. At least five earlier observations are required; otherwise the result is `insufficient_history` and is not flagged. Results include explanation, baseline, threshold, sample count, severity/confidence where available, and analysis time. Reanalysis updates one result per user/transaction. Transaction mutations invalidate that user's prior results. Users can acknowledge an alert without changing the transaction.

An anomaly is a potential unusual-spending indicator, not proof of fraud. Budget warnings are deterministic calculations, not anomaly predictions.

## Security and Limitations

- Passwords use Werkzeug scrypt hashes; authentication uses Flask-Login without remember-me.
- Flask-WTF CSRF protects state-changing forms/API requests. Session contents are server-side; cookies are HttpOnly and SameSite=Lax, with a 30-minute server lifetime.
- Set `SPENDWISE_SECRET_KEY` to a stable high-entropy value in deployment. If omitted, the app generates an ephemeral development key and sessions will not survive process restarts.
- Set `SPENDWISE_COOKIE_SECURE=1` behind HTTPS. The Flask development server is not for production.
- Filesystem-backed sessions are local to one app instance; multi-instance deployments need a shared session store and a production WSGI server.
- Email verification, password recovery, login rate limiting, and account deletion workflows are not implemented.
- Categories, budgets, transactions, and analyses are account-scoped. The legacy `Category.monthly_budget` column remains for compatibility; period budgets are authoritative in `MonthlyBudget`.