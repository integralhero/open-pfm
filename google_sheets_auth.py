"""Google Sheets authentication and service construction."""

import base64
import json
import os

from dotenv import load_dotenv
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google.oauth2 import service_account
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

load_dotenv()

SCOPES = ['https://www.googleapis.com/auth/spreadsheets']

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
CREDENTIALS_FILE = os.getenv('GOOGLE_CREDENTIALS_FILE', os.path.join(SCRIPT_DIR, 'credentials.json'))
TOKEN_FILE = os.getenv('GOOGLE_TOKEN_FILE', os.path.join(SCRIPT_DIR, 'token.json'))
SERVICE_ACCOUNT_FILE = os.getenv('GOOGLE_SERVICE_ACCOUNT_FILE', '')
SERVICE_ACCOUNT_JSON_B64 = os.getenv('GOOGLE_SERVICE_ACCOUNT_JSON_B64', '')


def create_sheets_service():
    """Authenticate with Google Sheets API and return an authenticated service.

    Tries authentication strategies in order:
    1. Base64-encoded service account JSON (GOOGLE_SERVICE_ACCOUNT_JSON_B64)
    2. Service account file path (GOOGLE_SERVICE_ACCOUNT_FILE)
    3. OAuth user credentials (token.json / credentials.json)
    """
    creds = None

    if SERVICE_ACCOUNT_JSON_B64:
        info = json.loads(base64.b64decode(SERVICE_ACCOUNT_JSON_B64))
        creds = service_account.Credentials.from_service_account_info(
            info, scopes=SCOPES
        )
    elif SERVICE_ACCOUNT_FILE and os.path.exists(SERVICE_ACCOUNT_FILE):
        creds = service_account.Credentials.from_service_account_file(
            SERVICE_ACCOUNT_FILE, scopes=SCOPES
        )
    else:
        if os.path.exists(TOKEN_FILE):
            creds = Credentials.from_authorized_user_file(TOKEN_FILE, SCOPES)

        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())
            else:
                if not os.path.exists(CREDENTIALS_FILE):
                    raise FileNotFoundError(
                        f"No credentials found. Provide GOOGLE_SERVICE_ACCOUNT_FILE "
                        f"for headless use, or '{CREDENTIALS_FILE}' for OAuth flow."
                    )
                flow = InstalledAppFlow.from_client_secrets_file(CREDENTIALS_FILE, SCOPES)
                creds = flow.run_local_server(port=0)

            with open(TOKEN_FILE, 'w') as token:
                token.write(creds.to_json())

    return build('sheets', 'v4', credentials=creds)
