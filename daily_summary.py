"""
daily_summary.py — Send daily budget summary to all active users.

Cron entry (7AM UTC = 8AM Lagos time):
    0 7 * * * cd /home/ubuntu/CashRadar && python3 daily_summary.py >> /home/ubuntu/tracker.log 2>&1
"""

from db import get_all_active_users
from notifier import send_summary
from datetime import datetime

def main():
    users = get_all_active_users()
    print(f"[{datetime.now().strftime('%H:%M:%S')}] Sending daily summary to {len(users)} user(s)")
    for user in users:
        try:
            send_summary(user["user_id"])
            print(f"  → Sent to user {user['user_id']}")
        except Exception as e:
            print(f"  ERROR for user {user['user_id']}: {e}")

if __name__ == "__main__":
    main()
