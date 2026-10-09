# Static assets and Flask API plan

This folder is reserved for local images, icons, and other static assets. The current demo is intentionally self-contained and uses CSS markers rather than external image assets. Plotly.js is loaded from its official CDN on the dashboard; serve a local copy here if the deployed environment must work offline.

## Frontend demo behavior

`static/js/app.js` owns the browser-only demo model. Transactions and categories are stored under the versioned `spendwise-demo-v1` localStorage key so all pages share changes. This is convenience storage, not a database or security boundary. Passwords are never stored. Authentication screens only validate form fields and route into the demo.

## Suggested Flask API contracts

Replace the `DemoStore` methods in `app.js` with fetch-based requests when Flask endpoints exist. Keep rendering and form handling separate from the transport layer.

- `POST /api/auth/login` accepts `{ "email": "...", "password": "..." }`; returns an authenticated user/session or a validation error. Never persist a plaintext password in the browser.
- `POST /api/auth/register` accepts `{ "name": "...", "email": "...", "password": "..." }`; returns a created user or field errors.
- `GET /api/transactions?month=YYYY-MM` returns `{ "transactions": [{ "id": "...", "date": "YYYY-MM-DD", "merchant": "...", "amount": 12.34, "categoryId": "...", "description": "..." }] }`.
- `POST /api/transactions` accepts one transaction with date, merchant, positive amount, category ID, and optional description. `PUT /api/transactions/{id}` updates it; `DELETE /api/transactions/{id}` removes it.
- `POST /api/transactions/import` accepts a multipart CSV upload and returns `{ "created": [], "duplicates": [], "errors": [{ "row": 2, "message": "..." }] }`. The current demo parses locally before adding valid rows.
- `GET /api/categories` returns `{ "categories": [{ "id": "...", "name": "Food", "monthlyBudget": 400, "color": "#3478c8", "archived": false }] }`. `POST`, `PUT /api/categories/{id}`, and `DELETE` or an archive action manage category records without rewriting historical transaction category IDs.
- `GET /api/budgets?month=YYYY-MM` returns configured category limits and usage. `PUT /api/budgets/{categoryId}` accepts `{ "monthlyLimit": 400, "warningThreshold": 0.8 }`.
- `GET /api/dashboard?month=YYYY-MM` returns summary totals and trend/category/month series derived from the same transaction and budget records.
- `GET /api/anomalies?month=YYYY-MM` returns `{ "alerts": [{ "transactionId": "...", "score": 0.82, "label": "Unusual timing", "explanation": "..." }] }`. Scores and explanations should be presented as signals, not fraud findings.
- Optional Drive integration should use a server-side OAuth flow and return an importable file reference; a local file chooser is not Google Drive authorization.

The HTML under `templates/` uses relative static links for the standalone demo. In Flask, render those templates and use `url_for('static', filename='css/style.css')` and `url_for('static', filename='js/app.js')` (and route links) in place of relative paths.