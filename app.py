import os
import secrets
import csv
import hashlib
import io
import re
from collections import defaultdict
from datetime import date as calendar_date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path

from cachelib.file import FileSystemCache
from email_validator import EmailNotValidError, validate_email
from flask import Flask, abort, current_app, flash, jsonify, redirect, render_template, request, session, url_for
from flask_login import current_user, login_required, login_user, logout_user
from flask_migrate import Migrate
from flask_wtf.csrf import CSRFError
from sqlalchemy import func
from sqlalchemy.engine import URL
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from werkzeug.security import check_password_hash, generate_password_hash
from werkzeug.exceptions import RequestEntityTooLarge

from extensions import csrf, db, login_manager, server_session
from models import AnomalyAnalysis, Category, MonthlyBudget, Transaction, TransactionImport, User
from services import (
    analyze_user_transactions,
    invalidate_user_anomalies,
    monthly_budget_report,
    serialize_analysis_for_transaction,
)

app = Flask(__name__)
try:
    Path(app.instance_path).mkdir(parents=True, exist_ok=True)
except OSError as exc:
    raise RuntimeError(f"Unable to create Flask instance directory: {app.instance_path}") from exc

session_directory = Path(
    os.environ.get("SPENDWISE_SESSION_DIR", Path(app.instance_path) / "sessions")
)
try:
    session_directory.mkdir(parents=True, exist_ok=True)
except OSError as exc:
    raise RuntimeError(f"Unable to create session directory: {session_directory}") from exc

database_path = Path(os.environ.get("SPENDWISE_DATABASE_PATH", Path(app.instance_path) / "spendwise.db"))
app.config["SQLALCHEMY_DATABASE_URI"] = URL.create("sqlite", database=str(database_path))
app.config.update(
    SECRET_KEY=os.environ.get("SPENDWISE_SECRET_KEY") or secrets.token_urlsafe(48),
    SQLALCHEMY_TRACK_MODIFICATIONS=False,
    SESSION_TYPE="cachelib",
    SESSION_CACHELIB=FileSystemCache(str(session_directory), mode=0o600),
    SESSION_PERMANENT=False,
    SESSION_REFRESH_EACH_REQUEST=False,
    PERMANENT_SESSION_LIFETIME=timedelta(minutes=30),
    SESSION_COOKIE_NAME="spendwise_session",
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=os.environ.get("SPENDWISE_COOKIE_SECURE", "").casefold()
    in {"1", "true", "yes"},
    WTF_CSRF_TIME_LIMIT=3600,
    MAX_CONTENT_LENGTH=1_100_000,
)
_DUMMY_PASSWORD_HASH = generate_password_hash(secrets.token_urlsafe(32), method="scrypt")
MAX_CSV_BYTES = 1_000_000
MAX_IMPORT_ROWS = 100

db.init_app(app)
server_session.init_app(app)
login_manager.init_app(app)
login_manager.login_view = "login"
login_manager.session_protection = "strong"
csrf.init_app(app)
migrate = Migrate(app, db)

PAGES = {
    "dashboard": "dashboard.html",
    "expenses": "expenses.html",
    "transactions": "transactions.html",
    "categories": "categories.html",
}


@login_manager.user_loader
def load_user(user_id):
    try:
        parsed_user_id = int(user_id)
    except (TypeError, ValueError):
        return None
    return db.session.get(User, parsed_user_id)


def normalized_email(value):
    if not isinstance(value, str):
        return None
    candidate = value.strip()
    if not candidate or len(candidate) > 254:
        return None
    try:
        return validate_email(candidate, check_deliverability=False).normalized.casefold()
    except EmailNotValidError:
        return None


def api_error(code, message, status, fields=None):
    error = {"code": code, "message": message}
    if fields:
        error["fields"] = fields
    return jsonify({"error": error}), status


def transaction_values(payload, user_id, existing=None, partial=False):
    values = {}
    errors = {}

    if "merchant" in payload:
        merchant = payload["merchant"]
        if not isinstance(merchant, str) or not merchant.strip() or len(merchant.strip()) > 80:
            errors["merchant"] = "Enter a merchant name of 1 to 80 characters."
        else:
            values["merchant"] = merchant.strip()
    elif existing is None or not partial:
        errors["merchant"] = "Merchant is required."

    if "amount" in payload:
        raw_amount = payload["amount"]
        try:
            amount = Decimal(str(raw_amount).strip()) if not isinstance(raw_amount, bool) else Decimal("NaN")
            if not amount.is_finite() or amount <= 0 or amount > Decimal("9999999999.99"):
                raise InvalidOperation
            if amount.quantize(Decimal("0.01")) != amount:
                raise InvalidOperation
            values["amount"] = amount
        except (InvalidOperation, ValueError, TypeError):
            errors["amount"] = "Enter a positive amount with no more than two decimal places."
    elif existing is None or not partial:
        errors["amount"] = "Amount is required."

    if "date" in payload:
        raw_date = payload["date"]
        try:
            transaction_date = calendar_date.fromisoformat(raw_date) if isinstance(raw_date, str) else None
            if transaction_date is None or transaction_date.isoformat() != raw_date:
                raise ValueError
            values["transaction_date"] = transaction_date
        except ValueError:
            errors["date"] = "Enter a valid date in YYYY-MM-DD format."
    elif existing is None or not partial:
        errors["date"] = "Date is required."

    if "description" in payload or existing is None or not partial:
        description = payload.get("description")
        if description is None:
            values["description"] = None
        elif not isinstance(description, str) or len(description.strip()) > 500:
            errors["description"] = "Description must be 500 characters or fewer."
        else:
            values["description"] = description.strip() or None

    if "category_id" in payload or existing is None or not partial:
        raw_category_id = payload.get("category_id")
        if raw_category_id is None or raw_category_id == "":
            category_id = None
        elif isinstance(raw_category_id, int) and not isinstance(raw_category_id, bool):
            category_id = raw_category_id
        elif isinstance(raw_category_id, str) and raw_category_id.isdecimal():
            category_id = int(raw_category_id)
        else:
            category_id = None
            errors["category_id"] = "Select a valid category."

        if category_id is not None:
            category_exists = db.session.scalar(
                db.select(Category.id).where(
                    Category.id == category_id,
                    Category.user_id == user_id,
                    Category.is_archived.is_(False),
                )
            )
            if category_exists is None:
                errors["category_id"] = "Select a category from your account."
            else:
                values["category_id"] = category_id
        elif "category_id" not in errors:
            values["category_id"] = None

    return values, errors


