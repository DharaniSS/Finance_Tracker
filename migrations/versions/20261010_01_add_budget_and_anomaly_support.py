"""Additive schema support for category keys, imports, and local analysis.

Revision ID: 20261010_01
Revises:
Create Date: 2026-10-10
"""

import hashlib

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision = "20261010_01"
down_revision = None
branch_labels = None
depends_on = None


BASE_TABLES = {"users", "categories", "transactions", "monthly_budgets"}


def upgrade():
    bind = op.get_bind()
    inspector = inspect(bind)
    existing_tables = set(inspector.get_table_names())
    missing_base = BASE_TABLES - existing_tables
    if missing_base:
        raise RuntimeError(
            "Run python init_db.py before this migration; missing base tables: "
            + ", ".join(sorted(missing_base))
        )

    category_rows = bind.execute(sa.text("SELECT user_id, name FROM categories")).all()
    seen_names = set()
    for user_id, name in category_rows:
        key = (user_id, name.strip().casefold())
        if key in seen_names:
            raise RuntimeError(
                "Case-insensitive category name conflicts exist; resolve them before migration."
            )
        seen_names.add(key)

    category_columns = {column["name"] for column in inspector.get_columns("categories")}
    if "name_key" not in category_columns:
        op.add_column(
            "categories",
            sa.Column("name_key", sa.String(length=100), nullable=False, server_default=""),
        )
        for category_id, name in bind.execute(sa.text("SELECT id, name FROM categories")).all():
            bind.execute(
                sa.text("UPDATE categories SET name_key = :key WHERE id = :id"),
                {"key": name.strip().casefold(), "id": category_id},
            )
    op.create_index(
        "uq_categories_user_name_key",
        "categories",
        ["user_id", "name_key"],
        unique=True,
        if_not_exists=True,
    )

    transaction_columns = {column["name"] for column in inspector.get_columns("transactions")}
    if "merchant" not in transaction_columns:
        op.add_column(
            "transactions",
            sa.Column("merchant", sa.String(length=80), nullable=False, server_default=""),
        )
    op.create_index(
        "uq_transactions_user_id_id",
        "transactions",
        ["user_id", "id"],
        unique=True,
        if_not_exists=True,
    )

    if "transaction_imports" not in existing_tables:
        op.create_table(
            "transaction_imports",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
            sa.Column("preview_id", sa.String(length=64), nullable=False),
            sa.Column("file_digest", sa.String(length=64), nullable=False),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.func.current_timestamp(),
            ),
            sa.UniqueConstraint("user_id", "preview_id", name="uq_transaction_imports_user_preview"),
            sa.UniqueConstraint("user_id", "file_digest", name="uq_transaction_imports_user_digest"),
        )
    else:
        import_columns = {
            column["name"] for column in inspector.get_columns("transaction_imports")
        }
        if "file_digest" not in import_columns:
            op.add_column(
                "transaction_imports",
                sa.Column("file_digest", sa.String(length=64), nullable=False, server_default=""),
            )
        for receipt_id, in bind.execute(
            sa.text("SELECT id FROM transaction_imports WHERE file_digest = ''")
        ).all():
            digest = hashlib.sha256(f"legacy-import:{receipt_id}".encode()).hexdigest()
            bind.execute(
                sa.text("UPDATE transaction_imports SET file_digest = :digest WHERE id = :id"),
                {"digest": digest, "id": receipt_id},
            )
        op.create_index(
            "uq_transaction_imports_user_digest",
            "transaction_imports",
            ["user_id", "file_digest"],
            unique=True,
            if_not_exists=True,
        )

    if "anomaly_analyses" not in existing_tables:
        op.create_table(
            "anomaly_analyses",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
            sa.Column("transaction_id", sa.Integer(), nullable=False),
            sa.Column("status", sa.String(length=32), nullable=False),
            sa.Column("is_anomaly", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("explanation", sa.Text(), nullable=False),
            sa.Column("severity", sa.String(length=16), nullable=True),
            sa.Column("confidence", sa.Numeric(4, 3), nullable=True),
            sa.Column("baseline_amount", sa.Numeric(12, 2), nullable=True),
            sa.Column("threshold_amount", sa.Numeric(12, 2), nullable=True),
            sa.Column("sample_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column(
                "analyzed_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.func.current_timestamp(),
            ),
            sa.Column("acknowledged_at", sa.DateTime(timezone=True), nullable=True),
            sa.UniqueConstraint(
                "user_id", "transaction_id", name="uq_anomaly_analyses_user_transaction"
            ),
            sa.ForeignKeyConstraint(
                ["user_id", "transaction_id"],
                ["transactions.user_id", "transactions.id"],
                name="fk_anomaly_analyses_user_transaction",
            ),
            sa.CheckConstraint(
                "status IN ('flagged', 'normal', 'insufficient_history')",
                name="ck_anomaly_analyses_status",
            ),
            sa.CheckConstraint("sample_count >= 0", name="ck_anomaly_analyses_sample_count"),
        )


def downgrade():
    raise RuntimeError(
        "This data-preserving migration is forward-only. Restore a verified database backup to roll back."
    )