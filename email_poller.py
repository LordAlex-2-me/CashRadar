"""
email_poller.py — Multi-user Gmail poller for BankReceiptTracker.

Replaces the old read_emails.py. Run by cron every 5 minutes.
Iterates all active users who have connected Gmail, polls each inbox,
parses transactions, updates budget, sends Telegram notification.

Cron entry:
    */5 * * * * cd /home/ubuntu/BankReceiptTracker && python3 email_poller.py >> /home/ubuntu/tracker.log 2>&1
"""

import base64
from datetime import datetime
from auth_manager import get_gmail_service
from parse_email import extract_transaction
from budget_tracker import process_transaction
from notifier import notify
from db import get_all_active_users

SENDER_FILTER = "from:alerts@firstbanknigeria.com is:unread"


def get_email_body(service, message_id: str) -> str:
    message = service.users().messages().get(
        userId="me", id=message_id, format="full"
    ).execute()
    payload = message["payload"]
    parts   = payload.get("parts", [])
    body    = ""
    if parts:
        for part in parts:
            if part["mimeType"] == "text/plain":
                data = part["body"].get("data", "")
                body = base64.urlsafe_b64decode(data).decode("utf-8")
                break
    else:
        data = payload["body"].get("data", "")
        body = base64.urlsafe_b64decode(data).decode("utf-8")
    return body


def mark_as_read(service, message_id: str):
    service.users().messages().modify(
        userId="me",
        id=message_id,
        body={"removeLabelIds": ["UNREAD"]},
    ).execute()


def poll_user(user: dict):
    user_id = user["user_id"]
    name    = user.get("first_name") or f"user {user_id}"
    print(f"[{datetime.now().strftime('%H:%M:%S')}] Polling {name} ({user.get('gmail_email', '?')})")

    service = get_gmail_service(user_id)
    if service is None:
        print(f"  → Gmail not connected or token expired for {name}")
        return

    result   = service.users().messages().list(userId="me", q=SENDER_FILTER).execute()
    messages = result.get("messages", [])

    if not messages:
        print(f"  → No new emails")
        return

    # Process oldest first (preserve correct balance order)
    messages = list(reversed(messages))
    print(f"  → {len(messages)} email(s) found")

    for msg in messages:
        msg_id = msg["id"]
        print(f"  → Processing email {msg_id}...")
        try:
            body        = get_email_body(service, msg_id)
            transaction = extract_transaction(body)

            if not transaction["amount"]:
                print(f"     Could not parse amount — skipping")
                mark_as_read(service, msg_id)
                continue

            budget_info = process_transaction(user_id, transaction)
            notify(user_id, transaction, budget_info)
            mark_as_read(service, msg_id)

        except Exception as e:
            print(f"     ERROR processing email {msg_id}: {e}")
            # Don't mark as read — will retry next cycle


def main():
    users = get_all_active_users()
    if not users:
        print("No active users with Gmail connected.")
        return

    print(f"Polling {len(users)} user(s)...")
    for user in users:
        try:
            poll_user(user)
        except Exception as e:
            print(f"  ERROR for user {user['user_id']}: {e}")


if __name__ == "__main__":
    main()
