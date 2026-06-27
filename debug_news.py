#!/usr/bin/env python3
"""
debug_news.py — Diagnostic tool for the Morning Brief news section.

Shows EXACTLY what text Claude receives as "news" before any curation:
- Lists every email currently labelled "News" in the last 18h
- Runs each through the same HTML-to-text extractor the real brief uses
- Writes the full raw extracted text to debug_news_output.txt
- Prints a short summary to the terminal

This does NOT call Claude and does NOT send any email. Read-only.

USAGE (run locally, same folder as your token files):
    python3 debug_news.py

Requires the same Google token you use for the brief. It looks for the token in
this order:
    1. Environment variable GMAIL_TOKEN_JSON (the GitHub secret contents), or
    2. A local file gmail_token.json (created by get_tokens.py)

You can also change HOURS_BACK below to widen/narrow the time window.
"""

import os
import json
import base64
import datetime
import re
import html
from html.parser import HTMLParser

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

# ── Config ────────────────────────────────────────────────────────────────────
HOURS_BACK = 18          # same window as the real brief
try:
    import config
    LABEL = config.NEWS_LABEL
except ModuleNotFoundError:
    LABEL = "News"       # fallback if config.py is absent
MAX_RESULTS = 6          # same cap as the real brief
OUTPUT_FILE = "debug_news_output.txt"
PER_NEWSLETTER_CAP = 15000  # same truncation the real brief applies


# ── Google Auth (mirrors morning_brief.py) ────────────────────────────────────
def get_gmail_service():
    # Prefer the env var (GitHub secret); fall back to a local token file.
    token_raw = os.environ.get("GMAIL_TOKEN_JSON")
    if not token_raw:
        if os.path.exists("gmail_token.json"):
            with open("gmail_token.json") as f:
                token_raw = f.read()
        else:
            raise SystemExit(
                "No Gmail token found. Set GMAIL_TOKEN_JSON env var, or put "
                "gmail_token.json (from get_tokens.py) in this folder."
            )
    token_data = json.loads(token_raw)
    creds = Credentials(
        token=token_data["token"],
        refresh_token=token_data["refresh_token"],
        token_uri="https://oauth2.googleapis.com/token",
        client_id=token_data["client_id"],
        client_secret=token_data["client_secret"],
        scopes=token_data["scopes"],
    )
    return build("gmail", "v1", credentials=creds)


# ── HTML-to-text extractor (identical to morning_brief.py) ────────────────────
class _TextExtractor(HTMLParser):
    """Strips HTML to readable text. Keeps a link's URL ONLY if the link has real
    anchor text — drops bare image/icon/spacer tracking links that eat the budget."""
    def __init__(self):
        super().__init__()
        self.parts = []
        self._current_href = None
        self._in_link = False
        self._link_had_text = False
        self._skip = False

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style", "head"):
            self._skip = True
        if tag == "a":
            self._current_href = None
            self._in_link = True
            self._link_had_text = False
            for name, val in attrs:
                if name == "href":
                    self._current_href = val

    def handle_endtag(self, tag):
        if tag in ("script", "style", "head"):
            self._skip = False
        if tag == "a":
            if self._current_href and self._link_had_text and _is_useful_url(self._current_href):
                self.parts.append(f" ({self._current_href})")
            self._current_href = None
            self._in_link = False
            self._link_had_text = False
        if tag in ("td", "th"):
            self.parts.append(" | ")
        if tag in ("p", "div", "br", "tr", "li", "h1", "h2", "h3"):
            self.parts.append("\n")

    def handle_data(self, data):
        if not self._skip:
            text = data.strip()
            if text:
                if self._in_link:
                    self._link_had_text = True
                self.parts.append(text + " ")

    def get_text(self):
        out = "".join(self.parts)
        out = html.unescape(out)
        out = re.sub(r"(\s*\|\s*){2,}", " ", out)
        out = re.sub(r"^\s*\|\s*$", "", out, flags=re.MULTILINE)
        lines = [ln.rstrip() for ln in out.split("\n")]
        lines = [ln for ln in lines if ln.strip() and ln.strip() != "|"]
        out = "\n".join(lines)
        out = re.sub(r"\n{3,}", "\n\n", out)
        out = re.sub(r"[ \t]{2,}", " ", out)
        return out.strip()


