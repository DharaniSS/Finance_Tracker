import hashlib
import os
from pathlib import Path

from sqlalchemy import inspect

from app import app
from extensions import db
from models import AnomalyAnalysis, Category, MonthlyBudget, Transaction, TransactionImport, User

EXPECTED_MODELS = (User, Category, Transaction, MonthlyBudget, TransactionImport, AnomalyAnalysis)
EXPECTED_TABLES = {model.__tablename__ for model in EXPECTED_MODELS}


def initialize_database():
    instance_path = Path(app.instance_path)
    instance_path.mkdir(parents=True, exist_ok=True)
    expected_path = Path(
        os.environ.get("SPENDWISE_DATABASE_PATH", instance_path / "spendwise.db")
    ).resolve()

    with app.app_context():
        engine = db.engine
        configured_path = Path(engine.url.database).resolve()
        if configured_path != expected_path:
            raise RuntimeError(
                f"Configured database path {configured_path} does not match {expected_path}"
            )

        database_existed = expected_path.exists()
        inspector = inspect(engine)
        existing_tables = set(inspector.get_table_names())

        if "categories" in existing_tables:
            with engine.connect() as connection:
                names = connection.exec_driver_sql("SELECT user_id, name FROM categories").all()
            seen_names = set()
            for user_id, name in names:
                key = (user_id, name.strip().casefold())
                if key in seen_names:
                    raise RuntimeError(
                        "Case-insensitive category name conflicts exist; resolve them before migration."
                    )
                seen_names.add(key)

            category_columns = {
                column["name"] for column in inspector.get_columns("categories")
            }
            if "name_key" not in category_columns:
                with engine.begin() as connection:
                    connection.exec_driver_sql(
                        "ALTER TABLE categories ADD COLUMN name_key VARCHAR(100) NOT NULL DEFAULT ''"
                    )
                    rows = connection.exec_driver_sql("SELECT id, name FROM categories").all()
                    for category_id, name in rows:
                        connection.exec_driver_sql(
                            "UPDATE categories SET name_key = ? WHERE id = ?",
                            (name.strip().casefold(), category_id),
                        )

        if "transactions" in existing_tables:
            transaction_columns = {
                column["name"] for column in inspector.get_columns("transactions")
            }
            if "merchant" not in transaction_columns:
                with engine.begin() as connection:
                    connection.exec_driver_sql(
                        "ALTER TABLE transactions ADD COLUMN merchant VARCHAR(80) NOT NULL DEFAULT ''"
                    )
            with engine.begin() as connection:
                connection.exec_driver_sql(
                    "CREATE UNIQUE INDEX IF NOT EXISTS uq_transactions_user_id_id "
                    "ON transactions (user_id, id)"
                )

        if "transaction_imports" in existing_tables:
            import_columns = {
                column["name"] for column in inspector.get_columns("transaction_imports")
            }
            if "file_digest" not in import_columns:
                with engine.begin() as connection:
                    connection.exec_driver_sql(
                        "ALTER TABLE transaction_imports ADD COLUMN file_digest VARCHAR(64) NOT NULL DEFAULT ''"
                    )
            with engine.begin() as connection:
                rows = connection.exec_driver_sql(
                    "SELECT id FROM transaction_imports WHERE file_digest = ''"
                ).all()
                for (receipt_id,) in rows:
                    digest = hashlib.sha256(f"legacy-import:{receipt_id}".encode()).hexdigest()
                    connection.exec_driver_sql(
                        "UPDATE transaction_imports SET file_digest = ? WHERE id = ?",
                        (digest, receipt_id),
                    )
                connection.exec_driver_sql(
                    "CREATE UNIQUE INDEX IF NOT EXISTS uq_transaction_imports_user_digest "
                    "ON transaction_imports (user_id, file_digest)"
                )

        db.create_all()

        if "categories" in existing_tables:
            with engine.begin() as connection:
                connection.exec_driver_sql(
                    "CREATE UNIQUE INDEX IF NOT EXISTS uq_categories_user_name_key "
                    "ON categories (user_id, name_key)"
                )

        tables = set(inspect(engine).get_table_names())
        missing_tables = EXPECTED_TABLES - tables
        if missing_tables:
            raise RuntimeError(f"Database is missing expected tables: {sorted(missing_tables)}")

        with engine.connect() as connection:
            foreign_keys_enabled = connection.exec_driver_sql("PRAGMA foreign_keys").scalar_one()
        if foreign_keys_enabled != 1:
            raise RuntimeError("SQLite foreign-key enforcement is not enabled")

    database_status = (
        "Existing database preserved; existing tables were not replaced."
        if database_existed
        else "Database file created."
    )
    print(f"Database: {expected_path}")
    print(database_status)
    print(f"Tables found: {', '.join(sorted(tables))}")
    print(f"PRAGMA foreign_keys: {foreign_keys_enabled}")


if __name__ == "__main__":
    initialize_database()