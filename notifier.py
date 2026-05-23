"""
notifier.py — Telegram message formatter for CashRadar.

Sends messages in monospace box format using Telegram's <pre> tag.
All box-drawing uses Unicode box characters that align perfectly in
Telegram's fixed-width font.

Box width: 28 characters of content (30 including the two border chars │ │).
"""

import asyncio
from datetime import datetime
from telegram import Bot
from config import TELEGRAM_TOKEN

# ─── Box drawing constants ────────────────────────────────────────────────────

W = 28  # inner content width

TOP    = "┌" + "─" * W + "┐"
SEP    = "├" + "─" * W + "┤"
BOT    = "└" + "─" * W + "┘"
BLANK  = "│" + " " * W + "│"


def row(text: str) -> str:
    """Single content row, padded to exactly W chars."""
    return "│" + text[:W].ljust(W) + "│"


def progress_bar(spent: float, limit: float, width: int = 18) -> str:
    """
    Returns a string like: [████████░░░░░░░░░░] 42%
    Uses █ for spent and ░ for remaining.
    """
    if limit <= 0:
        pct = 100
    else:
        pct = min(100, int((spent / limit) * 100))
    filled = int((pct / 100) * width)
    bar = "█" * filled + "░" * (width - filled)
    return f"[{bar}] {pct}%"


# ─── Message builders ─────────────────────────────────────────────────────────

def build_debit_message(transaction: dict, budget_info: dict) -> str:
    now = datetime.now()
    date_str = now.strftime("%d %b %Y")
    time_str = now.strftime("%H:%M")

    amount      = transaction["amount"]
    description = (transaction.get("description") or "Bank transaction")[:W]
    category    = budget_info.get("category", "Uncategorized")
    today_spent = budget_info.get("today_spent", 0)
    eff_limit   = budget_info.get("effective_limit", 0)
    left        = max(0, eff_limit - today_spent)
    carry_over  = budget_info.get("carry_over", 0)
    streak      = budget_info.get("streak", 0)
    days_left   = budget_info.get("days_left")
    over        = budget_info.get("over_budget", False)
    velocity    = budget_info.get("velocity_warning", False)

    bar = progress_bar(today_spent, eff_limit)

    lines = [
        TOP,
        row(" DEBIT ALERT"),
        SEP,
        row(f" Date:    {date_str}"),
        row(f" Time:    {time_str}"),
        row(f" Amount:  \u20a6{amount:,.0f}"),
        row(f" Category:{category}"),
        row(f" Note: {description}"),
        SEP,
        row(f" Spent:  \u20a6{today_spent:,.0f}"),
        row(f" Left:   \u20a6{left:,.0f}"),
        BLANK,
        row(f" {bar}"),
        BLANK,
        row(" \u2588 spent  \u2591 remaining"),
    ]

    # Optional extras
    extras = []
    if carry_over > 0:
        extras.append(row(f" \u26a0\ufe0f Carry over: \u20a6{carry_over:,.0f}"))
    if over:
        extras.append(row(" \u274c Over budget today!"))
    if velocity:
        extras.append(row(" \u26a1 40%+ spent before noon"))
    if streak > 0:
        extras.append(row(f" \U0001f525 Streak: {streak} day(s) on budget"))
    if days_left is not None:
        extras.append(row(f" \u23f3 Balance ~{days_left} days left"))

    if extras:
        lines.append(SEP)
        lines.extend(extras)

    lines.append(BOT)
    return "<pre>" + "\n".join(lines) + "</pre>"


def build_credit_message(transaction: dict, budget_info: dict) -> str:
    now = datetime.now()
    date_str = now.strftime("%d %b %Y")
    time_str = now.strftime("%H:%M")

    amount      = transaction["amount"]
    description = (transaction.get("description") or "Bank transaction")[:W]
    balance     = transaction.get("balance")
    allocation  = budget_info.get("allocation", {})
    savings     = allocation.get("savings", 0)
    investing   = allocation.get("investing", 0)
    is_payday   = budget_info.get("is_payday", False)

    header = " PAYDAY \U0001f389" if is_payday else " CREDIT ALERT"

    lines = [
        TOP,
        row(header),
        SEP,
        row(f" Date:   {date_str}"),
        row(f" Time:   {time_str}"),
        row(f" Amount: \u20a6{amount:,.0f}"),
        row(f" Note: {description}"),
    ]

    if balance is not None:
        lines.append(row(f" Balance:\u20a6{balance:,.0f}"))

    if allocation:
        lines += [
            SEP,
            row(" AUTO-ALLOCATION"),
            row(f" Savings (10%): \u20a6{savings:,.0f}"),
            row(f" Invest  (5%):  \u20a6{investing:,.0f}"),
        ]

    lines.append(BOT)
    return "<pre>" + "\n".join(lines) + "</pre>"


