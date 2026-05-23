"""
db.py — SQLite database layer for BankReceiptTracker.

Single tracker.db file lives alongside the project.
All per-user state lives here instead of flat JSON files.

Tables:
  users        — registered Telegram users + Gmail OAuth tokens
  budgets      — per-user budget settings (daily limit, rates, etc.)
  merchants    — per-user keyword→category map
  spending     — per-user daily/monthly rolling state
  transactions — full transaction log (never deleted, used for reports)
"""

import sqlite3
import json
import os
from datetime import date, datetime

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "tracker.db")


def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")  # safe concurrent reads
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db():
    """Create all tables if they don't exist. Safe to call on every startup."""
    with get_conn() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS users (
                user_id       INTEGER PRIMARY KEY,   -- Telegram chat_id
                username      TEXT,
                first_name    TEXT,
                registered_at TEXT NOT NULL DEFAULT (datetime('now')),
                gmail_token   TEXT,                  -- JSON blob from google-auth
                gmail_email   TEXT,                  -- address being monitored
                active        INTEGER NOT NULL DEFAULT 1
            );

            CREATE TABLE IF NOT EXISTS budgets (
                user_id        INTEGER PRIMARY KEY REFERENCES users(user_id),
                daily_limit    REAL    NOT NULL DEFAULT 5000,
                savings_rate   REAL    NOT NULL DEFAULT 0.10,
                investing_rate REAL    NOT NULL DEFAULT 0.05,
                payday_threshold REAL  NOT NULL DEFAULT 50000,
                updated_at     TEXT    NOT NULL DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS merchants (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id    INTEGER NOT NULL REFERENCES users(user_id),
                keyword    TEXT    NOT NULL,
                category   TEXT    NOT NULL,
                UNIQUE(user_id, keyword)
            );

            CREATE TABLE IF NOT EXISTS spending (
                user_id        INTEGER PRIMARY KEY REFERENCES users(user_id),
                month          TEXT    NOT NULL,     -- e.g. '2026-05'
                day            TEXT    NOT NULL,     -- e.g. '2026-05-23'
                today_spent    REAL    NOT NULL DEFAULT 0,
                carry_over     REAL    NOT NULL DEFAULT 0,
                total_spent    REAL    NOT NULL DEFAULT 0,
                savings_pot    REAL    NOT NULL DEFAULT 0,
                investing_pool REAL    NOT NULL DEFAULT 0,
                streak         INTEGER NOT NULL DEFAULT 0,
                last_streak_date TEXT
            );

            CREATE TABLE IF NOT EXISTS transactions (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id     INTEGER NOT NULL REFERENCES users(user_id),
                tx_type     TEXT    NOT NULL,        -- 'debit' | 'credit'
                amount      REAL    NOT NULL,
                description TEXT,
                balance     REAL,
                category    TEXT,
                recorded_at TEXT    NOT NULL DEFAULT (datetime('now'))
            );
        """)


# ─── Users ───────────────────────────────────────────────────────────────────

def upsert_user(user_id: int, username: str = None, first_name: str = None):
    with get_conn() as conn:
        conn.execute("""
            INSERT INTO users (user_id, username, first_name)
            VALUES (?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
                username   = excluded.username,
                first_name = excluded.first_name
        """, (user_id, username, first_name))


def get_user(user_id: int):
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM users WHERE user_id = ?", (user_id,)
        ).fetchone()
    return dict(row) if row else None


def get_all_active_users():
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM users WHERE active = 1 AND gmail_token IS NOT NULL"
        ).fetchall()
    return [dict(r) for r in rows]


def save_gmail_token(user_id: int, token_json: str, email: str):
    with get_conn() as conn:
        conn.execute("""
            UPDATE users SET gmail_token = ?, gmail_email = ?
            WHERE user_id = ?
        """, (token_json, email, user_id))


# ─── Budgets ─────────────────────────────────────────────────────────────────

def get_budget(user_id: int) -> dict:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM budgets WHERE user_id = ?", (user_id,)
        ).fetchone()
    if row:
        return dict(row)
    # Return defaults if not set yet
    return {
        "user_id": user_id,
        "daily_limit": 5000,
        "savings_rate": 0.10,
        "investing_rate": 0.05,
        "payday_threshold": 50000,
    }


def save_budget(user_id: int, daily_limit: float = None, savings_rate: float = None,
                investing_rate: float = None, payday_threshold: float = None):
    current = get_budget(user_id)
    daily_limit       = daily_limit       if daily_limit       is not None else current["daily_limit"]
    savings_rate      = savings_rate      if savings_rate      is not None else current["savings_rate"]
    investing_rate    = investing_rate    if investing_rate     is not None else current["investing_rate"]
    payday_threshold  = payday_threshold  if payday_threshold  is not None else current["payday_threshold"]

    with get_conn() as conn:
        conn.execute("""
            INSERT INTO budgets (user_id, daily_limit, savings_rate, investing_rate, payday_threshold, updated_at)
            VALUES (?, ?, ?, ?, ?, datetime('now'))
            ON CONFLICT(user_id) DO UPDATE SET
                daily_limit      = excluded.daily_limit,
                savings_rate     = excluded.savings_rate,
                investing_rate   = excluded.investing_rate,
                payday_threshold = excluded.payday_threshold,
                updated_at       = excluded.updated_at
        """, (user_id, daily_limit, savings_rate, investing_rate, payday_threshold))


# ─── Merchants ───────────────────────────────────────────────────────────────

def get_merchants(user_id: int) -> dict:
    """Returns {keyword: category} dict for a user."""
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT keyword, category FROM merchants WHERE user_id = ?", (user_id,)
        ).fetchall()
    return {r["keyword"]: r["category"] for r in rows}


def save_merchant(user_id: int, keyword: str, category: str):
    with get_conn() as conn:
        conn.execute("""
            INSERT INTO merchants (user_id, keyword, category)
            VALUES (?, ?, ?)
            ON CONFLICT(user_id, keyword) DO UPDATE SET category = excluded.category
        """, (user_id, keyword.lower().strip(), category.strip()))


def seed_default_merchants(user_id: int):
    """Add sensible defaults for a new user."""
    defaults = {
        "shoprite": "Food",
        "chicken republic": "Food",
        "kfc": "Food",
        "domino": "Food",
        "uber": "Transport",
        "bolt": "Transport",
        "filling station": "Transport",
        "fuel": "Transport",
        "airtime": "Utilities",
        "data": "Utilities",
        "netflix": "Entertainment",
        "dstv": "Entertainment",
    }
    with get_conn() as conn:
        conn.executemany("""
            INSERT OR IGNORE INTO merchants (user_id, keyword, category)
            VALUES (?, ?, ?)
        """, [(user_id, kw, cat) for kw, cat in defaults.items()])


# ─── Spending state ───────────────────────────────────────────────────────────

def get_spending(user_id: int) -> dict:
    today = date.today()
    today_str = today.isoformat()
    month_str = today.strftime("%Y-%m")

    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM spending WHERE user_id = ?", (user_id,)
        ).fetchone()

    if not row:
        return _fresh_spending(user_id, today_str, month_str)

    data = dict(row)

    # New month → full reset
    if data["month"] != month_str:
        return _fresh_spending(user_id, today_str, month_str)

    # New day → carry over logic handled by budget_tracker before calling save
    return data


def _fresh_spending(user_id: int, today_str: str, month_str: str) -> dict:
    return {
        "user_id": user_id,
        "month": month_str,
        "day": today_str,
        "today_spent": 0.0,
        "carry_over": 0.0,
        "total_spent": 0.0,
        "savings_pot": 0.0,
        "investing_pool": 0.0,
        "streak": 0,
        "last_streak_date": None,
    }


def save_spending(data: dict):
    with get_conn() as conn:
        conn.execute("""
            INSERT INTO spending
                (user_id, month, day, today_spent, carry_over, total_spent,
                 savings_pot, investing_pool, streak, last_streak_date)
            VALUES
                (:user_id, :month, :day, :today_spent, :carry_over, :total_spent,
                 :savings_pot, :investing_pool, :streak, :last_streak_date)
            ON CONFLICT(user_id) DO UPDATE SET
                month          = excluded.month,
                day            = excluded.day,
                today_spent    = excluded.today_spent,
                carry_over     = excluded.carry_over,
                total_spent    = excluded.total_spent,
                savings_pot    = excluded.savings_pot,
                investing_pool = excluded.investing_pool,
                streak         = excluded.streak,
                last_streak_date = excluded.last_streak_date
        """, data)


# ─── Transactions ─────────────────────────────────────────────────────────────

def log_transaction(user_id: int, tx_type: str, amount: float,
                    description: str, balance: float, category: str):
    with get_conn() as conn:
        conn.execute("""
            INSERT INTO transactions (user_id, tx_type, amount, description, balance, category)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (user_id, tx_type, amount, description, balance, category))


def get_transactions_this_month(user_id: int) -> list:
    month_str = date.today().strftime("%Y-%m")
    with get_conn() as conn:
        rows = conn.execute("""
            SELECT * FROM transactions
            WHERE user_id = ? AND recorded_at LIKE ?
            ORDER BY recorded_at ASC
        """, (user_id, f"{month_str}%")).fetchall()
    return [dict(r) for r in rows]


def get_transactions_this_week(user_id: int) -> list:
    with get_conn() as conn:
        rows = conn.execute("""
            SELECT * FROM transactions
            WHERE user_id = ?
              AND date(recorded_at) >= date('now', '-6 days')
            ORDER BY recorded_at ASC
        """, (user_id,)).fetchall()
    return [dict(r) for r in rows]


# ─── Init on import ──────────────────────────────────────────────────────────
init_db()
