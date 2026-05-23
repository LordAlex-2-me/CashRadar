# BankReceiptTracker

Automatically monitors your FirstBank Nigeria email alerts and sends you budget updates on Telegram — after every single transaction.

```
┌──────────────────────────────┐
│ DEBIT ALERT                  │
├──────────────────────────────┤
│ Date:    23 May 2026         │
│ Time:    14:42               │
│ Amount:  ₦4,200              │
│ Category:Food                │
│ Note: Lunch at KFC           │
├──────────────────────────────┤
│ Spent:  ₦12,500              │
│ Left:   ₦17,500              │
│                              │
│ [████████░░░░░░░░░░] 42%     │
│ █ spent  ░ remaining         │
└──────────────────────────────┘
```

---

## What it does

- Checks your Gmail inbox every 5 minutes for FirstBank alerts
- Parses the transaction amount, type, and narration
- Tracks your daily budget and carry-over
- Categorises spending by merchant (Food, Transport, Utilities, etc.)
- Sends a formatted Telegram message after every debit and credit
- Sends an 8AM daily summary and a Sunday weekly report
- Supports multiple users — anyone can connect their own Gmail

---

## How it works

```
FirstBank sends alert email to Gmail
         ↓
Oracle Cloud VM checks inbox every 5 mins
         ↓
Parses transaction → updates budget → sends Telegram message
         ↓
Email marked as read (never processed twice)
```

---

## Getting started (for users)

1. Find the bot on Telegram and send `/start`
2. Run `/connect` — the bot gives you a link to authorise your Gmail
3. Run `/setbudget` — set your daily spending limit (e.g. `8000`)
4. Done. The bot handles everything from here

### Bot commands

| Command | What it does |
|---------|-------------|
| `/start` | Welcome message and setup guide |
| `/connect` | Link your Gmail inbox |
| `/setbudget` | Set your daily spending limit |
| `/status` | Quick snapshot of today's spending |
| `/summary` | Full daily summary on demand |
| `/categories` | Spending breakdown by category this month |
| `/help` | List all commands |

---

## Self-hosting

### Requirements

- A Linux server (Oracle Cloud Always Free works well — 1GB RAM is enough)
- Python 3.10+
- A Telegram bot token from [@BotFather](https://t.me/BotFather)
- A Google Cloud project with the Gmail API enabled and an OAuth client credentials file

### 1. Clone the repo

```bash
git clone https://github.com/LordAlex-2-me/BankReceiptTracker
cd BankReceiptTracker
```

### 2. Install dependencies

```bash
pip3 install google-auth google-auth-oauthlib google-auth-httplib2 \
             google-api-python-client python-telegram-bot
```

### 3. Add your credentials

**config.py** (never committed — create this manually):
```python
TELEGRAM_TOKEN = "your-bot-token-here"
```

**credentials.json** — download from Google Cloud Console (OAuth 2.0 client, Desktop app type) and place in the project folder.

### 4. Start the bot

```bash
python3 bot.py
```

Run this as a systemd service or in a tmux session so it stays alive. See [SETUP.md](SETUP.md) for the full systemd config.

### 5. Add cron jobs

```bash
crontab -e
```

```
# Poll Gmail every 5 minutes
*/5 * * * * cd /home/ubuntu/BankReceiptTracker && python3 email_poller.py >> /home/ubuntu/tracker.log 2>&1

# Daily summary at 8AM Lagos time
0 7 * * * cd /home/ubuntu/BankReceiptTracker && python3 daily_summary.py >> /home/ubuntu/tracker.log 2>&1

# Weekly report Sunday 9AM Lagos time
0 8 * * 0 cd /home/ubuntu/BankReceiptTracker && python3 weekly_report.py >> /home/ubuntu/tracker.log 2>&1
```

---

## File structure

```
BankReceiptTracker/
├── bot.py              # Telegram bot — commands and onboarding
├── email_poller.py     # Cron script — polls Gmail for all users
├── parse_email.py      # Regex parser for FirstBank email format
├── budget_tracker.py   # Budget logic — categorisation, carry-over, streaks
├── notifier.py         # Formats and sends Telegram messages
├── auth_manager.py     # Per-user Gmail OAuth — tokens stored in DB
├── db.py               # SQLite schema and all database helpers
├── daily_summary.py    # Cron script — 8AM daily summary
├── weekly_report.py    # Cron script — Sunday weekly report
├── config.py           # Your bot token (NOT in git — create manually)
├── credentials.json    # Google OAuth credentials (NOT in git)
└── tracker.db          # Auto-generated database (NOT in git)
```

---

## What's stored

All data lives in a single `tracker.db` SQLite file on your server:

- User Telegram IDs and Gmail OAuth tokens
- Per-user budget settings and merchant category map
- Daily and monthly spending state
- Full transaction history

No data leaves your server other than the Telegram messages you receive.

---

## Notes

- Built for **FirstBank Nigeria** alert emails. The email parser (`parse_email.py`) targets their specific format — other banks would need a different parser.
- The app uses Gmail's **modify** scope (not delete) — it only marks emails as read, never deletes them.
- OAuth tokens are refreshed automatically. Users only need to `/connect` once.
- Python 3.10 works fine. There is a non-breaking FutureWarning from `google-api-core` — upgrade to Python 3.11 before October 2026 when 3.10 support is dropped.

---

## Planned features

- Smart merchant memory — bot asks for category when a merchant is unrecognised, saves it permanently
- Payday detection — large credits reset the monthly cycle and auto-allocate savings
- Budget health score (0–100)
- `/summary week` and `/summary month` breakdowns