def serialize_transaction(transaction):
    category = transaction.category
    return {
        "id": transaction.id,
        "merchant": transaction.merchant,
        "amount": format(transaction.amount, ".2f"),
        "date": transaction.transaction_date.isoformat(),
        "description": transaction.description,
        "category_id": transaction.category_id,
        "category": (
            {"id": category.id, "name": category.name, "color": category.color}
            if category is not None
            else None
        ),
        "created_at": transaction.created_at.isoformat() if transaction.created_at else None,
    }


@login_manager.unauthorized_handler
def unauthorized():
    if request.path.startswith("/api/"):
        return api_error("unauthorized", "Authentication is required.", 401)
    return redirect(url_for("login", next=request.url))


@app.errorhandler(CSRFError)
def handle_csrf_error(error):
    if request.path.startswith("/api/"):
        return api_error("csrf_failed", "The request token is missing or invalid.", 400)
    return error.description, 400


@app.errorhandler(404)
def handle_not_found(error):
    if request.path.startswith("/api/"):
        return api_error("not_found", "The requested resource was not found.", 404)
    return error


@app.errorhandler(405)
def handle_method_not_allowed(error):
    if request.path.startswith("/api/"):
        return api_error("method_not_allowed", "This method is not supported for the resource.", 405)
    return error


@app.errorhandler(RequestEntityTooLarge)
def handle_oversized_request(error):
    if request.path.startswith("/api/"):
        return api_error("file_too_large", "The upload exceeds the 1 MB file limit.", 413)
    return "The upload is too large.", 413


def parse_money_value(value, allow_zero=False):
    try:
        amount = Decimal(str(value).strip()) if not isinstance(value, bool) else Decimal("NaN")
        if not amount.is_finite() or amount < 0 or (amount == 0 and not allow_zero):
            raise InvalidOperation
        if amount > Decimal("9999999999.99") or amount.quantize(Decimal("0.01")) != amount:
            raise InvalidOperation
        return amount, None
    except (InvalidOperation, ValueError, TypeError, AttributeError):
        return None, "Enter an amount with no more than two decimal places."


def parse_period(year_value, month_value):
    def integer(value):
        if isinstance(value, bool):
            return None
        if isinstance(value, int):
            return value
        if isinstance(value, str) and re.fullmatch(r"\d+", value.strip()):
            return int(value.strip())
        return None

    year = integer(year_value)
    month = integer(month_value)
    if year is None or month is None:
        return None
    if not 1900 <= year <= 9998 or not 1 <= month <= 12:
        return None
    return year, month


def category_data(category):
    return {
        "id": category.id,
        "name": category.name,
        "color": category.color,
        "warning_threshold": category.warning_threshold,
        "is_archived": category.is_archived,
    }


def validate_category_fields(payload, existing=None):
    values = {}
    errors = {}

    if "name" in payload:
        name = payload["name"]
        if not isinstance(name, str) or not name.strip() or len(name.strip()) > 100:
            errors["name"] = "Category names must contain 1 to 100 characters."
        else:
            name = name.strip()
            name_key = name.casefold()
            duplicate = db.session.scalar(
                db.select(Category.id).where(
                    Category.user_id == current_user.id,
                    Category.name_key == name_key,
                    Category.id != (existing.id if existing else -1),
                )
            )
            if duplicate is not None:
                errors["name"] = "A category with this name already exists."
            else:
                values["name"] = name
                values["name_key"] = name_key
    elif existing is None:
        errors["name"] = "Category name is required."

    if "color" in payload:
        color = payload["color"]
        if color in (None, ""):
            values["color"] = None
        elif not isinstance(color, str) or not re.fullmatch(r"#[0-9a-fA-F]{6}", color):
            errors["color"] = "Color must be a six-digit hexadecimal value such as #3478c8."
        else:
            values["color"] = color.lower()

    if "warning_threshold" in payload:
        threshold = payload["warning_threshold"]
        if isinstance(threshold, bool):
            errors["warning_threshold"] = "Warning threshold must be a percentage from 0 to 100."
        else:
            try:
                threshold = int(threshold)
                if not 0 <= threshold <= 100:
                    raise ValueError
                values["warning_threshold"] = threshold
            except (TypeError, ValueError):
                errors["warning_threshold"] = "Warning threshold must be a percentage from 0 to 100."

    if "is_archived" in payload:
        if not isinstance(payload["is_archived"], bool):
            errors["is_archived"] = "Archived state must be true or false."
        else:
            values["is_archived"] = payload["is_archived"]

    budget_value = None
    if "monthly_budget" in payload:
        budget_value, message = parse_money_value(payload["monthly_budget"], allow_zero=True)
        if message:
            errors["monthly_budget"] = message

    return values, budget_value, errors


