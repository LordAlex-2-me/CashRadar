"""
auth_manager.py — Per-user Gmail OAuth2 for BankReceiptTracker.

Each user's OAuth token is stored as a JSON blob in the users table.
Auth flow: bot starts a local HTTP server on a random port, sends the user
a Google authorisation URL, Google redirects back to localhost with the code,
the local server captures it automatically. User just clicks the link —
no copy-pasting a code.

Note: the user must run /connect from a device where they can open a browser
that can reach localhost on their machine. For most users on desktop/laptop
this works seamlessly. On mobile they should open the link on a desktop.

Usage:
    from auth_manager import get_gmail_service, start_auth_flow, finish_auth_flow
"""

import json
import threading
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from db import get_user, save_gmail_token

SCOPES = ["https://www.googleapis.com/auth/gmail.modify"]

import os
CREDENTIALS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "credentials.json")

# In-memory store for pending flows keyed by user_id.
_pending_flows: dict[int, InstalledAppFlow] = {}
# Stores completed tokens keyed by user_id until finish_auth_flow() picks them up.
_completed_tokens: dict[int, tuple] = {}


def start_auth_flow(user_id: int) -> str:
    """
    Begin OAuth flow for a user.
    Starts a local HTTP server on a random port, returns the auth URL.
    Google redirects back to that local server automatically after the user approves.
    The token is captured in the background and stored via finish_auth_flow().
    """
    flow = InstalledAppFlow.from_client_secrets_file(CREDENTIALS_FILE, SCOPES)

    # Run the local server in a background thread so bot.py doesn't block.
    def _run():
        creds = flow.run_local_server(
            port=0,               # pick any free port
            open_browser=False,   # don't try to open browser on the server
            success_message=(
                "✅ Gmail connected! You can close this tab and return to Telegram."
            ),
        )
        _completed_tokens[user_id] = creds

    thread = threading.Thread(target=_run, daemon=True)
    thread.start()
    _pending_flows[user_id] = (flow, thread)

    # Give the local server a moment to start and generate its redirect URI
    import time
    time.sleep(1)

    # Build the auth URL from the flow's redirect URI (set by run_local_server)
    auth_url, _ = flow.authorization_url(
        access_type="offline",
        prompt="consent",
    )
    return auth_url


def finish_auth_flow(user_id: int) -> str:
    """
    Called after the background thread has captured the token.
    Polls briefly for the completed token, saves it to DB.
    Returns the Gmail address on success, raises ValueError if token not ready.
    """
    import time
    # Wait up to 3 minutes for the user to complete auth in their browser
    for _ in range(180):
        if user_id in _completed_tokens:
            break
        time.sleep(1)

    creds = _completed_tokens.pop(user_id, None)
    _pending_flows.pop(user_id, None)

    if creds is None:
        raise ValueError(
            "Auth timed out or wasn't completed. Please use /connect to try again."
        )

    service = build("gmail", "v1", credentials=creds)
    profile = service.users().getProfile(userId="me").execute()
    email   = profile.get("emailAddress", "unknown")

    save_gmail_token(user_id, creds.to_json(), email)
    return email


def finish_auth_flow(user_id: int, auth_code: str = None) -> str:
    """
    Compatibility wrapper — auth_code param is ignored (token captured automatically).
    Kept so bot.py doesn't need changes.
    """
    import time
    for _ in range(180):
        if user_id in _completed_tokens:
            break
        time.sleep(1)

    creds = _completed_tokens.pop(user_id, None)
    _pending_flows.pop(user_id, None)

    if creds is None:
        raise ValueError(
            "Auth timed out. Please use /connect to try again."
        )

    service = build("gmail", "v1", credentials=creds)
    profile = service.users().getProfile(userId="me").execute()
    email   = profile.get("emailAddress", "unknown")

    save_gmail_token(user_id, creds.to_json(), email)
    return email

    # Discover which Gmail address this token belongs to
    service = build("gmail", "v1", credentials=creds)
    profile = service.users().getProfile(userId="me").execute()
    email = profile.get("emailAddress", "unknown")

    save_gmail_token(user_id, creds.to_json(), email)
    return email


def get_gmail_service(user_id: int):
    """
    Returns an authorised Gmail API service for a user.
    Automatically refreshes expired tokens and saves the updated token to DB.
    Returns None if the user hasn't connected Gmail yet.
    """
    user = get_user(user_id)
    if not user or not user.get("gmail_token"):
        return None

    creds = Credentials.from_authorized_user_info(
        json.loads(user["gmail_token"]), SCOPES
    )

    if not creds.valid:
        if creds.expired and creds.refresh_token:
            creds.refresh(Request())
            # Persist refreshed token
            save_gmail_token(user_id, creds.to_json(), user.get("gmail_email", ""))
        else:
            # Token is broken — user needs to re-connect
            return None

    return build("gmail", "v1", credentials=creds)


def has_connected_gmail(user_id: int) -> bool:
    user = get_user(user_id)
    return bool(user and user.get("gmail_token"))