_URL_BLOCKLIST = (
    "unsubscribe", "/preferences", "privacy", "terms", "myaccount",
    "manage-email", "email-preferences", "/app", "apps.apple", "play.google",
    "facebook.com", "twitter.com", "x.com/", "instagram.com", "linkedin.com",
    "tiktok.com", "youtube.com", "view-in-browser", "viewinbrowser", "/account",
)


def _is_useful_url(url: str) -> bool:
    low = url.lower()
    return not any(bad in low for bad in _URL_BLOCKLIST)


def _decode_email_body(payload) -> str:
    """Recursively pull the HTML (or plain text) body out of a Gmail message payload."""
    body_html = ""
    body_text = ""

    def walk(part):
        nonlocal body_html, body_text
        mime = part.get("mimeType", "")
        data = part.get("body", {}).get("data")
        if data:
            decoded = base64.urlsafe_b64decode(data).decode("utf-8", errors="ignore")
            if mime == "text/html":
                body_html += decoded
            elif mime == "text/plain":
                body_text += decoded
        for sub in part.get("parts", []) or []:
            walk(sub)

    walk(payload)

    if body_html:
        parser = _TextExtractor()
        parser.feed(body_html)
        return parser.get_text()
    return body_text.strip()


# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    service = get_gmail_service()
    since = int((datetime.datetime.now() - datetime.timedelta(hours=HOURS_BACK)).timestamp())
    query = f"label:{LABEL} after:{since}"

    print(f"Query: {query}")
    print(f"(emails labelled '{LABEL}' from the last {HOURS_BACK}h)\n")

    results = service.users().messages().list(
        userId="me", q=query, maxResults=MAX_RESULTS,
    ).execute()
    messages = results.get("messages", [])

    if not messages:
        print("No matching emails. (The real brief would fall back to a web search.)")
        return

    print(f"Found {len(messages)} email(s). Extracting...\n")

    out_chunks = []
    out_chunks.append(f"DEBUG NEWS DUMP — generated {datetime.datetime.now().isoformat()}")
    out_chunks.append(f"Query: {query}")
    out_chunks.append(f"{len(messages)} email(s) found\n")
    out_chunks.append("=" * 80)

    for i, msg in enumerate(messages, 1):
        detail = service.users().messages().get(
            userId="me", id=msg["id"], format="full",
        ).execute()
        headers = {h["name"]: h["value"] for h in detail["payload"]["headers"]}
        sender = headers.get("From", "Unknown")
        subject = headers.get("Subject", "(no subject)")
        date = headers.get("Date", "?")

        full_body = _decode_email_body(detail["payload"])
        capped_body = full_body[:PER_NEWSLETTER_CAP]
        was_truncated = len(full_body) > PER_NEWSLETTER_CAP

        # Terminal summary
        print(f"[{i}] {sender}")
        print(f"    Subject: {subject}")
        print(f"    Date:    {date}")
        print(f"    Extracted length: {len(full_body)} chars"
              + (f"  (TRUNCATED to {PER_NEWSLETTER_CAP} for Claude)" if was_truncated else ""))
        print()

        # Full dump to file
        out_chunks.append(f"\n[{i}] FROM: {sender}")
        out_chunks.append(f"    SUBJECT: {subject}")
        out_chunks.append(f"    DATE: {date}")
        out_chunks.append(f"    FULL EXTRACTED LENGTH: {len(full_body)} chars")
        out_chunks.append(f"    TRUNCATED FOR CLAUDE: {'yes — Claude only sees first 12000 chars' if was_truncated else 'no'}")
        out_chunks.append("-" * 80)
        out_chunks.append("WHAT CLAUDE ACTUALLY RECEIVES (after 12000-char cap):")
        out_chunks.append("-" * 80)
        out_chunks.append(capped_body)
        if was_truncated:
            out_chunks.append("\n... [TRUNCATED — the text below is in the email but NOT sent to Claude] ...\n")
            out_chunks.append(full_body[PER_NEWSLETTER_CAP:])
        out_chunks.append("\n" + "=" * 80)

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        f.write("\n".join(out_chunks))

    print(f"✅ Full extracted text written to: {OUTPUT_FILE}")
    print("   Open it to see exactly what Claude receives (and what gets truncated).")


if __name__ == "__main__":
    main()