def parse_month_query(value):
    if value is None:
        today = calendar_date.today()
        return today.year, today.month
    if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}", value):
        return None
    return parse_period(value[:4], value[5:])


def shift_month(year, month, offset):
    index = year * 12 + month - 1 + offset
    return index // 12, index % 12 + 1


def parse_transaction_csv(content, user_id):
    try:
        text = content.decode("utf-8-sig", errors="strict")
    except UnicodeDecodeError:
        return None, "Use a UTF-8 encoded CSV file."

    reader = csv.reader(io.StringIO(text, newline=""), strict=True)
    try:
        headers = next(reader, None)
        if not headers or not any(value.strip() for value in headers):
            return None, "The CSV file is empty or has no header row."

        aliases = {
            "date": {"date", "transactiondate"},
            "description": {"description", "note", "memo"},
            "amount": {"amount", "total"},
            "category": {"category", "categoryname"},
            "merchant": {"merchant", "payee", "name"},
        }
        columns = {}
        for index, header in enumerate(headers):
            normalized = re.sub(r"[^a-z0-9]", "", header.strip().lstrip("\ufeff").casefold())
            matches = [name for name, names in aliases.items() if normalized in names]
            if matches:
                field = matches[0]
                if field in columns:
                    return None, f"The CSV has more than one {field} column."
                columns[field] = index

        required = {"date", "description", "amount", "category"}
        missing = sorted(required - columns.keys())
        if missing:
            return None, f"Missing required CSV columns: {', '.join(missing)}."

        categories = db.session.scalars(
            db.select(Category).where(
                Category.user_id == user_id,
                Category.is_archived.is_(False),
            )
        ).all()
        categories_by_name = {}
        for category in categories:
            categories_by_name.setdefault(category.name.strip().casefold(), []).append(category)

        preview_rows = []
        valid_rows = []
        row_count = 0
        for row_number, row in enumerate(reader, start=2):
            if not row or not any(value.strip() for value in row):
                continue
            row_count += 1
            if row_count > MAX_IMPORT_ROWS:
                return None, f"A CSV import can contain at most {MAX_IMPORT_ROWS} rows."

            errors = []
            if len(row) != len(headers):
                errors.append("The row has a different number of columns than the header.")
            padded = row[:len(headers)] + [""] * max(0, len(headers) - len(row))
            raw_description = padded[columns["description"]].strip()
            merchant = (
                padded[columns["merchant"]].strip()
                if "merchant" in columns
                else raw_description
            )
            category_name = padded[columns["category"]].strip()
            matching_categories = categories_by_name.get(category_name.casefold(), [])
            category_id = matching_categories[0].id if len(matching_categories) == 1 else None
            if len(matching_categories) != 1:
                errors.append(
                    f"Category '{category_name or '(blank)'}' is not an active category on your account."
                )

            payload = {
                "merchant": merchant,
                "date": padded[columns["date"]].strip(),
                "amount": padded[columns["amount"]].strip(),
                "description": raw_description or None,
                "category_id": category_id,
            }
            values, field_errors = transaction_values(payload, user_id)
            if field_errors:
                errors.extend(field_errors.values())

            transaction_data = {
                "merchant": values.get("merchant", merchant),
                "date": values.get("transaction_date", "").isoformat()
                if values.get("transaction_date")
                else payload["date"],
                "amount": format(values["amount"], ".2f") if "amount" in values else payload["amount"],
                "description": values.get("description", raw_description or None),
                "category_id": values.get("category_id"),
                "category": category_name,
            }
            valid = not errors
            preview_rows.append(
                {"row": row_number, "valid": valid, "transaction": transaction_data, "errors": errors}
            )
            if valid:
                valid_rows.append(
                    {
                        "merchant": values["merchant"],
                        "amount": format(values["amount"], ".2f"),
                        "date": values["transaction_date"].isoformat(),
                        "description": values["description"],
                        "category_id": values["category_id"],
                    }
                )

        if row_count == 0:
            return None, "The CSV contains no transaction rows."
        return {"rows": preview_rows, "valid_rows": valid_rows}, None
    except csv.Error:
        return None, "The CSV file is malformed. Check its quoting and row structure."


