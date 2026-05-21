"""Google OAuth credentials for Tecman.

En producción (Render): lee GOOGLE_TOKEN_JSON y GOOGLE_CLIENT_SECRET_JSON como env vars.
En local: lee token.json y client_secret.json desde google_calendar/ del workspace.
"""

import os
import json
import tempfile
from pathlib import Path

from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from googleapiclient.discovery import build

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/calendar",
]

_LOCAL_BASE = Path(__file__).resolve().parent.parent / "google_calendar"


def get_creds() -> Credentials:
    token_json = os.environ.get("GOOGLE_TOKEN_JSON")
    if token_json:
        creds = Credentials.from_authorized_user_info(json.loads(token_json), SCOPES)
        if creds.expired and creds.refresh_token:
            creds.refresh(Request())
        return creds

    # Fallback local
    token_path = _LOCAL_BASE / "token.json"
    if not token_path.exists():
        raise RuntimeError("No se encontró token.json ni GOOGLE_TOKEN_JSON env var.")
    creds = Credentials.from_authorized_user_file(str(token_path), SCOPES)
    if creds.expired and creds.refresh_token:
        creds.refresh(Request())
        token_path.write_text(creds.to_json())
    return creds


def gmail():
    return build("gmail", "v1", credentials=get_creds())


def sheets():
    return build("sheets", "v4", credentials=get_creds())


def calendar():
    return build("calendar", "v3", credentials=get_creds())
