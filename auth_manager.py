"""
auth_manager.py — Per-user Gmail OAuth2 for BankReceiptTracker.

Each user's OAuth token is stored as a JSON blob in the users table.
The first-time auth flow produces a URL the user visits in their browser,
then pastes the auth code back to the bot. No local file or browser pop-up
needed on the server.

Usage:
    from auth_manager import get_gmail_service, start_auth_flow, finish_auth_flow
"""

import json
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from db import get_user, save_gmail_token

SCOPES = ["https://www.googleapis.com/auth/gmail.modify"]

# Path to your OAuth client credentials file (downloaded from Google Cloud Console).
# This file is NOT in git. One shared credentials.json for the whole app is fine —
# each user gets their own token stored in the DB.
import os
CREDENTIALS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "credentials.json")

# In-memory store for pending OAuth flows keyed by user_id.
# These are short-lived (user completes auth within minutes).
_pending_flows: dict[int, Flow] = {}


def start_auth_flow(user_id: int) -> str:
    """
    Begin OAuth flow for a user. Returns the authorisation URL they must visit.
    Stores the flow object in memory until finish_auth_flow() is called.
    """
    flow = Flow.from_client_secrets_file(
        CREDENTIALS_FILE,
        scopes=SCOPES,
        redirect_uri="urn:ietf:wg:oauth:2.0:oob",  # out-of-band: user pastes code back
    )
    auth_url, _ = flow.authorization_url(
        access_type="offline",
        include_granted_scopes="true",
        prompt="consent",  # force refresh_token even if previously authorised
    )
    _pending_flows[user_id] = flow
    return auth_url


def finish_auth_flow(user_id: int, auth_code: str) -> str:
    """
    Complete OAuth flow using the code the user pasted.
    Fetches the token, discovers the Gmail address, saves both to DB.
    Returns the Gmail address on success, raises on failure.
    """
    flow = _pending_flows.pop(user_id, None)
    if flow is None:
        raise ValueError("No pending auth flow for this user. Use /connect first.")

    flow.fetch_token(code=auth_code.strip())
    creds = flow.credentials

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