@app.post("/api/transactions/import/preview")
@login_required
def preview_transaction_import():
    upload = request.files.get("file")
    if upload is None or not upload.filename:
        return api_error("missing_file", "Choose a CSV file to preview.", 400)
    if not upload.filename.casefold().endswith(".csv"):
        return api_error("invalid_file_type", "Only .csv files are accepted.", 400)

    content = upload.stream.read(MAX_CSV_BYTES + 1)
    if len(content) > MAX_CSV_BYTES:
        return api_error("file_too_large", "The upload exceeds the 1 MB file limit.", 413)
    try:
        parsed, error = parse_transaction_csv(content, current_user.id)
    except SQLAlchemyError:
        db.session.rollback()
        return api_error("database_error", "The CSV preview could not be created.", 500)
    if error:
        db.session.rollback()
        return api_error("invalid_csv", error, 400)

    file_digest = hashlib.sha256(content).hexdigest()
    try:
        imported_file = db.session.scalar(
            db.select(TransactionImport.id).where(
                TransactionImport.user_id == current_user.id,
                TransactionImport.file_digest == file_digest,
            )
        )
    except SQLAlchemyError:
        db.session.rollback()
        return api_error("database_error", "The CSV preview could not be created.", 500)
    if imported_file is not None:
        return api_error(
            "duplicate_file",
            "This exact CSV file has already been imported for your account.",
            409,
        )

    preview_id = secrets.token_urlsafe(32)
    previews = session.get("csv_import_previews", {})
    if len(previews) >= 5:
        previews.pop(next(iter(previews)))
    previews[preview_id] = {"rows": parsed["valid_rows"], "file_digest": file_digest}
    session["csv_import_previews"] = previews
    return jsonify(
        {
            "data": {
                "preview_id": preview_id,
                "rows": parsed["rows"],
                "valid_count": len(parsed["valid_rows"]),
                "invalid_count": len(parsed["rows"]) - len(parsed["valid_rows"]),
                "max_rows": MAX_IMPORT_ROWS,
            }
        }
    )


@app.post("/api/transactions/import/confirm")
@login_required
def confirm_transaction_import():
    payload = request.get_json(silent=True)
    preview_id = payload.get("preview_id") if isinstance(payload, dict) else None
    if not isinstance(preview_id, str) or not 1 <= len(preview_id) <= 64:
        return api_error("invalid_preview", "The import preview is invalid or expired.", 400)

    previews = session.get("csv_import_previews", {})
    preview = previews.get(preview_id)
    if preview is None:
        try:
            already_imported = db.session.scalar(
                db.select(TransactionImport.id).where(
                    TransactionImport.user_id == current_user.id,
                    TransactionImport.preview_id == preview_id,
                )
            )
        except SQLAlchemyError:
            db.session.rollback()
            return api_error("database_error", "The import could not be confirmed.", 500)
        if already_imported:
            return api_error("already_imported", "This preview has already been imported.", 409)
        return api_error("invalid_preview", "The import preview is invalid or expired.", 400)
    valid_rows = preview["rows"]
    if not valid_rows:
        return api_error("no_valid_rows", "There are no valid rows to import.", 400)

    try:
        receipt = TransactionImport(
            user_id=current_user.id,
            preview_id=preview_id,
            file_digest=preview["file_digest"],
        )
        db.session.add(receipt)
        imported = 0
        for row in valid_rows:
            values, errors = transaction_values(row, current_user.id)
            if errors:
                db.session.rollback()
                return api_error(
                    "preview_expired",
                    "A category or transaction value changed after preview. Preview the file again.",
                    409,
                )
            db.session.add(Transaction(user_id=current_user.id, **values))
            imported += 1
        invalidate_user_anomalies(current_user.id)
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        return api_error("already_imported", "This preview has already been imported.", 409)
    except SQLAlchemyError:
        db.session.rollback()
        return api_error("database_error", "The import could not be saved.", 500)

    previews.pop(preview_id, None)
    session["csv_import_previews"] = previews
    return jsonify({"data": {"imported_count": imported}}), 201


@app.delete("/api/transactions/import/preview/<preview_id>")
@login_required
def cancel_transaction_import(preview_id):
    previews = session.get("csv_import_previews", {})
    existed = previews.pop(preview_id, None) is not None
    session["csv_import_previews"] = previews
    return jsonify({"data": {"cancelled": existed}})


@app.get("/api/categories")
@login_required
def api_categories():
    status = request.args.get("status", "active")
    if status not in {"active", "archived", "all"}:
        return api_error("invalid_filter", "Status must be active, archived, or all.", 400)
    try:
        query = db.select(Category).where(Category.user_id == current_user.id)
        if status == "active":
            query = query.where(Category.is_archived.is_(False))
        elif status == "archived":
            query = query.where(Category.is_archived.is_(True))
        categories = db.session.scalars(query.order_by(Category.name_key, Category.id)).all()
        return jsonify({"data": [category_data(category) for category in categories]})
    except SQLAlchemyError:
        db.session.rollback()
        return api_error("database_error", "Categories could not be loaded.", 500)


