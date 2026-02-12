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

SCOPES = ['https://www.googleapis.com/auth/spreadsheets']

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

# Load .env from the project directory, not CWD (which may differ when
# launched by Claude Desktop or other MCP hosts).
load_dotenv(os.path.join(SCRIPT_DIR, '.env'))


def _resolve_path(env_value: str, default_name: str) -> str:
    """Return an absolute path, resolving relative paths against SCRIPT_DIR."""
    path = env_value or default_name
    if not os.path.isabs(path):
        return os.path.join(SCRIPT_DIR, path)
    return path


CREDENTIALS_FILE = _resolve_path(os.getenv('GOOGLE_CREDENTIALS_FILE', ''), 'credentials.json')
TOKEN_FILE = _resolve_path(os.getenv('GOOGLE_TOKEN_FILE', ''), 'token.json')
SERVICE_ACCOUNT_FILE = os.getenv('GOOGLE_SERVICE_ACCOUNT_FILE', '')
SERVICE_ACCOUNT_JSON_B64 = os.getenv('GOOGLE_SERVICE_ACCOUNT_JSON_B64', '')


def _browser_available() -> bool:
    """Return True if a web browser can likely be opened."""
    import webbrowser
    try:
        browser = webbrowser.get()
        return browser is not None
    except webbrowser.Error:
        return False


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
        # CREDENTIALS_FILE may be either a service-account key or an OAuth
        # client-secrets file.  Detect the type so the right flow is used.
        if os.path.exists(CREDENTIALS_FILE):
            with open(CREDENTIALS_FILE) as f:
                creds_data = json.load(f)
            if creds_data.get('type') == 'service_account':
                creds = service_account.Credentials.from_service_account_file(
                    CREDENTIALS_FILE, scopes=SCOPES
                )
                return build('sheets', 'v4', credentials=creds)

        # OAuth flow: try cached token first.
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
                # run_local_server needs a browser.  When running headless
                # (e.g. as an MCP server inside Claude Desktop) the browser
                # won't be available.  Detect this early and give a helpful
                # message instead of a cryptic socket/browser error.
                if os.getenv('MCP_TRANSPORT') or not _browser_available():
                    raise RuntimeError(
                        f"OAuth requires a browser but the server appears to be "
                        f"running headless. Run 'python {os.path.join(SCRIPT_DIR, 'auth_setup.py')}' "
                        f"once to generate {TOKEN_FILE}, then restart the server."
                    )
                creds = flow.run_local_server(port=0)

            with open(TOKEN_FILE, 'w') as token:
                token.write(creds.to_json())

    return build('sheets', 'v4', credentials=creds)
