from collections import defaultdict
from datetime import date, datetime, timezone
from decimal import Decimal, ROUND_HALF_UP

from sqlalchemy import delete, func, select

from extensions import db
from models import AnomalyAnalysis, Category, MonthlyBudget, Transaction

CENT = Decimal("0.01")
ZERO = Decimal("0.00")
MIN_ANOMALY_HISTORY = 5


def month_bounds(year, month):
    start = date(year, month, 1)
    end = date(year + 1, 1, 1) if month == 12 else date(year, month + 1, 1)
    return start, end


def budget_status(spent, budget, warning_threshold):
    spent = Decimal(spent or ZERO)
    budget = Decimal(budget or ZERO)
    threshold = int(warning_threshold)
    threshold_amount = (budget * Decimal(threshold) / Decimal(100)).quantize(CENT)
    percentage = (
        (spent * Decimal(100) / budget).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)
        if budget > 0
        else None
    )
    if budget <= 0:
        status = "unbudgeted"
    elif spent >= budget:
        status = "exceeded"
    elif spent >= threshold_amount:
        status = "warning"
    else:
        status = "normal"
    return {
        "spent": spent.quantize(CENT),
        "budget_amount": budget.quantize(CENT),
        "threshold_amount": threshold_amount,
        "warning_threshold": threshold,
        "percentage": percentage,
        "remaining": max(ZERO, budget - spent).quantize(CENT),
        "status": status,
    }


def monthly_budget_report(user_id, year, month, include_unbudgeted=True):
    start, end = month_bounds(year, month)
    categories = db.session.scalars(
        select(Category)
        .where(Category.user_id == user_id)
        .order_by(Category.is_archived, Category.name_key, Category.id)
    ).all()
    budgets = db.session.scalars(
        select(MonthlyBudget).where(
            MonthlyBudget.user_id == user_id,
            MonthlyBudget.year == year,
            MonthlyBudget.month == month,
        )
    ).all()
    budget_by_category = {item.category_id: item for item in budgets}
    totals = db.session.execute(
        select(Transaction.category_id, func.sum(Transaction.amount))
        .where(
            Transaction.user_id == user_id,
            Transaction.transaction_date >= start,
            Transaction.transaction_date < end,
            Transaction.category_id.is_not(None),
        )
        .group_by(Transaction.category_id)
    ).all()
    spent_by_category = {category_id: total or ZERO for category_id, total in totals}

    report = []
    for category in categories:
        budget_record = budget_by_category.get(category.id)
        if not include_unbudgeted and budget_record is None:
            continue
        metrics = budget_status(
            spent_by_category.get(category.id, ZERO),
            budget_record.budget_amount if budget_record else ZERO,
            category.warning_threshold,
        )
        report.append(
            {
                "budget_id": budget_record.id if budget_record else None,
                "category_id": category.id,
                "category_name": category.name,
                "category_color": category.color,
                "is_archived": category.is_archived,
                "year": year,
                "month": month,
                **{key: format(value, ".2f") if isinstance(value, Decimal) else value for key, value in metrics.items()},
            }
        )
    return report


def _median(values):
    ordered = sorted(values)
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[middle]
    return ((ordered[middle - 1] + ordered[middle]) / Decimal(2)).quantize(CENT)


def _serialize_analysis(analysis):
    return {
        "id": analysis.id,
        "transaction_id": analysis.transaction_id,
        "status": analysis.status,
        "is_anomaly": analysis.is_anomaly,
        "explanation": analysis.explanation,
        "severity": analysis.severity,
        "confidence": format(analysis.confidence, ".3f") if analysis.confidence is not None else None,
        "baseline_amount": format(analysis.baseline_amount, ".2f") if analysis.baseline_amount is not None else None,
        "threshold_amount": format(analysis.threshold_amount, ".2f") if analysis.threshold_amount is not None else None,
        "sample_count": analysis.sample_count,
        "analyzed_at": analysis.analyzed_at.isoformat() if analysis.analyzed_at else None,
        "acknowledged": analysis.acknowledged_at is not None,
    }


def analyze_user_transactions(user_id):
    transactions = db.session.scalars(
        select(Transaction)
        .where(Transaction.user_id == user_id)
        .order_by(Transaction.transaction_date, Transaction.id)
    ).all()
    existing = {
        analysis.transaction_id: analysis
        for analysis in db.session.scalars(
            select(AnomalyAnalysis).where(AnomalyAnalysis.user_id == user_id)
        ).all()
    }
    history = defaultdict(list)
    results = []

    for transaction in transactions:
        category_history = history[transaction.category_id] if transaction.category_id is not None else []
        sample_count = len(category_history)
        baseline = None
        threshold = None
        confidence = None
        severity = None
        flagged = False

        if transaction.category_id is None or sample_count < MIN_ANOMALY_HISTORY:
            status = "insufficient_history"
            if transaction.category_id is None:
                explanation = "This uncategorized transaction has no category baseline to compare against."
            else:
                explanation = (
                    f"Only {sample_count} earlier transactions exist in this category; "
                    f"at least {MIN_ANOMALY_HISTORY} are needed for a comparison."
                )
        else:
            amounts = [Decimal(item.amount) for item in category_history]
            baseline = _median(amounts)
            deviations = [abs(amount - baseline) for amount in amounts]
            mad = _median(deviations)
            spread = mad * Decimal("4.4478")
            threshold = max(baseline + spread, baseline * Decimal(3)).quantize(CENT)
            amount = Decimal(transaction.amount)
            flagged = amount > threshold
            status = "flagged" if flagged else "normal"
            confidence = min(Decimal("0.95"), Decimal("0.50") + Decimal(sample_count) / Decimal(50))
            confidence = confidence.quantize(Decimal("0.001"))
            if flagged:
                multiple = amount / baseline if baseline > 0 else Decimal("Infinity")
                severity = "high" if multiple >= Decimal(5) else "medium"
                explanation = (
                    f"Amount {amount.quantize(CENT)} exceeds the historical threshold "
                    f"{threshold} for this category, based on {sample_count} earlier transactions."
                )
            else:
                explanation = (
                    f"Amount {amount.quantize(CENT)} is within the historical threshold "
                    f"{threshold} for this category, based on {sample_count} earlier transactions."
                )

        analysis = existing.get(transaction.id)
        if analysis is None:
            analysis = AnomalyAnalysis(user_id=user_id, transaction_id=transaction.id)
            db.session.add(analysis)
        analysis.status = status
        analysis.is_anomaly = flagged
        analysis.explanation = explanation
        analysis.severity = severity
        analysis.confidence = confidence
        analysis.baseline_amount = baseline
        analysis.threshold_amount = threshold
        analysis.sample_count = sample_count
        analysis.analyzed_at = datetime.now(timezone.utc)
        results.append((transaction, analysis))

        if transaction.category_id is not None:
            history[transaction.category_id].append(transaction)

    active_ids = {transaction.id for transaction in transactions}
    for transaction_id, analysis in existing.items():
        if transaction_id not in active_ids:
            db.session.delete(analysis)
    db.session.flush()
    return results


def invalidate_user_anomalies(user_id):
    db.session.execute(delete(AnomalyAnalysis).where(AnomalyAnalysis.user_id == user_id))


def serialize_analysis_for_transaction(transaction, analysis):
    result = _serialize_analysis(analysis)
    result["transaction"] = {
        "merchant": transaction.merchant,
        "amount": format(transaction.amount, ".2f"),
        "date": transaction.transaction_date.isoformat(),
        "category_id": transaction.category_id,
        "category": transaction.category.name if transaction.category else None,
    }
    return result