@app.post("/api/categories")
@login_required
def create_category():
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return api_error("invalid_request", "Send category data as a JSON object.", 400)
    values, budget_amount, errors = validate_category_fields(payload)
    if errors:
        if "already exists" in errors.get("name", ""):
            return api_error("duplicate_category", errors["name"], 409)
        return api_error("validation_error", "Check the category fields.", 400, errors)

    try:
        category = Category(user_id=current_user.id, **values)
        db.session.add(category)
        db.session.flush()
        if budget_amount is not None:
            today = calendar_date.today()
            db.session.add(
                MonthlyBudget(
                    user_id=current_user.id,
                    category_id=category.id,
                    year=today.year,
                    month=today.month,
                    budget_amount=budget_amount,
                )
            )
        db.session.commit()
        return jsonify({"data": category_data(category)}), 201
    except IntegrityError:
        db.session.rollback()
        return api_error("duplicate_category", "A category with this name already exists.", 409)
    except SQLAlchemyError:
        db.session.rollback()
        return api_error("database_error", "The category could not be saved.", 500)


@app.route("/api/categories/<int:category_id>", methods=["GET", "PATCH", "PUT"])
@login_required
def category_detail(category_id):
    try:
        category = db.session.scalar(
            db.select(Category).where(
                Category.id == category_id,
                Category.user_id == current_user.id,
            )
        )
        if category is None:
            return api_error("not_found", "Category not found.", 404)
        if request.method == "GET":
            return jsonify({"data": category_data(category)})

        payload = request.get_json(silent=True)
        if not isinstance(payload, dict):
            return api_error("invalid_request", "Send category data as a JSON object.", 400)
        values, budget_amount, errors = validate_category_fields(payload, existing=category)
        if errors:
            if "already exists" in errors.get("name", ""):
                return api_error("duplicate_category", errors["name"], 409)
            return api_error("validation_error", "Check the category fields.", 400, errors)
        for field, value in values.items():
            setattr(category, field, value)
        if budget_amount is not None:
            today = calendar_date.today()
            budget = db.session.scalar(
                db.select(MonthlyBudget).where(
                    MonthlyBudget.user_id == current_user.id,
                    MonthlyBudget.category_id == category.id,
                    MonthlyBudget.year == today.year,
                    MonthlyBudget.month == today.month,
                )
            )
            if budget is None:
                db.session.add(
                    MonthlyBudget(
                        user_id=current_user.id,
                        category_id=category.id,
                        year=today.year,
                        month=today.month,
                        budget_amount=budget_amount,
                    )
                )
            else:
                budget.budget_amount = budget_amount
        db.session.commit()
        return jsonify({"data": category_data(category)})
    except IntegrityError:
        db.session.rollback()
        return api_error("duplicate_category", "A category with this name already exists.", 409)
    except SQLAlchemyError:
        db.session.rollback()
        return api_error("database_error", "The category could not be updated.", 500)


@app.route("/api/budgets", methods=["GET", "POST"])
@login_required
def monthly_budgets():
    if request.method == "GET":
        period = parse_month_query(request.args.get("month"))
        if period is None:
            return api_error("invalid_month", "Month must use YYYY-MM format.", 400)
        try:
            return jsonify({"data": monthly_budget_report(current_user.id, *period)})
        except SQLAlchemyError:
            db.session.rollback()
            return api_error("database_error", "Budgets could not be loaded.", 500)

    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return api_error("invalid_request", "Send budget data as a JSON object.", 400)
    category_id = payload.get("category_id")
    if isinstance(category_id, bool):
        category_id = None
    elif isinstance(category_id, int):
        pass
    elif isinstance(category_id, str) and re.fullmatch(r"\d+", category_id.strip()):
        category_id = int(category_id.strip())
    else:
        category_id = None
    period = parse_period(payload.get("year"), payload.get("month"))
    amount, amount_error = parse_money_value(payload.get("budget_amount"), allow_zero=True)
    errors = {}
    if category_id is None or category_id <= 0:
        errors["category_id"] = "Select a valid category."
    if period is None:
        errors["period"] = "Enter a valid year and month."
    if amount_error:
        errors["budget_amount"] = amount_error
    if errors:
        return api_error("validation_error", "Check the budget fields.", 400, errors)

    try:
        category = db.session.scalar(
            db.select(Category).where(
                Category.id == category_id,
                Category.user_id == current_user.id,
                Category.is_archived.is_(False),
            )
        )
        if category is None:
            return api_error("invalid_category", "Select an active category from your account.", 400)
        year, month = period
        budget = MonthlyBudget(
            user_id=current_user.id,
            category_id=category.id,
            year=year,
            month=month,
            budget_amount=amount,
        )
        db.session.add(budget)
        db.session.commit()
        report = monthly_budget_report(current_user.id, year, month)
        result = next(item for item in report if item["category_id"] == category.id)
        return jsonify({"data": result}), 201
    except IntegrityError:
        db.session.rollback()
        return api_error("duplicate_budget", "A budget already exists for this category and month.", 409)
    except SQLAlchemyError:
        db.session.rollback()
        return api_error("database_error", "The budget could not be saved.", 500)


