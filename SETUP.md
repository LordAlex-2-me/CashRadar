# BankReceiptTracker — Setup Guide

## What changed from the old version

| Old | New |
|-----|-----|
| Single user only | Any number of users |
| JSON files (budget.json, spending.json) | SQLite database (tracker.db) |
| Hardcoded Telegram chat ID in config.py | Each user connects via /start |
| Gmail token stored as a file | Gmail token stored in database |
| telegram_notifier.py → HTML format | notifier.py → monospace box format |
| read_emails.py (one user) | email_poller.py (all users) |

---

## Server setup (one-time)

### 1. Pull the new code

```bash
cd /home/ubuntu
git clone https://github.com/LordAlex-2-me/BankReceiptTracker BankReceiptTracker
cd BankReceiptTracker
```

### 2. Install dependencies

```bash
pip3 install --break-system-packages \
    google-auth google-auth-oauthlib google-auth-httplib2 \
    google-api-python-client python-telegram-bot
```

### 3. Add credentials.json

Download your OAuth client credentials from Google Cloud Console
and copy to the project folder:

```bash
scp -i your-key.pem credentials.json ubuntu@140.238.84.15:/home/ubuntu/BankReceiptTracker/
```

### 4. Create config.py

```bash
nano /home/ubuntu/BankReceiptTracker/config.py
```

Paste:
```python
import os
TELEGRAM_TOKEN = "your-actual-bot-token-here"
```

### 5. Initialise the database

The database is created automatically when any script imports `db.py`.
You can force it with:

```bash
cd /home/ubuntu/BankReceiptTracker
python3 -c "import db; print('DB ready')"
```

This creates `tracker.db` in the project folder.

---

## Running the bot (keep-alive)

The bot needs to run continuously to respond to /start, /connect, etc.
Use a systemd service or tmux:

### Option A — systemd (recommended)

Create `/etc/systemd/system/banktracker-bot.service`:

```ini
[Unit]
Description=BankReceiptTracker Telegram Bot
After=network.target

[Service]
User=ubuntu
WorkingDirectory=/home/ubuntu/BankReceiptTracker
ExecStart=/usr/bin/python3 bot.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

Then:
```bash
sudo systemctl daemon-reload
sudo systemctl enable banktracker-bot
sudo systemctl start banktracker-bot
sudo journalctl -u banktracker-bot -f   # watch logs
```

### Option B — tmux (simpler)

```bash
tmux new -s bot
cd /home/ubuntu/BankReceiptTracker
python3 bot.py
# Ctrl+B then D to detach
```

---

## Cron jobs

Replace the old single-user cron with these three:

```bash
crontab -e
```

Add:
```
# Email polling — every 5 minutes
*/5 * * * * cd /home/ubuntu/BankReceiptTracker && python3 email_poller.py >> /home/ubuntu/tracker.log 2>&1

# Daily summary — 8AM Lagos time (7AM UTC)
0 7 * * * cd /home/ubuntu/BankReceiptTracker && python3 daily_summary.py >> /home/ubuntu/tracker.log 2>&1

# Weekly report — Sunday 9AM Lagos time (8AM UTC)
0 8 * * 0 cd /home/ubuntu/BankReceiptTracker && python3 weekly_report.py >> /home/ubuntu/tracker.log 2>&1
```

---

## User onboarding (what users do)

1. User finds your bot on Telegram and sends `/start`
2. Bot greets them and guides them to `/connect`
3. `/connect` shows a Google OAuth link — user opens it, signs in with
   their FirstBank Gmail, copies the code back to the bot
4. Bot confirms connection and prompts `/setbudget`
5. User sets their daily limit — done

From that point on, every transaction alert email triggers automatically.

---

## Files NOT in git (must be on server)

| File | Why |
|------|-----|
| `config.py` | Contains your bot token |
| `credentials.json` | Google OAuth client credentials |
| `tracker.db` | Auto-generated — all user data lives here |

---

## Migrating your existing data

Your existing `budget.json` and `spending.json` are no longer used.
To migrate your personal settings into the new database, run this once
after setup (replace values as needed):

```python
# run as: python3 migrate.py
from db import upsert_user, save_budget, seed_default_merchants, save_gmail_token
import json, os

MY_CHAT_ID = 123456789  # your Telegram chat ID

upsert_user(MY_CHAT_ID, first_name="Alex")
save_budget(MY_CHAT_ID, daily_limit=5000, savings_rate=0.10, investing_rate=0.05)
seed_default_merchants(MY_CHAT_ID)

# Copy your existing token.json into the DB
if os.path.exists("token.json"):
    token_data = open("token.json").read()
    save_gmail_token(MY_CHAT_ID, token_data, "your@gmail.com")
    print("Token migrated.")

print("Migration complete.")
```
