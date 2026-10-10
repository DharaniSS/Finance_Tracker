from decimal import Decimal

from extensions import db
from flask_login import UserMixin
from sqlalchemy import and_, event
from sqlalchemy.orm import foreign


class TransactionImport(db.Model):
    __tablename__ = "transaction_imports"
    __table_args__ = (
        db.UniqueConstraint("user_id", "preview_id", name="uq_transaction_imports_user_preview"),
        db.UniqueConstraint("user_id", "file_digest", name="uq_transaction_imports_user_digest"),
    )

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    preview_id = db.Column(db.String(64), nullable=False)
    file_digest = db.Column(db.String(64), nullable=False)
    created_at = db.Column(
        db.DateTime(timezone=True), nullable=False, server_default=db.func.current_timestamp()
    )


class User(UserMixin, db.Model):
    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(255), nullable=False, unique=True)
    password_hash = db.Column(db.String(255), nullable=False)
    created_at = db.Column(
        db.DateTime(timezone=True), nullable=False, server_default=db.func.current_timestamp()
    )

    categories = db.relationship("Category", back_populates="user")
    transactions = db.relationship("Transaction", back_populates="user")
    monthly_budgets = db.relationship("MonthlyBudget", back_populates="user")


class Category(db.Model):
    __tablename__ = "categories"
    __table_args__ = (
        db.UniqueConstraint("user_id", "id", name="uq_categories_user_id_id"),
        db.UniqueConstraint("user_id", "name", name="uq_categories_user_name"),
        db.CheckConstraint("monthly_budget >= 0", name="ck_categories_budget_nonnegative"),
        db.CheckConstraint(
            "warning_threshold >= 0 AND warning_threshold <= 100",
            name="ck_categories_warning_threshold_percent",
        ),
        db.UniqueConstraint("user_id", "name_key", name="uq_categories_user_name_key"),
    )

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    name = db.Column(db.String(100), nullable=False)
    name_key = db.Column(db.String(100), nullable=False, default="")
    color = db.Column(db.String(7), nullable=True)
    monthly_budget = db.Column(db.Numeric(12, 2), nullable=False, default=Decimal("0.00"))
    warning_threshold = db.Column(db.Integer, nullable=False, default=80)
    is_archived = db.Column(db.Boolean, nullable=False, default=False)

    user = db.relationship("User", back_populates="categories")
    transactions = db.relationship(
        "Transaction",
        primaryjoin=lambda: and_(
            Category.user_id == Transaction.user_id,
            Category.id == foreign(Transaction.category_id),
        ),
        foreign_keys=lambda: [Transaction.category_id],
        back_populates="category",
    )
    monthly_budgets = db.relationship(
        "MonthlyBudget",
        primaryjoin=lambda: and_(
            Category.user_id == MonthlyBudget.user_id,
            Category.id == foreign(MonthlyBudget.category_id),
        ),
        foreign_keys=lambda: [MonthlyBudget.category_id],
        back_populates="category",
    )


@event.listens_for(Category, "before_insert")
@event.listens_for(Category, "before_update")
def normalize_category_name(mapper, connection, category):
    if isinstance(category.name, str):
        category.name = category.name.strip()
        category.name_key = category.name.casefold()

class Transaction(db.Model):
    __tablename__ = "transactions"
    __table_args__ = (
        db.UniqueConstraint("user_id", "id", name="uq_transactions_user_id_id"),
        db.ForeignKeyConstraint(
            ["user_id", "category_id"],
            ["categories.user_id", "categories.id"],
            name="fk_transactions_user_category",
        ),
        db.CheckConstraint("amount > 0", name="ck_transactions_amount_positive"),
    )

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    category_id = db.Column(db.Integer, nullable=True)
    merchant = db.Column(db.String(80), nullable=False, default="")
    amount = db.Column(db.Numeric(12, 2), nullable=False)
    transaction_date = db.Column(db.Date, nullable=False)
    description = db.Column(db.Text, nullable=True)
    created_at = db.Column(
        db.DateTime(timezone=True), nullable=False, server_default=db.func.current_timestamp()
    )

    user = db.relationship("User", back_populates="transactions")
    category = db.relationship(
        "Category",
        primaryjoin=lambda: and_(
            Category.user_id == Transaction.user_id,
            Category.id == foreign(Transaction.category_id),
        ),
        foreign_keys=lambda: [Transaction.category_id],
        back_populates="transactions",
    )


class MonthlyBudget(db.Model):
    __tablename__ = "monthly_budgets"
    __table_args__ = (
        db.UniqueConstraint(
            "user_id", "category_id", "year", "month", name="uq_monthly_budgets_user_category_period"
        ),
        db.ForeignKeyConstraint(
            ["user_id", "category_id"],
            ["categories.user_id", "categories.id"],
            name="fk_monthly_budgets_user_category",
        ),
        db.CheckConstraint("budget_amount >= 0", name="ck_monthly_budgets_amount_nonnegative"),
        db.CheckConstraint("year >= 1", name="ck_monthly_budgets_year_positive"),
        db.CheckConstraint("month >= 1 AND month <= 12", name="ck_monthly_budgets_month_range"),
    )

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    category_id = db.Column(db.Integer, nullable=False)
    year = db.Column(db.Integer, nullable=False)
    month = db.Column(db.Integer, nullable=False)
    budget_amount = db.Column(db.Numeric(12, 2), nullable=False, default=Decimal("0.00"))

    user = db.relationship("User", back_populates="monthly_budgets")
    category = db.relationship(
        "Category",
        primaryjoin=lambda: and_(
            Category.user_id == MonthlyBudget.user_id,
            Category.id == foreign(MonthlyBudget.category_id),
        ),
        foreign_keys=lambda: [MonthlyBudget.category_id],
        back_populates="monthly_budgets",
    )

class AnomalyAnalysis(db.Model):
    __tablename__ = "anomaly_analyses"
    __table_args__ = (
        db.UniqueConstraint(
            "user_id", "transaction_id", name="uq_anomaly_analyses_user_transaction"
        ),
        db.ForeignKeyConstraint(
            ["user_id", "transaction_id"],
            ["transactions.user_id", "transactions.id"],
            name="fk_anomaly_analyses_user_transaction",
        ),
        db.CheckConstraint(
            "status IN ('flagged', 'normal', 'insufficient_history')",
            name="ck_anomaly_analyses_status",
        ),
        db.CheckConstraint("sample_count >= 0", name="ck_anomaly_analyses_sample_count"),
    )

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    transaction_id = db.Column(db.Integer, nullable=False)
    status = db.Column(db.String(32), nullable=False)
    is_anomaly = db.Column(db.Boolean, nullable=False, default=False)
    explanation = db.Column(db.Text, nullable=False)
    severity = db.Column(db.String(16), nullable=True)
    confidence = db.Column(db.Numeric(4, 3), nullable=True)
    baseline_amount = db.Column(db.Numeric(12, 2), nullable=True)
    threshold_amount = db.Column(db.Numeric(12, 2), nullable=True)
    sample_count = db.Column(db.Integer, nullable=False, default=0)
    analyzed_at = db.Column(
        db.DateTime(timezone=True), nullable=False, server_default=db.func.current_timestamp()
    )
    acknowledged_at = db.Column(db.DateTime(timezone=True), nullable=True)

    user = db.relationship("User")
    transaction = db.relationship(
        "Transaction",
        primaryjoin=lambda: and_(
            Transaction.user_id == AnomalyAnalysis.user_id,
            Transaction.id == foreign(AnomalyAnalysis.transaction_id),
        ),
        foreign_keys=lambda: [AnomalyAnalysis.transaction_id],
    )