@app.route("/api/budgets/<int:budget_id>", methods=["GET", "PUT", "PATCH"])
@login_required
def monthly_budget_detail(budget_id):
    try:
        budget = db.session.scalar(
            db.select(MonthlyBudget).where(
                MonthlyBudget.id == budget_id,
                MonthlyBudget.user_id == current_user.id,
            )
        )
        if budget is None:
            return api_error("not_found", "Budget not found.", 404)
        if request.method == "GET":
            report = monthly_budget_report(current_user.id, budget.year, budget.month)
            result = next(item for item in report if item["category_id"] == budget.category_id)
            return jsonify({"data": result})

        payload = request.get_json(silent=True)
        if not isinstance(payload, dict) or "budget_amount" not in payload:
            return api_error("invalid_request", "Provide a budget_amount in the JSON object.", 400)
        amount, error = parse_money_value(payload["budget_amount"], allow_zero=True)
        if error:
            return api_error("validation_error", "Check the budget amount.", 400, {"budget_amount": error})
        budget.budget_amount = amount
        db.session.commit()
        report = monthly_budget_report(current_user.id, budget.year, budget.month)
        result = next(item for item in report if item["category_id"] == budget.category_id)
        return jsonify({"data": result})
    except SQLAlchemyError:
        db.session.rollback()
        return api_error("database_error", "The budget could not be loaded or updated.", 500)


@app.get("/api/dashboard")
@login_required
def dashboard_data():
    period = parse_month_query(request.args.get("month"))
    if period is None:
        return api_error("invalid_month", "Month must use YYYY-MM format.", 400)
    year, month = period
    start = calendar_date(year, month, 1)
    next_year, next_month = shift_month(year, month, 1)
    end = calendar_date(next_year, next_month, 1)
    previous_year, previous_month = shift_month(year, month, -1)
    previous_start = calendar_date(previous_year, previous_month, 1)
    range_year, range_month = shift_month(year, month, -5)
    range_start = calendar_date(range_year, range_month, 1)

    try:
        transactions = db.session.scalars(
            db.select(Transaction)
            .where(
                Transaction.user_id == current_user.id,
                Transaction.transaction_date >= range_start,
                Transaction.transaction_date < end,
            )
            .order_by(Transaction.transaction_date, Transaction.id)
        ).all()

        month_totals = defaultdict(Decimal)
        category_totals = defaultdict(Decimal)
        daily_totals = defaultdict(Decimal)
        current_entries = []
        previous_total = Decimal("0.00")
        for transaction in transactions:
            amount = Decimal(transaction.amount)
            transaction_month = (transaction.transaction_date.year, transaction.transaction_date.month)
            month_totals[transaction_month] += amount
            if transaction_month == (year, month):
                current_entries.append(transaction)
                daily_totals[transaction.transaction_date.day] += amount
                category_totals[transaction.category_id] += amount
            elif transaction_month == (previous_year, previous_month):
                previous_total += amount

        current_total = month_totals[(year, month)]
        budget_rows = monthly_budget_report(current_user.id, year, month)
        active_budget_rows = [row for row in budget_rows if not row["is_archived"]]
        warning_count = sum(row["status"] in {"warning", "exceeded"} for row in active_budget_rows)
        budget_remaining = sum(
            (Decimal(row["remaining"]) for row in active_budget_rows),
            Decimal("0.00"),
        )

        categories = db.session.scalars(
            db.select(Category).where(Category.user_id == current_user.id)
        ).all()
        category_by_id = {category.id: category for category in categories}
        category_spending = [
            {
                "category_id": category_id,
                "name": category_by_id[category_id].name if category_id in category_by_id else "Uncategorized",
                "color": category_by_id[category_id].color if category_id in category_by_id else "#768493",
                "amount": format(amount, ".2f"),
            }
            for category_id, amount in category_totals.items()
            if amount > 0
        ]
        category_spending.sort(key=lambda item: Decimal(item["amount"]), reverse=True)

        trend = []
        for offset in range(-5, 1):
            month_year, month_number = shift_month(year, month, offset)
            trend.append(
                {
                    "month": f"{month_year:04d}-{month_number:02d}",
                    "amount": format(month_totals[(month_year, month_number)], ".2f"),
                }
            )

        analysis_count = db.session.scalar(
            db.select(func.count(AnomalyAnalysis.id))
            .join(Transaction, Transaction.id == AnomalyAnalysis.transaction_id)
            .where(
                AnomalyAnalysis.user_id == current_user.id,
                db.or_(
                    AnomalyAnalysis.is_anomaly.is_(True),
                    AnomalyAnalysis.status == "insufficient_history",
                ),
                Transaction.transaction_date >= start,
                Transaction.transaction_date < end,
            )
        )
        anomaly_rows = db.session.execute(
            db.select(Transaction, AnomalyAnalysis)
            .join(
                AnomalyAnalysis,
                (AnomalyAnalysis.transaction_id == Transaction.id)
                & (AnomalyAnalysis.user_id == Transaction.user_id),
            )
            .where(
                Transaction.user_id == current_user.id,
                AnomalyAnalysis.is_anomaly.is_(True),
                Transaction.transaction_date >= start,
                Transaction.transaction_date < end,
            )
            .order_by(Transaction.transaction_date.desc(), Transaction.id.desc())
            .limit(3)
        ).all()
        earliest_transaction = db.session.scalar(
            db.select(func.min(Transaction.transaction_date)).where(Transaction.user_id == current_user.id)
        )
        earliest_budget = db.session.execute(
            db.select(MonthlyBudget.year, MonthlyBudget.month)
            .where(MonthlyBudget.user_id == current_user.id)
            .order_by(MonthlyBudget.year, MonthlyBudget.month)
            .limit(1)
        ).first()
        earliest = (earliest_transaction.year, earliest_transaction.month) if earliest_transaction else (year, month)
        if earliest_budget:
            earliest = min(earliest, (earliest_budget.year, earliest_budget.month))
        if not earliest_transaction and not earliest_budget:
            earliest = shift_month(year, month, -11)
        available_months = []
        cursor = earliest
        while cursor <= (year, month):
            available_months.append(f"{cursor[0]:04d}-{cursor[1]:02d}")
            cursor = shift_month(*cursor, 1)
        amount_change = current_total - previous_total
        change_percent = (
            (amount_change * Decimal(100) / previous_total).quantize(Decimal("0.1"))
            if previous_total > 0
            else None
        )
        return jsonify(
            {
                "data": {
                    "month": f"{year:04d}-{month:02d}",
                    "summary": {
                        "total_spent": format(current_total, ".2f"),
                        "transaction_count": len(current_entries),
                        "previous_month_total": format(previous_total, ".2f"),
                        "change_amount": format(amount_change, ".2f"),
                        "change_percent": format(change_percent, ".1f") if change_percent is not None else None,
                        "budget_warning_count": warning_count,
                        "budget_remaining": format(budget_remaining, ".2f"),
                        "anomaly_count": analysis_count or 0,
                    },
                    "daily_spending": [
                        {"day": day, "amount": format(daily_totals[day], ".2f")}
                        for day in range(1, (end - start).days + 1)
                    ],
                    "monthly_spending": trend,
                    "category_spending": category_spending,
                    "budget_vs_actual": [
                        {
                            "category_id": item["category_id"],
                            "category_name": item["category_name"],
                            "category_color": item["category_color"],
                            "spent": item["spent"],
                            "budget_amount": item["budget_amount"],
                            "warning_threshold": item["warning_threshold"],
                            "status": item["status"],
                        }
                        for item in active_budget_rows
                    ],
                    "recent_transactions": [
                        serialize_transaction(transaction)
                        for transaction in sorted(
                            current_entries,
                            key=lambda item: (item.transaction_date, item.id),
                            reverse=True,
                        )[:6]
                    ],
                    "anomalies": [
                        serialize_analysis_for_transaction(transaction, analysis)
                        for transaction, analysis in anomaly_rows
                    ],
                    "available_months": available_months,
                }
            }
        )
    except SQLAlchemyError:
        db.session.rollback()
        return api_error("database_error", "Dashboard data could not be loaded.", 500)