def build_summary_message(user_id: int) -> str:
    """
    Daily summary box — called by daily_summary.py.
    Imports db directly to avoid circular deps.
    """
    from db import get_spending, get_budget, get_transactions_this_month
    from datetime import date

    budget   = get_budget(user_id)
    spending = get_spending(user_id)
    txns     = get_transactions_this_month(user_id)
    today    = date.today().strftime("%d %b %Y")

    daily_limit  = budget["daily_limit"]
    today_spent  = spending.get("today_spent", 0)
    carry_over   = spending.get("carry_over", 0)
    total_spent  = spending.get("total_spent", 0)
    savings_pot  = spending.get("savings_pot", 0)
    investing    = spending.get("investing_pool", 0)
    streak       = spending.get("streak", 0)
    eff_limit    = daily_limit + carry_over
    left         = max(0, eff_limit - today_spent)
    bar          = progress_bar(today_spent, eff_limit)

    # Category breakdown
    cats: dict = {}
    for tx in txns:
        if tx["tx_type"] == "debit":
            cats[tx["category"]] = cats.get(tx["category"], 0) + tx["amount"]

    lines = [
        TOP,
        row(" DAILY SUMMARY"),
        row(f" {today}"),
        SEP,
        row(f" Budget:  \u20a6{eff_limit:,.0f}"),
        row(f" Spent:   \u20a6{today_spent:,.0f}"),
        row(f" Left:    \u20a6{left:,.0f}"),
        BLANK,
        row(f" {bar}"),
        SEP,
        row(f" Month total: \u20a6{total_spent:,.0f}"),
        row(f" Savings pot: \u20a6{savings_pot:,.0f}"),
        row(f" Invest pool: \u20a6{investing:,.0f}"),
    ]

    if streak > 0:
        lines.append(row(f" \U0001f525 Streak: {streak} day(s)"))

    if cats:
        lines.append(SEP)
        lines.append(row(" TOP CATEGORIES"))
        for cat, total in sorted(cats.items(), key=lambda x: -x[1])[:4]:
            lines.append(row(f"  {cat[:14]}: \u20a6{total:,.0f}"))

    lines.append(BOT)
    return "<pre>" + "\n".join(lines) + "</pre>"


def build_weekly_message(user_id: int) -> str:
    """Weekly report box — called by weekly_report.py."""
    from db import get_spending, get_budget, get_transactions_this_week
    from datetime import date

    budget  = get_budget(user_id)
    txns    = get_transactions_this_week(user_id)
    spending = get_spending(user_id)

    debits  = [t for t in txns if t["tx_type"] == "debit"]
    credits = [t for t in txns if t["tx_type"] == "credit"]

    total_debit  = sum(t["amount"] for t in debits)
    total_credit = sum(t["amount"] for t in credits)
    avg_daily    = total_debit / 7 if debits else 0

    cats: dict = {}
    for tx in debits:
        cats[tx["category"]] = cats.get(tx["category"], 0) + tx["amount"]

    savings = spending.get("savings_pot", 0)
    streak  = spending.get("streak", 0)

    lines = [
        TOP,
        row(" WEEKLY REPORT"),
        SEP,
        row(f" Spent:     \u20a6{total_debit:,.0f}"),
        row(f" Received:  \u20a6{total_credit:,.0f}"),
        row(f" Daily avg: \u20a6{avg_daily:,.0f}"),
        row(f" Tx count:  {len(txns)}"),
        SEP,
        row(f" Savings pot:\u20a6{savings:,.0f}"),
        row(f" Streak: {streak} day(s) on budget"),
    ]

    if cats:
        lines.append(SEP)
        lines.append(row(" SPENDING BY CATEGORY"))
        for cat, total in sorted(cats.items(), key=lambda x: -x[1])[:5]:
            lines.append(row(f"  {cat[:14]}: \u20a6{total:,.0f}"))

    lines.append(BOT)
    return "<pre>" + "\n".join(lines) + "</pre>"


# ─── Send helpers ─────────────────────────────────────────────────────────────

async def _send(chat_id: int, text: str):
    bot = Bot(token=TELEGRAM_TOKEN)
    await bot.send_message(chat_id=chat_id, text=text, parse_mode="HTML")


def notify(user_id: int, transaction: dict, budget_info: dict):
    """Synchronous wrapper — called from email_poller.py."""
    tx_type = transaction.get("type")
    if tx_type == "debit":
        msg = build_debit_message(transaction, budget_info)
    elif tx_type == "credit":
        msg = build_credit_message(transaction, budget_info)
    else:
        return
    asyncio.run(_send(user_id, msg))
    print(f"[notify] Sent {tx_type} alert to user {user_id}")


def send_summary(user_id: int):
    """Called by daily_summary.py."""
    msg = build_summary_message(user_id)
    asyncio.run(_send(user_id, msg))


def send_weekly(user_id: int):
    """Called by weekly_report.py."""
    msg = build_weekly_message(user_id)
    asyncio.run(_send(user_id, msg))
