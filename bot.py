"""
bot.py — Telegram bot for CashRadar.

Handles user onboarding and commands. Runs as a long-running process
alongside the cron jobs.

Start it with:
    python3 bot.py

Commands:
    /start        — Welcome message + onboarding guide
    /connect      — Begin Gmail OAuth flow
    /setbudget    — Set daily spending limit
    /status       — Show today's spending status
    /summary      — On-demand daily summary
    /categories   — List spending categories
    /help         — Show all commands

Run as a systemd service or in a tmux session so it stays alive.
"""

import logging
from telegram import Update
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    ContextTypes, ConversationHandler, filters
)
from config import TELEGRAM_TOKEN
from db import upsert_user, get_user, save_budget, get_budget, get_spending, seed_default_merchants
from auth_manager import start_auth_flow, finish_auth_flow, has_connected_gmail
from notifier import build_summary_message

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)

# Conversation states
WAITING_AUTH_CODE  = 1
WAITING_BUDGET_AMT = 2


# ─── /start ──────────────────────────────────────────────────────────────────

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    upsert_user(user.id, user.username, user.first_name)
    seed_default_merchants(user.id)

    name = user.first_name or "there"
    msg = (
        f"👋 Hey {name}! Welcome to <b>CashRadar</b>.\n\n"
        "I monitor your FirstBank Nigeria email alerts and send you "
        "budget updates right here in Telegram — automatically, every 5 minutes.\n\n"
        "<b>To get started:</b>\n"
        "1️⃣ Run /connect to link your Gmail\n"
        "2️⃣ Run /setbudget to set your daily spend limit\n"
        "3️⃣ That's it! I'll notify you after every transaction.\n\n"
        "Type /help to see all commands."
    )
    await update.message.reply_text(msg, parse_mode="HTML")


# ─── /help ───────────────────────────────────────────────────────────────────

async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = (
        "<b>Available commands</b>\n\n"
        "/connect — Link your Gmail inbox\n"
        "/setbudget — Set your daily spending limit\n"
        "/status — Today's spending snapshot\n"
        "/summary — Full daily summary\n"
        "/categories — Your spending categories this month\n"
        "/help — This message\n\n"
        "<i>Transactions are checked automatically every 5 minutes.</i>"
    )
    await update.message.reply_text(msg, parse_mode="HTML")


# ─── /connect — Gmail OAuth flow ─────────────────────────────────────────────

async def connect_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id

    if has_connected_gmail(user_id):
        db_user = get_user(user_id)
        email   = db_user.get("gmail_email", "your Gmail")
        await update.message.reply_text(
            f"✅ Your Gmail is already connected ({email}).\n\n"
            "To reconnect with a different account, use /connect again."
        )
        # Still fall through to re-auth if they want

    try:
        auth_url = start_auth_flow(user_id)
    except FileNotFoundError:
        await update.message.reply_text(
            "⚠️ The bot isn't fully set up yet. "
            "The admin needs to add credentials.json to the server."
        )
        return ConversationHandler.END

    msg = (
        "Let's connect your Gmail inbox.\n\n"
        f"<b>Step 1:</b> Open this link in your browser:\n{auth_url}\n\n"
        "<b>Step 2:</b> Sign in with the Gmail that receives your FirstBank alerts.\n\n"
        "<b>Step 3:</b> Copy the code Google gives you and paste it here."
    )
    await update.message.reply_text(msg, parse_mode="HTML")
    return WAITING_AUTH_CODE


