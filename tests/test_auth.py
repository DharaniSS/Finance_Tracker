import html
import io
import os
import re
import secrets
import tempfile
import unittest
from datetime import date as calendar_date, timedelta
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.engine import URL
from werkzeug.security import check_password_hash


class AuthenticationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary_directory = tempfile.TemporaryDirectory(prefix="spendwise-auth-tests-")
        cls.temporary_path = Path(cls.temporary_directory.name)
        cls.previous_session_dir = os.environ.get("SPENDWISE_SESSION_DIR")
        cls.previous_database_path = os.environ.get("SPENDWISE_DATABASE_PATH")
        os.environ["SPENDWISE_SESSION_DIR"] = str(cls.temporary_path / "sessions")
        cls.database_path = cls.temporary_path / "auth-tests.sqlite"
        os.environ["SPENDWISE_DATABASE_PATH"] = str(cls.database_path)

        from app import app
        from extensions import db
        from models import AnomalyAnalysis, Category, MonthlyBudget, Transaction, TransactionImport, User

        cls.app = app
        cls.db = db
        cls.User = User
        cls.Category = Category
        cls.Transaction = Transaction
        cls.TransactionImport = TransactionImport
        cls.AnomalyAnalysis = AnomalyAnalysis
        cls.password = secrets.token_urlsafe(24)
        cls.models = (AnomalyAnalysis, TransactionImport, MonthlyBudget, Transaction, Category, User)
        cls.app.config.update(
            TESTING=True,
            SECRET_KEY=secrets.token_urlsafe(48),
            SESSION_COOKIE_SECURE=False,
            WTF_CSRF_ENABLED=True,
        )
        with cls.app.app_context():
            cls.db.create_all()

    @classmethod
    def tearDownClass(cls):
        with cls.app.app_context():
            cls.db.session.remove()
            cls.db.drop_all()
            cls.db.engine.dispose()
        cls.temporary_directory.cleanup()
        if cls.previous_session_dir is None:
            os.environ.pop("SPENDWISE_SESSION_DIR", None)
        else:
            os.environ["SPENDWISE_SESSION_DIR"] = cls.previous_session_dir
        if cls.previous_database_path is None:
            os.environ.pop("SPENDWISE_DATABASE_PATH", None)
        else:
            os.environ["SPENDWISE_DATABASE_PATH"] = cls.previous_database_path

    def setUp(self):
        with self.app.app_context():
            for model in self.models:
                self.db.session.execute(model.__table__.delete())
            self.db.session.commit()
        self.client = self.app.test_client()

    def _csrf_token(self, path, client=None):
        client = client or self.client
        response = client.get(path, follow_redirects=True)
        self.assertEqual(response.status_code, 200)
        match = re.search(rb'name="csrf_token" value="([^"]+)"', response.data)
        self.assertIsNotNone(match)
        return match.group(1).decode("ascii")

    def _register(self, email="person@example.com", password=None):
        password = password or self.password
        token = self._csrf_token("/register")
        return self.client.post(
            "/register",
            data={"csrf_token": token, "email": email, "password": password, "confirm": password},
            follow_redirects=True,
        )

    def _login(self, email="person@example.com", password=None):
        password = password or self.password
        token = self._csrf_token("/login")
        return self.client.post(
            "/login",
            data={"csrf_token": token, "email": email, "password": password},
        )

    def _authenticated_client(self, email):
        client = self.app.test_client()
        password = self.password
        register_token = self._csrf_token("/register", client)
        registration = client.post(
            "/register",
            data={
                "csrf_token": register_token,
                "email": email,
                "password": password,
                "confirm": password,
            },
        )
        self.assertEqual(registration.status_code, 302)
        login_token = self._csrf_token("/login", client)
        login = client.post(
            "/login",
            data={"csrf_token": login_token, "email": email, "password": password},
        )
        self.assertEqual(login.status_code, 302)
        return client

    def _api_request(self, client, method, path, data=None, csrf_token=True):
        headers = {"Accept": "application/json"}
        if method.upper() not in {"GET", "HEAD"} and csrf_token:
            headers["X-CSRFToken"] = self._csrf_token("/expenses.html", client)
        return client.open(path, method=method, json=data, headers=headers)

    def _preview_csv(self, client, content, filename="transactions.csv", csrf_token=True):
        headers = {"Accept": "application/json"}
        if csrf_token:
            headers["X-CSRFToken"] = self._csrf_token("/login", client)
        return client.post(
            "/api/transactions/import/preview",
            data={"file": (io.BytesIO(content), filename, "text/csv")},
            headers=headers,
        )

    def _confirm_csv(self, client, preview_id):
        return self._api_request(
            client,
            "POST",
            "/api/transactions/import/confirm",
            {"preview_id": preview_id},
        )

    def _transaction_count(self, email):
        with self.app.app_context():
            user_id = self.db.session.scalar(
                self.db.select(self.User.id).where(self.User.email == email)
            )
            return self.db.session.query(self.Transaction).filter_by(user_id=user_id).count()

    def _create_category(self, email, name="Food"):
        with self.app.app_context():
            user = self.db.session.scalar(self.db.select(self.User).where(self.User.email == email))
            category = self.Category(user_id=user.id, name=name, color="#3478c8")
            self.db.session.add(category)
            self.db.session.commit()
            return category.id

    @staticmethod
    def _form_error(response, form_id):
        pattern = rf'<p class="form-error" id="{form_id}"[^>]*>(.*?)</p>'.encode()
        match = re.search(pattern, response.data, re.DOTALL)
        return html.unescape(match.group(1).decode()).strip() if match else None

    def test_successful_registration_stores_only_password_hash(self):
        response = self._register(email=" Person@Example.com ")
        self.assertEqual(response.status_code, 200)
        with self.app.app_context():
            user = self.db.session.scalar(self.db.select(self.User))
            self.assertIsNotNone(user)
            self.assertEqual(user.email, "person@example.com")
            self.assertNotEqual(user.password_hash, self.password)
            self.assertTrue(check_password_hash(user.password_hash, self.password))

    def test_duplicate_registration_is_generic_and_does_not_duplicate_user(self):
        first_response = self._register()
        second_response = self._register()
        self.assertEqual(first_response.status_code, second_response.status_code)
        self.assertIn(b"If an account can be created with these details", first_response.data)
        self.assertIn(b"If an account can be created with these details", second_response.data)
        with self.app.app_context():
            count = self.db.session.query(self.User).count()
            self.assertEqual(count, 1)

    def test_registration_validates_email_password_and_confirmation(self):
        token = self._csrf_token("/register")
        response = self.client.post(
            "/register",
            data={"csrf_token": token, "email": "not-an-email", "password": "short", "confirm": "different"},
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(self._form_error(response, "register-error"), "Enter a valid email address.")

    def test_successful_login_and_new_browser_session_requires_authentication(self):
        self._register()
        response = self._login()
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response.headers["Location"].endswith("/dashboard.html"))
        for path in ("/dashboard.html", "/transactions.html", "/categories.html", "/expenses.html"):
            with self.subTest(path=path):
                self.assertEqual(self.client.get(path).status_code, 200)
        cookies = response.headers.getlist("Set-Cookie")
        session_cookie = next(value for value in cookies if value.startswith("spendwise_session="))
        self.assertIn("HttpOnly", session_cookie)
        self.assertIn("SameSite=Lax", session_cookie)
        self.assertNotIn("remember_token", " ".join(cookies))
        self.assertNotIn("Max-Age", session_cookie)

        new_session = self.app.test_client()
        protected = new_session.get("/dashboard.html")
        self.assertEqual(protected.status_code, 302)
        self.assertIn("login", protected.headers["Location"])

    def test_invalid_password_uses_generic_error(self):
        self._register()
        incorrect_password = f"incorrect-{self.password}"
        known_account = self._login(password=incorrect_password)
        unknown_client = self.app.test_client()
        unknown_account = unknown_client.post(
            "/login",
            data={
            "csrf_token": self._csrf_token("/login", unknown_client),
                "email": "unknown@example.com",
                "password": incorrect_password,
            },
        )
        expected = "Email or password is incorrect."
        self.assertEqual(self._form_error(known_account, "login-error"), expected)
        self.assertEqual(self._form_error(unknown_account, "login-error"), expected)

    def test_logout_clears_authenticated_session(self):
        self._register()
        self._login()
        token = self._csrf_token("/dashboard.html")
        response = self.client.post("/logout", data={"csrf_token": token})
        self.assertEqual(response.status_code, 302)
        self.assertIn("login", response.headers["Location"])
        self.assertEqual(self.client.get("/dashboard.html").status_code, 302)

    def test_protected_pages_redirect_unauthenticated_users(self):
        for path in ("/dashboard.html", "/transactions.html", "/categories.html", "/expenses.html"):
            with self.subTest(path=path):
                response = self.client.get(path)
                self.assertEqual(response.status_code, 302)
                self.assertIn("login", response.headers["Location"])

    def test_state_changing_auth_routes_require_csrf(self):
        self.assertEqual(self.client.post("/login", data={}).status_code, 400)
        self.assertEqual(self.client.post("/register", data={}).status_code, 400)
        self._register()
        self._login()
        self.assertEqual(self.client.post("/logout", data={}).status_code, 400)

    def test_session_expiration_and_cookie_configuration(self):
        self.assertFalse(self.app.config["SESSION_PERMANENT"])
        self.assertEqual(self.app.config["PERMANENT_SESSION_LIFETIME"], timedelta(minutes=30))
        self.assertTrue(self.app.config["SESSION_COOKIE_HTTPONLY"])
        self.assertEqual(self.app.config["SESSION_COOKIE_SAMESITE"], "Lax")

    def test_transaction_crud_uses_authenticated_owner(self):
        client = self._authenticated_client("owner@example.com")
        category_id = self._create_category("owner@example.com")
        created = self._api_request(
            client,
            "POST",
            "/api/transactions",
            {
                "merchant": "Corner Cafe",
                "amount": "12.50",
                "date": "2026-10-10",
                "description": "Lunch",
                "category_id": category_id,
                "user_id": 999999,
            },
        )
        self.assertEqual(created.status_code, 201, created.json)
        transaction_data = created.json["data"]
        transaction_id = transaction_data["id"]
        self.assertEqual(transaction_data["amount"], "12.50")
        self.assertNotIn("user_id", transaction_data)
        self.assertEqual(transaction_data["category"]["id"], category_id)

        with self.app.app_context():
            transaction = self.db.session.get(self.Transaction, transaction_id)
            owner_id = transaction.user_id
            expected_owner = self.db.session.scalar(
                self.db.select(self.User.id).where(self.User.email == "owner@example.com")
            )
            self.assertEqual(owner_id, expected_owner)

        listed = self._api_request(client, "GET", "/api/transactions")
        self.assertEqual(listed.status_code, 200)
        self.assertEqual([item["id"] for item in listed.json["data"]], [transaction_id])

        retrieved = self._api_request(client, "GET", f"/api/transactions/{transaction_id}")
        self.assertEqual(retrieved.status_code, 200)
        self.assertEqual(retrieved.json["data"]["merchant"], "Corner Cafe")

        updated = self._api_request(
            client,
            "PATCH",
            f"/api/transactions/{transaction_id}",
            {"amount": "15.75", "description": "Dinner"},
        )
        self.assertEqual(updated.status_code, 200, updated.json)
        self.assertEqual(updated.json["data"]["amount"], "15.75")
        self.assertEqual(updated.json["data"]["merchant"], "Corner Cafe")

        deleted = self._api_request(client, "DELETE", f"/api/transactions/{transaction_id}")
        self.assertEqual(deleted.status_code, 200)
        self.assertEqual(self._api_request(client, "GET", f"/api/transactions/{transaction_id}").status_code, 404)

    def test_empty_transaction_list_returns_empty_data(self):
        client = self._authenticated_client("empty@example.com")
        response = self._api_request(client, "GET", "/api/transactions")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json, {"data": []})
        malformed_id = self._api_request(client, "GET", "/api/transactions/not-an-id")
        self.assertEqual(malformed_id.status_code, 404)
        self.assertEqual(malformed_id.json["error"]["code"], "not_found")

    def test_invalid_transaction_fields_are_rejected(self):
        client = self._authenticated_client("validation@example.com")
        invalid_payloads = (
            ({"amount": "0"}, "amount"),
            ({"amount": "1.239"}, "amount"),
            ({"date": "2026-02-30"}, "date"),
            ({"description": "x" * 501}, "description"),
            ({"category_id": 999999}, "category_id"),
        )
        base = {"merchant": "Shop", "amount": "10.00", "date": "2026-10-10"}
        for invalid_fields, expected_field in invalid_payloads:
            with self.subTest(field=expected_field, value=invalid_fields):
                response = self._api_request(
                    client, "POST", "/api/transactions", {**base, **invalid_fields}
                )
                self.assertEqual(response.status_code, 400)
                self.assertEqual(response.json["error"]["code"], "validation_error")
                self.assertIn(expected_field, response.json["error"]["fields"])

    def test_category_from_another_user_is_rejected(self):
        owner_client = self._authenticated_client("category-owner@example.com")
        other_client = self._authenticated_client("other-owner@example.com")
        other_category = self._create_category("other-owner@example.com")
        response = self._api_request(
            owner_client,
            "POST",
            "/api/transactions",
            {
                "merchant": "Shop",
                "amount": "10.00",
                "date": "2026-10-10",
                "category_id": other_category,
            },
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("category_id", response.json["error"]["fields"])
        categories = self._api_request(other_client, "GET", "/api/categories")
        self.assertEqual([item["id"] for item in categories.json["data"]], [other_category])

    def test_user_cannot_access_another_users_transaction(self):
        owner_client = self._authenticated_client("transaction-owner@example.com")
        other_client = self._authenticated_client("transaction-reader@example.com")
        created = self._api_request(
            owner_client,
            "POST",
            "/api/transactions",
            {"merchant": "Private Shop", "amount": "20.00", "date": "2026-10-10"},
        )
        self.assertEqual(created.status_code, 201)
        transaction_id = created.json["data"]["id"]

        for method, data in (
            ("GET", None),
            ("PATCH", {"description": "attempted edit"}),
            ("DELETE", None),
        ):
            with self.subTest(method=method):
                response = self._api_request(
                    other_client, method, f"/api/transactions/{transaction_id}", data
                )
                self.assertEqual(response.status_code, 404)
                self.assertEqual(response.json["error"]["code"], "not_found")
        self.assertEqual(
            self._api_request(owner_client, "GET", f"/api/transactions/{transaction_id}").status_code,
            200,
        )

    def test_transaction_api_requires_authentication_and_csrf(self):
        anonymous = self.app.test_client()
        response = anonymous.get("/api/transactions")
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json["error"]["code"], "unauthorized")

        client = self._authenticated_client("csrf@example.com")
        response = self._api_request(
            client,
            "POST",
            "/api/transactions",
            {"merchant": "Shop", "amount": "10", "date": "2026-10-10"},
            csrf_token=False,
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json["error"]["code"], "csrf_failed")

    def test_database_errors_return_sanitized_json(self):
        client = self._authenticated_client("database-error@example.com")
        with patch("app.db.session.scalars", side_effect=SQLAlchemyError("private database details")):
            response = self._api_request(client, "GET", "/api/transactions")
        self.assertEqual(response.status_code, 500)
        self.assertEqual(response.json["error"]["code"], "database_error")
        self.assertNotIn(b"private database details", response.data)

    def test_csv_preview_confirm_import_and_idempotency(self):
        email = "csv-owner@example.com"
        client = self._authenticated_client(email)
        self._create_category(email)
        content = (
            " DATE , Description , AMOUNT , Category , User ID\n"
            "2026-10-10,Corner Cafe,12.50,Food,999\n"
            "2026-10-10,Corner Cafe,12.50,Food,999\n"
            "2026-10-10,Invalid refund,-4.00,Food,999\n"
        ).encode("utf-8")
        preview = self._preview_csv(client, content)
        self.assertEqual(preview.status_code, 200, preview.json)
        self.assertEqual(preview.json["data"]["valid_count"], 2)
        self.assertEqual(preview.json["data"]["invalid_count"], 1)
        self.assertFalse(preview.json["data"]["rows"][2]["valid"])
        self.assertEqual(self._transaction_count(email), 0)

        preview_id = preview.json["data"]["preview_id"]
        confirmed = self._confirm_csv(client, preview_id)
        self.assertEqual(confirmed.status_code, 201, confirmed.json)
        self.assertEqual(confirmed.json["data"]["imported_count"], 2)
        self.assertEqual(self._transaction_count(email), 2)
        repeated = self._confirm_csv(client, preview_id)
        self.assertEqual(repeated.status_code, 409)
        self.assertEqual(repeated.json["error"]["code"], "already_imported")
        reuploaded = self._preview_csv(client, content)
        self.assertEqual(reuploaded.status_code, 409)
        self.assertEqual(reuploaded.json["error"]["code"], "duplicate_file")
        self.assertEqual(self._transaction_count(email), 2)

    def test_csv_missing_columns_is_rejected(self):
        client = self._authenticated_client("csv-headers@example.com")
        response = self._preview_csv(client, b"date,amount\n2026-10-10,2.00\n")
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json["error"]["code"], "invalid_csv")
        self.assertIn("description", response.json["error"]["message"])
        self.assertIn("category", response.json["error"]["message"])

    def test_csv_invalid_dates_amounts_and_utf8_are_previewed_as_errors(self):
        email = "csv-invalid@example.com"
        client = self._authenticated_client(email)
        self._create_category(email)
        content = (
            "date,description,amount,category\n"
            "2026-02-30,Invalid date,10.00,Food\n"
            "2026-10-10,Invalid amount,-4.00,Food\n"
        ).encode("utf-8")
        preview = self._preview_csv(client, content)
        self.assertEqual(preview.status_code, 200)
        data = preview.json["data"]
        self.assertEqual(data["valid_count"], 0)
        self.assertEqual(data["invalid_count"], 2)
        self.assertTrue(any("date" in message.lower() for message in data["rows"][0]["errors"]))
        self.assertTrue(any("amount" in message.lower() for message in data["rows"][1]["errors"]))
        self.assertEqual(self._transaction_count(email), 0)

        invalid_encoding = self._preview_csv(client, b"\xff\xfe\x00\x00", "bad.csv")
        self.assertEqual(invalid_encoding.status_code, 400)
        self.assertIn("UTF-8", invalid_encoding.json["error"]["message"])
        malformed = self._preview_csv(
            client,
            b'date,description,amount,category\n2026-10-10,"unfinished,10.00,Food\n',
            "malformed.csv",
        )
        self.assertEqual(malformed.status_code, 400)
        self.assertEqual(malformed.json["error"]["code"], "invalid_csv")

    def test_csv_empty_file_and_missing_rows_are_rejected(self):
        client = self._authenticated_client("csv-empty@example.com")
        empty = self._preview_csv(client, b"")
        self.assertEqual(empty.status_code, 400)
        self.assertEqual(empty.json["error"]["code"], "invalid_csv")
        header_only = self._preview_csv(
            client, b"date,description,amount,category\n", "header-only.csv"
        )
        self.assertEqual(header_only.status_code, 400)
        self.assertIn("no transaction rows", header_only.json["error"]["message"])

    def test_csv_oversized_and_non_csv_uploads_are_rejected(self):
        client = self._authenticated_client("csv-size@example.com")
        oversized = self._preview_csv(client, b"x" * 1_000_001)
        self.assertEqual(oversized.status_code, 413)
        wrong_extension = self._preview_csv(client, b"not csv", "transactions.xlsx")
        self.assertEqual(wrong_extension.status_code, 400)
        self.assertEqual(wrong_extension.json["error"]["code"], "invalid_file_type")

    def test_csv_row_limit_is_enforced(self):
        client = self._authenticated_client("csv-row-limit@example.com")
        rows = ["date,description,amount,category"]
        rows.extend("2026-10-10,Shop,10.00,Unknown" for _ in range(101))
        response = self._preview_csv(client, ("\n".join(rows) + "\n").encode("utf-8"))
        self.assertEqual(response.status_code, 400)
        self.assertIn("at most 100 rows", response.json["error"]["message"])
        self.assertEqual(self._transaction_count("csv-row-limit@example.com"), 0)

    def test_csv_invalid_category_is_shown_and_not_imported(self):
        email = "csv-category@example.com"
        client = self._authenticated_client(email)
        content = b"date,description,amount,category\n2026-10-10,Shop,10.00,Missing\n"
        preview = self._preview_csv(client, content)
        self.assertEqual(preview.status_code, 200)
        self.assertEqual(preview.json["data"]["valid_count"], 0)
        self.assertTrue(any("active category" in message for message in preview.json["data"]["rows"][0]["errors"]))
        confirmed = self._confirm_csv(client, preview.json["data"]["preview_id"])
        self.assertEqual(confirmed.status_code, 400)
        self.assertEqual(confirmed.json["error"]["code"], "no_valid_rows")
        self.assertEqual(self._transaction_count(email), 0)

    def test_csv_category_owned_by_another_user_is_invalid(self):
        client = self._authenticated_client("csv-category-owner@example.com")
        other_email = "csv-category-other@example.com"
        self._authenticated_client(other_email)
        self._create_category(other_email, "Shared name")
        content = (
            b"date,description,amount,category\n"
            b"2026-10-10,Shop,10.00,Shared name\n"
        )
        preview = self._preview_csv(client, content)
        self.assertEqual(preview.status_code, 200)
        self.assertEqual(preview.json["data"]["valid_count"], 0)
        self.assertIn(
            "active category",
            preview.json["data"]["rows"][0]["errors"][0],
        )
        self.assertEqual(self._transaction_count("csv-category-owner@example.com"), 0)

    def test_csv_preview_requires_authentication_and_csrf(self):
        anonymous = self.app.test_client()
        response = self._preview_csv(anonymous, b"date,description,amount,category\n")
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json["error"]["code"], "unauthorized")

        client = self._authenticated_client("csv-csrf@example.com")
        response = self._preview_csv(
            client,
            b"date,description,amount,category\n",
            csrf_token=False,
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json["error"]["code"], "csrf_failed")

        self._create_category("csv-csrf@example.com")
        preview = self._preview_csv(
            client,
            b"date,description,amount,category\n2026-10-10,Shop,10.00,Food\n",
        )
        preview_id = preview.json["data"]["preview_id"]
        response = client.post(
            "/api/transactions/import/confirm",
            json={"preview_id": preview_id},
            headers={"Accept": "application/json"},
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json["error"]["code"], "csrf_failed")

    def test_csv_cancel_discards_preview_without_inserting(self):
        email = "csv-cancel@example.com"
        client = self._authenticated_client(email)
        self._create_category(email)
        preview = self._preview_csv(
            client,
            b"date,description,amount,category\n2026-10-10,Shop,10.00,Food\n",
        )
        preview_id = preview.json["data"]["preview_id"]
        rejected_cancel = self._api_request(
            client,
            "DELETE",
            f"/api/transactions/import/preview/{preview_id}",
            csrf_token=False,
        )
        self.assertEqual(rejected_cancel.status_code, 400)
        self.assertEqual(rejected_cancel.json["error"]["code"], "csrf_failed")
        cancelled = self._api_request(
            client,
            "DELETE",
            f"/api/transactions/import/preview/{preview_id}",
        )
        self.assertEqual(cancelled.status_code, 200)
        self.assertTrue(cancelled.json["data"]["cancelled"])
        confirmed = self._confirm_csv(client, preview_id)
        self.assertEqual(confirmed.status_code, 400)
        self.assertEqual(self._transaction_count(email), 0)

    def test_csv_import_rolls_back_transactions_and_receipt_on_failure(self):
        email = "csv-rollback@example.com"
        client = self._authenticated_client(email)
        self._create_category(email)
        preview = self._preview_csv(
            client,
            b"date,description,amount,category\n2026-10-10,Shop,10.00,Food\n",
        )
        preview_id = preview.json["data"]["preview_id"]
        with patch("app.db.session.commit", side_effect=SQLAlchemyError("injected failure")):
            response = self._confirm_csv(client, preview_id)
        self.assertEqual(response.status_code, 500)
        self.assertEqual(response.json["error"]["code"], "database_error")
        self.assertEqual(self._transaction_count(email), 0)
        with self.app.app_context():
            user_id = self.db.session.scalar(
                self.db.select(self.User.id).where(self.User.email == email)
            )
            receipts = self.db.session.query(self.TransactionImport).filter_by(user_id=user_id).count()
            self.assertEqual(receipts, 0)

    def test_category_crud_casefold_archive_and_owner_isolation(self):
        client = self._authenticated_client("category-api@example.com")
        created = self._api_request(
            client,
            "POST",
            "/api/categories",
            {
                "name": "  Grocery  ",
                "color": "#3478C8",
                "warning_threshold": 70,
                "monthly_budget": "120.00",
            },
        )
        self.assertEqual(created.status_code, 201, created.json)
        category_id = created.json["data"]["id"]
        self.assertEqual(created.json["data"]["name"], "Grocery")
        self.assertEqual(created.json["data"]["color"], "#3478c8")

        duplicate = self._api_request(
            client, "POST", "/api/categories", {"name": "gRoCeRy", "color": "#ffffff"}
        )
        self.assertEqual(duplicate.status_code, 409)
        invalid = self._api_request(
            client,
            "POST",
            "/api/categories",
            {"name": " ", "color": "blue", "warning_threshold": 101},
        )
        self.assertEqual(invalid.status_code, 400)
        self.assertEqual(invalid.json["error"]["code"], "validation_error")

        other = self._authenticated_client("category-api-other@example.com")
        self.assertEqual(other.get(f"/api/categories/{category_id}").status_code, 404)
        own_list = self._api_request(client, "GET", "/api/categories?status=all")
        self.assertEqual([item["id"] for item in own_list.json["data"]], [category_id])

        transaction_date = calendar_date(2026, 10, 10)
        with self.app.app_context():
            owner_id = self.db.session.scalar(
                self.db.select(self.User.id).where(self.User.email == "category-api@example.com")
            )
            transaction = self.Transaction(
                user_id=owner_id,
                category_id=category_id,
                merchant="Market",
                amount=Decimal("8.00"),
                transaction_date=transaction_date,
            )
            self.db.session.add(transaction)
            self.db.session.commit()
            transaction_id = transaction.id

        archived = self._api_request(
            client,
            "PATCH",
            f"/api/categories/{category_id}",
            {"is_archived": True},
        )
        self.assertEqual(archived.status_code, 200)
        self.assertTrue(archived.json["data"]["is_archived"])
        active_list = self._api_request(client, "GET", "/api/categories")
        self.assertEqual(active_list.json["data"], [])
        archived_list = self._api_request(client, "GET", "/api/categories?status=archived")
        self.assertEqual([item["id"] for item in archived_list.json["data"]], [category_id])
        reactivated = self._api_request(
            client,
            "PATCH",
            f"/api/categories/{category_id}",
            {"is_archived": False, "name": "Market", "color": "#ffffff"},
        )
        self.assertEqual(reactivated.status_code, 200)
        with self.app.app_context():
            transaction = self.db.session.get(self.Transaction, transaction_id)
            self.assertEqual(transaction.category_id, category_id)
            self.assertEqual(transaction.category.name, "Market")

    def test_monthly_budget_crud_history_threshold_and_owner_isolation(self):
        client = self._authenticated_client("budget-api@example.com")
        other = self._authenticated_client("budget-api-other@example.com")
        category_response = self._api_request(
            client,
            "POST",
            "/api/categories",
            {"name": "Travel", "color": "#3478c8", "warning_threshold": 80},
        )
        category_id = category_response.json["data"]["id"]

        def create_budget(year, month, amount, selected_category=category_id):
            return self._api_request(
                client,
                "POST",
                "/api/budgets",
                {
                    "category_id": selected_category,
                    "year": year,
                    "month": month,
                    "budget_amount": amount,
                },
            )

        september = create_budget(2026, 9, "150.00")
        october = create_budget(2026, 10, "100.00")
        self.assertEqual(september.status_code, 201, september.json)
        self.assertEqual(october.status_code, 201, october.json)
        duplicate = create_budget(2026, 10, "90.00")
        self.assertEqual(duplicate.status_code, 409)
        invalid_amount = create_budget(2026, 11, "-1")
        self.assertEqual(invalid_amount.status_code, 400)
        invalid_period = create_budget(9999, 12, "10")
        self.assertEqual(invalid_period.status_code, 400)
        fractional_period = create_budget(2026.5, 11, "10")
        self.assertEqual(fractional_period.status_code, 400)
        foreign_category = create_budget(2026, 11, "10", selected_category=999999)
        self.assertEqual(foreign_category.status_code, 400)
        boolean_category = create_budget(2026, 11, "10", selected_category=True)
        self.assertEqual(boolean_category.status_code, 400)

        with self.app.app_context():
            owner_id = self.db.session.scalar(
                self.db.select(self.User.id).where(self.User.email == "budget-api@example.com")
            )
            self.db.session.add(
                self.Transaction(
                    user_id=owner_id,
                    category_id=category_id,
                    merchant="Flight",
                    amount=Decimal("80.00"),
                    transaction_date=calendar_date(2026, 10, 12),
                )
            )
            self.db.session.commit()

        october_report = self._api_request(client, "GET", "/api/budgets?month=2026-10")
        october_item = next(item for item in october_report.json["data"] if item["category_id"] == category_id)
        self.assertEqual(october_item["spent"], "80.00")
        self.assertEqual(october_item["status"], "warning")
        self.assertEqual(other.get(f"/api/budgets/{october.json['data']['budget_id']}").status_code, 404)

        updated = self._api_request(
            client,
            "PATCH",
            f"/api/budgets/{october.json['data']['budget_id']}",
            {"budget_amount": "200.00"},
        )
        self.assertEqual(updated.status_code, 200)
        self.assertEqual(updated.json["data"]["status"], "normal")
        zero_budget = self._api_request(
            client,
            "PATCH",
            f"/api/budgets/{october.json['data']['budget_id']}",
            {"budget_amount": "0.00"},
        )
        self.assertEqual(zero_budget.json["data"]["status"], "unbudgeted")
        self.assertIsNone(zero_budget.json["data"]["percentage"])
        september_report = self._api_request(client, "GET", "/api/budgets?month=2026-09")
        september_item = next(item for item in september_report.json["data"] if item["category_id"] == category_id)
        self.assertEqual(september_item["budget_amount"], "150.00")

    def test_dashboard_uses_transaction_dates_and_scopes_totals(self):
        client = self._authenticated_client("dashboard-data@example.com")
        other = self._authenticated_client("dashboard-other@example.com")
        category_response = self._api_request(
            client,
            "POST",
            "/api/categories",
            {"name": "Food", "color": "#3478c8"},
        )
        category_id = category_response.json["data"]["id"]
        other_category = self._api_request(
            other,
            "POST",
            "/api/categories",
            {"name": "Private", "color": "#ffffff"},
        ).json["data"]["id"]
        with self.app.app_context():
            owner_id = self.db.session.scalar(
                self.db.select(self.User.id).where(self.User.email == "dashboard-data@example.com")
            )
            self.db.session.add_all(
                [
                    self.Transaction(user_id=owner_id, category_id=category_id, merchant="Earlier", amount=Decimal("40.00"), transaction_date=calendar_date(2026, 9, 10)),
                    self.Transaction(user_id=owner_id, category_id=category_id, merchant="Food", amount=Decimal("60.00"), transaction_date=calendar_date(2026, 10, 10)),
                    self.Transaction(user_id=owner_id, category_id=None, merchant="Uncategorized", amount=Decimal("10.00"), transaction_date=calendar_date(2026, 10, 11)),
                ]
            )
            self.db.session.commit()
        with self.app.app_context():
            other_id = self.db.session.scalar(
                self.db.select(self.User.id).where(self.User.email == "dashboard-other@example.com")
            )
            self.db.session.add(
                self.Transaction(user_id=other_id, category_id=other_category, merchant="Private", amount=Decimal("999.00"), transaction_date=calendar_date(2026, 10, 11))
            )
            self.db.session.commit()

        response = self._api_request(client, "GET", "/api/dashboard?month=2026-10")
        self.assertEqual(response.status_code, 200, response.json)
        data = response.json["data"]
        self.assertEqual(data["summary"]["total_spent"], "70.00")
        self.assertEqual(data["summary"]["transaction_count"], 2)
        self.assertEqual(data["summary"]["previous_month_total"], "40.00")
        self.assertEqual(data["summary"]["change_amount"], "30.00")
        self.assertEqual(sum(Decimal(day["amount"]) for day in data["daily_spending"]), Decimal("70.00"))
        self.assertTrue(any(item["name"] == "Uncategorized" for item in data["category_spending"]))
        self.assertNotIn("999.00", str(data))

    def test_dashboard_empty_month_returns_zero_values(self):
        client = self._authenticated_client("dashboard-empty@example.com")
        response = self._api_request(client, "GET", "/api/dashboard?month=2026-01")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json["data"]["summary"]["total_spent"], "0.00")
        self.assertEqual(response.json["data"]["summary"]["transaction_count"], 0)
        self.assertIsNone(response.json["data"]["summary"]["change_percent"])
        self.assertTrue(all(day["amount"] == "0.00" for day in response.json["data"]["daily_spending"]))

    def test_new_feature_endpoints_require_authentication(self):
        client = self.app.test_client()
        csrf_token = self._csrf_token("/login", client)
        requests = (
            ("GET", "/api/categories", None),
            ("POST", "/api/categories", {"name": "Food"}),
            ("GET", "/api/budgets?month=2026-10", None),
            ("POST", "/api/budgets", {"category_id": 1, "year": 2026, "month": 10, "budget_amount": "1.00"}),
            ("GET", "/api/dashboard?month=2026-10", None),
            ("GET", "/api/anomalies?month=2026-10", None),
            ("POST", "/api/anomalies/analyze?month=2026-10", None),
        )
        for method, path, payload in requests:
            with self.subTest(method=method, path=path):
                response = client.open(
                    path,
                    method=method,
                    json=payload,
                    headers={"Accept": "application/json", "X-CSRFToken": csrf_token},
                )
                self.assertEqual(response.status_code, 401)
                self.assertEqual(response.json["error"]["code"], "unauthorized")

    def test_anomaly_analysis_cold_start_outlier_repeat_and_acknowledgement(self):
        client = self._authenticated_client("anomaly-owner@example.com")
        other = self._authenticated_client("anomaly-other@example.com")
        category_id = self._api_request(
            client,
            "POST",
            "/api/categories",
            {"name": "Meals", "color": "#e2a23a"},
        ).json["data"]["id"]
        sparse_category_id = self._api_request(
            client,
            "POST",
            "/api/categories",
            {"name": "Travel", "color": "#3478c8"},
        ).json["data"]["id"]

        cold_start = self._api_request(client, "POST", "/api/anomalies/analyze?month=2026-10")
        self.assertEqual(cold_start.status_code, 200)
        self.assertEqual(cold_start.json["data"], [])

        with self.app.app_context():
            owner_id = self.db.session.scalar(
                self.db.select(self.User.id).where(self.User.email == "anomaly-owner@example.com")
            )
            prior = [
                self.Transaction(
                    user_id=owner_id,
                    category_id=category_id,
                    merchant=f"Meal {index}",
                    amount=Decimal("10.00"),
                    transaction_date=calendar_date(2026, 9, index + 1),
                )
                for index in range(5)
            ]
            unusual = self.Transaction(
                user_id=owner_id,
                category_id=category_id,
                merchant="Large dinner",
                amount=Decimal("80.00"),
                transaction_date=calendar_date(2026, 10, 2),
            )
            normal = self.Transaction(
                user_id=owner_id,
                category_id=category_id,
                merchant="Usual lunch",
                amount=Decimal("12.00"),
                transaction_date=calendar_date(2026, 10, 3),
            )
            uncategorized = self.Transaction(
                user_id=owner_id,
                category_id=None,
                merchant="No category",
                amount=Decimal("20.00"),
                transaction_date=calendar_date(2026, 10, 4),
            )
            sparse = self.Transaction(
                user_id=owner_id,
                category_id=sparse_category_id,
                merchant="Single trip",
                amount=Decimal("30.00"),
                transaction_date=calendar_date(2026, 10, 5),
            )
            self.db.session.add_all([*prior, unusual, normal, uncategorized, sparse])
            self.db.session.commit()

        analyzed = self._api_request(client, "POST", "/api/anomalies/analyze?month=2026-10")
        self.assertEqual(analyzed.status_code, 200)
        result = analyzed.json["data"][0]
        self.assertTrue(result["is_anomaly"])
        self.assertEqual(result["status"], "flagged")
        self.assertIn("5 earlier transactions", result["explanation"])
        self.assertEqual(result["baseline_amount"], "10.00")
        normal_result = next(item for item in analyzed.json["data"] if item["transaction"]["merchant"] == "Usual lunch")
        self.assertEqual(normal_result["status"], "normal")
        uncategorized_result = next(item for item in analyzed.json["data"] if item["transaction"]["merchant"] == "No category")
        self.assertEqual(uncategorized_result["status"], "insufficient_history")
        self.assertFalse(uncategorized_result["is_anomaly"])
        sparse_result = next(item for item in analyzed.json["data"] if item["transaction"]["merchant"] == "Single trip")
        self.assertEqual(sparse_result["status"], "insufficient_history")
        self.assertIn("Only 0 earlier transactions", sparse_result["explanation"])

        repeated = self._api_request(client, "POST", "/api/anomalies/analyze?month=2026-10")
        self.assertEqual(repeated.status_code, 200)
        with self.app.app_context():
            count = self.db.session.query(self.AnomalyAnalysis).filter_by(user_id=owner_id).count()
            self.assertEqual(count, 9)

        analysis_id = result["id"]
        foreign_ack = self._api_request(other, "POST", f"/api/anomalies/{analysis_id}/acknowledge")
        self.assertEqual(foreign_ack.status_code, 404)
        acknowledged = self._api_request(client, "POST", f"/api/anomalies/{analysis_id}/acknowledge")
        self.assertEqual(acknowledged.status_code, 200)
        self.assertTrue(acknowledged.json["data"]["acknowledged"])

        changed = self._api_request(
            client,
            "PATCH",
            f"/api/transactions/{result['transaction_id']}",
            {"amount": "81.00"},
        )
        self.assertEqual(changed.status_code, 200)
        with self.app.app_context():
            self.assertEqual(self.db.session.query(self.AnomalyAnalysis).filter_by(user_id=owner_id).count(), 0)


if __name__ == "__main__":
    unittest.main()