"""
budget_tracker.py — Per-user budget logic for CashRadar.

Replaces the old JSON-file-based budget_tracker.py.
All state now lives in SQLite via db.py.

Main entry point: process_transaction(user_id, transaction)
Returns a budget_info dict for notifier.py to format.
"""

from datetime import date, datetime
from db import (
    get_budget, get_spending, save_spending,
    get_merchants, log_transaction, save_merchant
)


# ─── Day rollover ─────────────────────────────────────────────────────────────

def check_day_rollover(spending: dict, budget: dict) -> dict:
    """
    If it's a new day, calculate deficit carry-over, update streak, reset today.
    Mutates and returns the spending dict.
    """
    today_str = date.today().isoformat()
    month_str = date.today().strftime("%Y-%m")

    if spending["day"] == today_str:
        return spending  # same day, nothing to do

    # ── New day ──
    effective_limit = budget["daily_limit"] + spending.get("carry_over", 0)
    yesterday_spent = spending["today_spent"]
    deficit = max(0, yesterday_spent - effective_limit)

    # Streak: did they stay within budget yesterday?
    last_date = spending.get("last_streak_date")
    yesterday = (date.today().replace(day=date.today().day - 1)).isoformat() \
        if date.today().day > 1 else None

    if yesterday_spent <= effective_limit:
        # Within budget — extend streak if consecutive
        if last_date == yesterday:
            spending["streak"] += 1
        elif last_date != spending["day"]:
            spending["streak"] = 1
        spending["last_streak_date"] = spending["day"]
    else:
        spending["streak"] = 0

    spending["carry_over"] = deficit
    spending["today_spent"] = 0.0
    spending["day"] = today_str
    spending["month"] = month_str

    return spending


# ─── Categorisation ───────────────────────────────────────────────────────────

def categorise(description: str, merchants: dict) -> str:
    """Keyword-match description against user's merchant map."""
    if not description:
        return "Uncategorized"
    desc_lower = description.lower()
    for keyword, category in merchants.items():
        if keyword.lower() in desc_lower:
            return category
    return "Uncategorized"


# ─── Credit allocation ────────────────────────────────────────────────────────

def allocate_credit(amount: float, budget: dict, spending: dict) -> dict:
    """On a credit, calculate savings and investing amounts, update pots."""
    savings_amount   = round(amount * budget["savings_rate"], 2)
    investing_amount = round(amount * budget["investing_rate"], 2)
    spending["savings_pot"]    += savings_amount
    spending["investing_pool"] += investing_amount
    return {"savings": savings_amount, "investing": investing_amount}


# ─── Velocity check ───────────────────────────────────────────────────────────

def check_velocity(spending: dict, budget: dict) -> bool:
    """Returns True if >40% of effective daily budget spent before noon."""
    now = datetime.now()
    if now.hour >= 12:
        return False
    effective_limit = budget["daily_limit"] + spending.get("carry_over", 0)
    return spending["today_spent"] > (effective_limit * 0.4)


# ─── Days until balance runs out ──────────────────────────────────────────────

def days_until_balance_out(balance: float, spending: dict, budget: dict) -> int | None:
    """Rough estimate: how many days until balance hits zero at current rate."""
    if not balance or balance <= 0:
        return None
    total = spending.get("total_spent", 0)
    # Count days in the current month so far
    days_elapsed = date.today().day
    if days_elapsed > 2 and total > 0:
        avg_daily = total / days_elapsed
    else:
        avg_daily = budget["daily_limit"]
    if avg_daily <= 0:
        return None
    return int(balance / avg_daily)


# ─── Payday detection ─────────────────────────────────────────────────────────

def is_payday(amount: float, budget: dict) -> bool:
    return amount >= budget.get("payday_threshold", 50000)


# ─── Main entry point ─────────────────────────────────────────────────────────

def process_transaction(user_id: int, transaction: dict) -> dict:
    """
    Called from email_poller.py for each parsed transaction.
    Loads state, applies logic, saves state, returns budget_info dict.

    transaction keys: type, amount, description, balance
    """
    budget   = get_budget(user_id)
    spending = get_spending(user_id)
    merchants = get_merchants(user_id)

    # Ensure user_id is present in spending dict (for save_spending)
    spending["user_id"] = user_id

    spending = check_day_rollover(spending, budget)

    tx_type     = transaction["type"]
    amount      = transaction["amount"]
    description = transaction.get("description", "")
    balance     = transaction.get("balance")

    category   = categorise(description, merchants)
    budget_info = {"category": category}

    if tx_type == "debit":
        spending["today_spent"] += amount
        spending["total_spent"] += amount

        effective_limit = budget["daily_limit"] + spending.get("carry_over", 0)
        days_left = days_until_balance_out(balance, spending, budget)

        budget_info.update({
            "today_spent":    spending["today_spent"],
            "effective_limit": effective_limit,
            "carry_over":     spending.get("carry_over", 0),
            "days_left":      days_left,
            "streak":         spending.get("streak", 0),
            "velocity_warning": check_velocity(spending, budget),
            "over_budget":    spending["today_spent"] > effective_limit,
        })

    elif tx_type == "credit":
        allocation = allocate_credit(amount, budget, spending)
        budget_info["allocation"] = allocation

        # Payday detection
        if is_payday(amount, budget):
            budget_info["is_payday"] = True

    log_transaction(user_id, tx_type, amount, description, balance, category)
    save_spending(spending)

    return budget_info