@app.get("/api/anomalies")
@login_required
def list_anomalies():
    period = parse_month_query(request.args.get("month"))
    if period is None:
        return api_error("invalid_month", "Month must use YYYY-MM format.", 400)
    from services import month_bounds

    start, end = month_bounds(*period)
    try:
        rows = db.session.execute(
            db.select(Transaction, AnomalyAnalysis)
            .join(
                AnomalyAnalysis,
                (AnomalyAnalysis.transaction_id == Transaction.id)
                & (AnomalyAnalysis.user_id == Transaction.user_id),
            )
            .where(
                Transaction.user_id == current_user.id,
                Transaction.transaction_date >= start,
                Transaction.transaction_date < end,
            )
            .order_by(Transaction.transaction_date.desc(), Transaction.id.desc())
        ).all()
        return jsonify({
            "data": [serialize_analysis_for_transaction(transaction, analysis) for transaction, analysis in rows]
        })
    except SQLAlchemyError:
        db.session.rollback()
        return api_error("database_error", "Anomaly results could not be loaded.", 500)


@app.post("/api/anomalies/analyze")
@login_required
def run_anomaly_analysis():
    period = parse_month_query(request.args.get("month"))
    if period is None:
        return api_error("invalid_month", "Month must use YYYY-MM format.", 400)
    from services import month_bounds

    start, end = month_bounds(*period)
    try:
        results = analyze_user_transactions(current_user.id)
        db.session.commit()
        return jsonify({
            "data": [
                serialize_analysis_for_transaction(transaction, analysis)
                for transaction, analysis in results
                if start <= transaction.transaction_date < end
            ]
        })
    except SQLAlchemyError:
        db.session.rollback()
        return api_error("database_error", "Anomaly analysis could not be completed.", 500)


@app.post("/api/anomalies/<int:analysis_id>/acknowledge")
@login_required
def acknowledge_anomaly(analysis_id):
    try:
        analysis = db.session.scalar(
            db.select(AnomalyAnalysis).where(
                AnomalyAnalysis.id == analysis_id,
                AnomalyAnalysis.user_id == current_user.id,
            )
        )
        if analysis is None:
            return api_error("not_found", "Anomaly result not found.", 404)
        analysis.acknowledged_at = datetime.now(timezone.utc)
        db.session.commit()
        return jsonify({"data": {"id": analysis.id, "acknowledged": True}})
    except SQLAlchemyError:
        db.session.rollback()
        return api_error("database_error", "The anomaly result could not be acknowledged.", 500)


