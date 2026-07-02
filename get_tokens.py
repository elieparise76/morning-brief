#!/usr/bin/env python3
"""
One-time script — run locally to authorize Google access.
This opens a browser, you log in, and it saves token files
that you then paste into GitHub Secrets.

Run: python get_tokens.py
"""

import json
from google_auth_oauthlib.flow import InstalledAppFlow

GMAIL_SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.send",
]

GCAL_SCOPES = [
    "https://www.googleapis.com/auth/calendar.readonly",
]


def get_token(scopes, output_file, credentials_file="credentials.json"):
    flow = InstalledAppFlow.from_client_secrets_file(credentials_file, scopes)
    creds = flow.run_local_server(port=0)

    token_data = {
        "token": creds.token,
        "refresh_token": creds.refresh_token,
        "token_uri": creds.token_uri,
        "client_id": creds.client_id,
        "client_secret": creds.client_secret,
        "scopes": list(creds.scopes),
    }

    with open(output_file, "w") as f:
        json.dump(token_data, f, indent=2)

    print(f"✓ Saved {output_file}")
    print(f"  → Copy the contents of this file into the GitHub Secret.")


if __name__ == "__main__":
    print("=== Gmail authorization ===")
    print("A browser window will open. Log in and grant access.\n")
    get_token(GMAIL_SCOPES, "gmail_token.json")

    print("\n=== Google Calendar authorization ===")
    print("A browser window will open again.\n")
    get_token(GCAL_SCOPES, "gcal_token.json")

    print("\n✅ Done. Add gmail_token.json and gcal_token.json as GitHub Secrets.")
    print("   Do NOT commit these files to your repo.")
