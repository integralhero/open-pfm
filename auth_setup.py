#!/usr/bin/env python3
"""One-time OAuth setup script.

Run this interactively (with a browser available) to generate token.json.
Once token.json exists the MCP server can refresh tokens without a browser.

Usage:
    python auth_setup.py
"""

from google_sheets_auth import CREDENTIALS_FILE, TOKEN_FILE, SCOPES

import os
import sys

from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from google_auth_oauthlib.flow import InstalledAppFlow


def main() -> None:
    creds = None

    if os.path.exists(TOKEN_FILE):
        creds = Credentials.from_authorized_user_file(TOKEN_FILE, SCOPES)

    if creds and creds.valid:
        print(f"Token already valid at {TOKEN_FILE} — nothing to do.")
        return

    if creds and creds.expired and creds.refresh_token:
        print("Refreshing expired token...")
        creds.refresh(Request())
    else:
        if not os.path.exists(CREDENTIALS_FILE):
            print(f"Error: credentials file not found at {CREDENTIALS_FILE}", file=sys.stderr)
            print("Download it from the Google Cloud Console and place it there.", file=sys.stderr)
            sys.exit(1)

        print("Opening browser for Google OAuth consent...")
        flow = InstalledAppFlow.from_client_secrets_file(CREDENTIALS_FILE, SCOPES)
        creds = flow.run_local_server(port=0)

    with open(TOKEN_FILE, "w") as f:
        f.write(creds.to_json())

    print(f"Token saved to {TOKEN_FILE}")
    print("You can now start the MCP server headlessly.")


if __name__ == "__main__":
    main()
