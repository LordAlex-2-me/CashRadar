"""
weekly_report.py — Send weekly spending report to all active users.

Cron entry (8AM UTC Sunday = 9AM Lagos time):
    0 8 * * 0 cd /home/ubuntu/BankReceiptTracker && python3 weekly_report.py >> /home/ubuntu/tracker.log 2>&1
"""

from db import get_all_active_users
from notifier import send_weekly
from datetime import datetime

def main():
    users = get_all_active_users()
    print(f"[{datetime.now().strftime('%H:%M:%S')}] Sending weekly report to {len(users)} user(s)")
    for user in users:
        try:
            send_weekly(user["user_id"])
            print(f"  → Sent to user {user['user_id']}")
        except Exception as e:
            print(f"  ERROR for user {user['user_id']}: {e}")

if __name__ == "__main__":
    main()