async def connect_receive_code(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id   = update.effective_user.id
    auth_code = update.message.text.strip()

    await update.message.reply_text("⏳ Connecting to Gmail...")

    try:
        email = finish_auth_flow(user_id, auth_code)
        await update.message.reply_text(
            f"✅ Connected! I'm now monitoring <b>{email}</b> for FirstBank alerts.\n\n"
            "Next: use /setbudget to set your daily spending limit.",
            parse_mode="HTML"
        )
    except Exception as e:
        await update.message.reply_text(
            f"❌ That didn't work: {e}\n\nTry /connect again from the beginning."
        )

    return ConversationHandler.END


# ─── /setbudget ───────────────────────────────────────────────────────────────

async def setbudget_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    current = get_budget(update.effective_user.id)
    await update.message.reply_text(
        f"Your current daily budget is <b>₦{current['daily_limit']:,.0f}</b>.\n\n"
        "Send me your new daily spending limit (numbers only, e.g. <code>8000</code>):",
        parse_mode="HTML"
    )
    return WAITING_BUDGET_AMT


async def setbudget_receive(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    text    = update.message.text.strip().replace(",", "").replace("₦", "")

    try:
        amount = float(text)
        if amount <= 0:
            raise ValueError
    except ValueError:
        await update.message.reply_text(
            "Please send a valid number, e.g. <code>8000</code>",
            parse_mode="HTML"
        )
        return WAITING_BUDGET_AMT

    save_budget(user_id, daily_limit=amount)
    await update.message.reply_text(
        f"✅ Daily budget set to <b>₦{amount:,.0f}</b>.\n\n"
        "I'll track your spending against this every day. "
        "Unused budget doesn't roll over fully — overspend carries forward instead.",
        parse_mode="HTML"
    )
    return ConversationHandler.END


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Cancelled.")
    return ConversationHandler.END


# ─── /status ─────────────────────────────────────────────────────────────────

async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id  = update.effective_user.id
    budget   = get_budget(user_id)
    spending = get_spending(user_id)

    eff_limit   = budget["daily_limit"] + spending.get("carry_over", 0)
    today_spent = spending.get("today_spent", 0)
    left        = max(0, eff_limit - today_spent)
    pct         = min(100, int((today_spent / eff_limit * 100))) if eff_limit > 0 else 0

    bar_w  = 18
    filled = int((pct / 100) * bar_w)
    bar    = "█" * filled + "░" * (bar_w - filled)

    msg = (
        f"<pre>"
        f"Today's snapshot\n"
        f"─────────────────────\n"
        f"Budget:  ₦{eff_limit:,.0f}\n"
        f"Spent:   ₦{today_spent:,.0f}\n"
        f"Left:    ₦{left:,.0f}\n"
        f"\n[{bar}] {pct}%\n"
        f"</pre>"
    )
    await update.message.reply_text(msg, parse_mode="HTML")


# ─── /summary ────────────────────────────────────────────────────────────────

async def summary(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    msg     = build_summary_message(user_id)
    await update.message.reply_text(msg, parse_mode="HTML")


# ─── /categories ─────────────────────────────────────────────────────────────

async def categories(update: Update, context: ContextTypes.DEFAULT_TYPE):
    from db import get_transactions_this_month
    user_id = update.effective_user.id
    txns    = get_transactions_this_month(user_id)
    debits  = [t for t in txns if t["tx_type"] == "debit"]

    if not debits:
        await update.message.reply_text("No transactions recorded this month yet.")
        return

    cats: dict = {}
    for tx in debits:
        cats[tx["category"]] = cats.get(tx["category"], 0) + tx["amount"]

    lines = ["<b>Spending by category this month</b>\n"]
    for cat, total in sorted(cats.items(), key=lambda x: -x[1]):
        lines.append(f"  {cat}: ₦{total:,.0f}")

    await update.message.reply_text("\n".join(lines), parse_mode="HTML")


# ─── App setup ────────────────────────────────────────────────────────────────

def main():
    app = Application.builder().token(TELEGRAM_TOKEN).build()

    # Gmail connect flow
    connect_handler = ConversationHandler(
        entry_points=[CommandHandler("connect", connect_start)],
        states={WAITING_AUTH_CODE: [MessageHandler(filters.TEXT & ~filters.COMMAND, connect_receive_code)]},
        fallbacks=[CommandHandler("cancel", cancel)],
    )

    # Set budget flow
    budget_handler = ConversationHandler(
        entry_points=[CommandHandler("setbudget", setbudget_start)],
        states={WAITING_BUDGET_AMT: [MessageHandler(filters.TEXT & ~filters.COMMAND, setbudget_receive)]},
        fallbacks=[CommandHandler("cancel", cancel)],
    )

    app.add_handler(CommandHandler("start",      start))
    app.add_handler(CommandHandler("help",       help_cmd))
    app.add_handler(CommandHandler("status",     status))
    app.add_handler(CommandHandler("summary",    summary))
    app.add_handler(CommandHandler("categories", categories))
    app.add_handler(connect_handler)
    app.add_handler(budget_handler)

    print("Bot is running...")
    app.run_polling()


if __name__ == "__main__":
    main()