@app.route("/api/transactions", methods=["GET", "POST"])
@login_required
def api_transactions():
    if request.method == "GET":
        try:
            transactions = db.session.scalars(
                db.select(Transaction)
                .where(Transaction.user_id == current_user.id)
                .order_by(Transaction.transaction_date.desc(), Transaction.id.desc())
            ).all()
            return jsonify({"data": [serialize_transaction(item) for item in transactions]})
        except SQLAlchemyError:
            db.session.rollback()
            return api_error("database_error", "Transactions could not be loaded.", 500)

    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return api_error("invalid_request", "Send transaction data as a JSON object.", 400)
    try:
        values, errors = transaction_values(payload, current_user.id)
        if errors:
            return api_error("validation_error", "Check the transaction fields.", 400, errors)
        transaction = Transaction(user_id=current_user.id, **values)
        db.session.add(transaction)
        invalidate_user_anomalies(current_user.id)
        db.session.commit()
        return jsonify({"data": serialize_transaction(transaction)}), 201
    except IntegrityError:
        db.session.rollback()
        return api_error("invalid_reference", "The selected category is not available.", 400)
    except SQLAlchemyError:
        db.session.rollback()
        return api_error("database_error", "The transaction could not be saved.", 500)


@app.route("/api/transactions/<int:transaction_id>", methods=["GET", "PUT", "PATCH", "DELETE"])
@login_required
def api_transaction(transaction_id):
    try:
        transaction = db.session.scalar(
            db.select(Transaction).where(
                Transaction.id == transaction_id,
                Transaction.user_id == current_user.id,
            )
        )
        if transaction is None:
            return api_error("not_found", "Transaction not found.", 404)

        if request.method == "GET":
            return jsonify({"data": serialize_transaction(transaction)})

        if request.method == "DELETE":
            db.session.delete(transaction)
            invalidate_user_anomalies(current_user.id)
            db.session.commit()
            return jsonify({"data": {"id": transaction_id}})

        payload = request.get_json(silent=True)
        if not isinstance(payload, dict):
            return api_error("invalid_request", "Send transaction data as a JSON object.", 400)
        values, errors = transaction_values(
            payload,
            current_user.id,
            existing=transaction,
            partial=request.method == "PATCH",
        )
        if errors:
            return api_error("validation_error", "Check the transaction fields.", 400, errors)
        for field, value in values.items():
            setattr(transaction, field, value)
        invalidate_user_anomalies(current_user.id)
        db.session.commit()
        return jsonify({"data": serialize_transaction(transaction)})
    except IntegrityError:
        db.session.rollback()
        return api_error("invalid_reference", "The selected category is not available.", 400)
    except SQLAlchemyError:
        db.session.rollback()
        return api_error("database_error", "The transaction could not be saved.", 500)


@app.get("/")
def home():
    destination = "page" if current_user.is_authenticated else "login"
    if destination == "page":
        return redirect(url_for("page", page="dashboard"))
    return redirect(url_for(destination))


@app.get("/favicon.ico")
def favicon():
    return "", 204


@app.route("/login", methods=["GET", "POST"])
@app.route("/login.html", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("page", page="dashboard"))

    if request.method == "GET":
        return render_template("login.html", error="")

    email = normalized_email(request.form.get("email"))
    password = request.form.get("password", "")
    user = db.session.scalar(db.select(User).where(User.email == email)) if email else None
    password_hash = user.password_hash if user else _DUMMY_PASSWORD_HASH
    password_matches = check_password_hash(password_hash, password[:128])
    if user is None or len(password) > 128 or not password_matches:
        return render_template("login.html", error="Email or password is incorrect."), 401

    regenerate_session = getattr(current_app.session_interface, "regenerate", None)
    if regenerate_session:
        regenerate_session(session)
    session.clear()
    session.permanent = False
    login_user(user, remember=False, fresh=True)
    return redirect(url_for("page", page="dashboard"))


@app.route("/register", methods=["GET", "POST"])
@app.route("/register.html", methods=["GET", "POST"])
def register():
    if current_user.is_authenticated:
        return redirect(url_for("page", page="dashboard"))

    if request.method == "GET":
        return render_template("register.html", error="")

    email = normalized_email(request.form.get("email"))
    password = request.form.get("password", "")
    confirmation = request.form.get("confirm", "")

    if email is None:
        return render_template("register.html", error="Enter a valid email address."), 400
    if len(password) < 12 or len(password) > 128:
        return render_template("register.html", error="Use a password between 12 and 128 characters."), 400
    if password != confirmation:
        return render_template("register.html", error="Your passwords do not match."), 400

    user = User(email=email, password_hash=generate_password_hash(password, method="scrypt"))
    db.session.add(user)
    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()

    flash("If an account can be created with these details, you can sign in now.", "info")
    return redirect(url_for("login"))


@app.post("/logout")
@login_required
def logout():
    logout_user()
    session.clear()
    return redirect(url_for("login"))


@app.get("/<page>.html")
@login_required
def page(page):
    template = PAGES.get(page)
    if template is None:
        abort(404)
    return render_template(template)


if __name__ == "__main__":
    app.run()