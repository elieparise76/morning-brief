#!/usr/bin/env python3
"""
Morning Brief — Élie
Runs via GitHub Actions at 7:30 AM ET on weekdays.
Pulls weather, calendar, Gmail, and news via Claude + APIs, then emails the result.
"""

import os
import json
import base64
import datetime
import re
import html
from html.parser import HTMLParser
import pytz
import requests
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import anthropic
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

# ── Config ────────────────────────────────────────────────────────────────────
MONTREAL_TZ = pytz.timezone("America/Toronto")
OPENWEATHER_API_KEY = os.environ.get("OPENWEATHER_API_KEY", "")
ANTHROPIC_API_KEY = os.environ["ANTHROPIC_API_KEY"]
RECIPIENT_EMAIL = os.environ["RECIPIENT_EMAIL"]


# ── Google Auth ───────────────────────────────────────────────────────────────
def get_gmail_service():
    token_data = json.loads(os.environ["GMAIL_TOKEN_JSON"])
    creds = Credentials(
        token=token_data["token"],
        refresh_token=token_data["refresh_token"],
        token_uri="https://oauth2.googleapis.com/token",
        client_id=token_data["client_id"],
        client_secret=token_data["client_secret"],
        scopes=token_data["scopes"],
    )
    return build("gmail", "v1", credentials=creds)


def get_calendar_service():
    token_data = json.loads(os.environ["GCAL_TOKEN_JSON"])
    creds = Credentials(
        token=token_data["token"],
        refresh_token=token_data["refresh_token"],
        token_uri="https://oauth2.googleapis.com/token",
        client_id=token_data["client_id"],
        client_secret=token_data["client_secret"],
        scopes=token_data["scopes"],
    )
    return build("calendar", "v3", credentials=creds)


# ── Data Fetchers ─────────────────────────────────────────────────────────────
def fetch_weather() -> str:
    """Fetch current weather for Montréal via OpenWeatherMap."""
    if not OPENWEATHER_API_KEY:
        return "Weather API key not configured."
    url = (
        f"https://api.openweathermap.org/data/2.5/forecast"
        f"?q=Montreal,CA&appid={OPENWEATHER_API_KEY}&units=metric&cnt=8"
    )
    try:
        r = requests.get(url, timeout=10)
        r.raise_for_status()
        data = r.json()
        items = data["list"]
        # Current + today range
        lines = []
        for item in items:
            dt = datetime.datetime.fromtimestamp(item["dt"], tz=MONTREAL_TZ)
            desc = item["weather"][0]["description"]
            temp = item["main"]["temp"]
            feels = item["main"]["feels_like"]
            wind = item["wind"]["speed"]
            pop = item.get("pop", 0) * 100
            lines.append(
                f"{dt.strftime('%H:%M')}: {desc}, {temp:.0f}°C (feels {feels:.0f}°C), "
                f"wind {wind:.0f} m/s, {pop:.0f}% chance of rain"
            )
        return "\n".join(lines)
    except Exception as e:
        return f"Could not fetch weather: {e}"


def fetch_calendar_events() -> str:
    """Fetch today's events + next 7 days from primary + subscribed calendars."""
    try:
        service = get_calendar_service()
        now_et = datetime.datetime.now(MONTREAL_TZ)
        today_start = now_et.replace(hour=0, minute=0, second=0, microsecond=0)
        week_end = today_start + datetime.timedelta(days=8)

        # Calendars to check: primary + the two shared/subscribed ones
        calendar_ids = [
            "primary",
            "REMOVED_CALENDAR_ID",
            "REMOVED_CALENDAR_ID",
        ]

        all_events = []
        for cal_id in calendar_ids:
            try:
                events_result = service.events().list(
                    calendarId=cal_id,
                    timeMin=today_start.isoformat(),
                    timeMax=week_end.isoformat(),
                    singleEvents=True,
                    orderBy="startTime",
                    maxResults=50,
                ).execute()
                all_events.extend(events_result.get("items", []))
            except Exception as cal_err:
                print(f"Warning: could not read calendar {cal_id[:20]}...: {cal_err}")

        if not all_events:
            return "No events found."

        # Sort merged events by start time
        def sort_key(e):
            return e["start"].get("dateTime") or e["start"].get("date")
        all_events.sort(key=sort_key)

        lines = []
        for e in all_events:
            start_raw = e["start"].get("dateTime") or e["start"].get("date")
            end_raw = e["end"].get("dateTime") or e["end"].get("date")
            summary = e.get("summary", "(no title)")
            location = e.get("location", "")

            if "T" in start_raw:
                start_dt = datetime.datetime.fromisoformat(start_raw).astimezone(MONTREAL_TZ)
                end_dt = datetime.datetime.fromisoformat(end_raw).astimezone(MONTREAL_TZ)
                time_str = f"{start_dt.strftime('%a %b %d, %H:%M')}–{end_dt.strftime('%H:%M')}"
            else:
                time_str = f"{start_raw} (all day)"

            loc_str = f" @ {location}" if location else ""
            lines.append(f"• {time_str}: {summary}{loc_str}")

        return "\n".join(lines)
    except Exception as e:
        return f"Could not fetch calendar: {e}"


def fetch_emails() -> str:
    """Report inbox total + unread counts, then list relevant unread from last 24h."""
    try:
        service = get_gmail_service()

        # Exact inbox counts via the INBOX label metadata (not an estimate)
        label_info = service.users().labels().get(
            userId="me", id="INBOX",
        ).execute()
        total_count = label_info.get("messagesTotal", 0)
        unread_count = label_info.get("messagesUnread", 0)

        count_line = f"Inbox: {total_count} emails total ({unread_count} unread)."

        # Relevant unread from last 24h (skipping promos/social/updates/newsletters)
        since = int((datetime.datetime.now() - datetime.timedelta(hours=24)).timestamp())
        query = f"is:unread after:{since} -category:promotions -category:social -category:updates -label:newsletters"

        results = service.users().messages().list(
            userId="me", q=query, maxResults=30,
        ).execute()

        messages = results.get("messages", [])
        if not messages:
            return f"{count_line}\nNo relevant unread emails in the last 24h."

        email_lines = [count_line, ""]
        for msg in messages:
            detail = service.users().messages().get(
                userId="me",
                id=msg["id"],
                format="metadata",
                metadataHeaders=["From", "Subject", "Date"],
            ).execute()
            headers = {h["name"]: h["value"] for h in detail["payload"]["headers"]}
            sender = headers.get("From", "Unknown")
            subject = headers.get("Subject", "(no subject)")
            snippet = detail.get("snippet", "")[:150]
            email_lines.append(f"From: {sender}\nSubject: {subject}\nSnippet: {snippet}")

        return "\n\n".join(email_lines)
    except Exception as e:
        return f"Could not fetch emails: {e}"


# ── Newsletter News ───────────────────────────────────────────────────────────
class _TextExtractor(HTMLParser):
    """Strips HTML to plain text but keeps <a href> links inline as: text (url)."""
    def __init__(self):
        super().__init__()
        self.parts = []
        self._current_href = None
        self._skip = False

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style", "head"):
            self._skip = True
        if tag == "a":
            for name, val in attrs:
                if name == "href":
                    self._current_href = val

    def handle_endtag(self, tag):
        if tag in ("script", "style", "head"):
            self._skip = False
        if tag == "a" and self._current_href:
            self.parts.append(f" ({self._current_href})")
            self._current_href = None
        if tag in ("p", "div", "br", "tr", "li", "h1", "h2", "h3"):
            self.parts.append("\n")

    def handle_data(self, data):
        if not self._skip:
            text = data.strip()
            if text:
                self.parts.append(text + " ")

    def get_text(self):
        out = "".join(self.parts)
        out = html.unescape(out)
        out = re.sub(r"\n{3,}", "\n\n", out)
        out = re.sub(r"[ \t]{2,}", " ", out)
        return out.strip()


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


def fetch_news_from_newsletters(service) -> str:
    """Find today's newsletters and have Claude pick top articles. Returns '' if none found."""
    # Senders to pull newsletters from
    sender_query = (
        "from:globeandmail OR from:globeandmailnewsletters OR "
        "from:economist.com OR from:nytimes.com OR from:theguardian.com"
    )
    # Only today's (last 18h to be safe, catches early-morning sends)
    since = int((datetime.datetime.now() - datetime.timedelta(hours=18)).timestamp())
    query = f"({sender_query}) after:{since}"

    results = service.users().messages().list(
        userId="me", q=query, maxResults=10,
    ).execute()
    messages = results.get("messages", [])

    if not messages:
        return ""  # signal: no newsletters → caller falls back to web

    newsletters = []
    for msg in messages:
        detail = service.users().messages().get(
            userId="me", id=msg["id"], format="full",
        ).execute()
        headers = {h["name"]: h["value"] for h in detail["payload"]["headers"]}
        sender = headers.get("From", "Unknown")
        subject = headers.get("Subject", "(no subject)")
        body = _decode_email_body(detail["payload"])
        body = body[:12000]  # cap to keep token cost sane
        newsletters.append(f"=== From: {sender} | Subject: {subject} ===\n{body}")

    combined = "\n\n".join(newsletters)

    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    news_prompt = f"""Below are the raw contents of this morning's news newsletters from my inbox (Globe and Mail, Economist, NYT, Guardian).

Pick the 5-10 most interesting and significant stories. Group related items if multiple outlets cover the same story. For each, give:
- A one-sentence summary
- The article link (pull the actual article URL from the newsletter text — it appears in parentheses after the link text)

Prioritize: major Canada/Quebec news, significant international events, financial/markets/macro. Skip lifestyle fluff, puzzles, recipes, horoscopes, and pure opinion unless notably important.

Return plain text only (no HTML, no markdown headers). Format each item as:
• [summary] — [url]

Newsletters:
{combined}"""

    message = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=1500,
        messages=[{"role": "user", "content": news_prompt}],
    )
    text = next((b.text for b in message.content if hasattr(b, "text")), "")
    return text.strip()


def fetch_news_from_web() -> str:
    """Fallback: web search for top stories when no newsletters are available."""
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    web_prompt = """Search the web for the most significant news from the last 24 hours. Cover three areas:
- 🇨🇦 Canada/Quebec: federal politics, Quebec politics, major policy or legal developments.
- 🌍 International: significant geopolitical events, elections, conflicts, major diplomatic moves.
- 📈 Financial: markets, central bank moves, major corporate news, macro developments.

Give 5-10 stories total. For each: a one-sentence summary followed by a source link.
Return plain text only (no HTML, no markdown headers). Format each item as:
• [summary] — [url]
Skip fluff — only genuinely significant developments."""

    message = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=1500,
        tools=[{"type": "web_search_20250305", "name": "web_search"}],
        messages=[{"role": "user", "content": web_prompt}],
    )
    # Response has search tool blocks + text blocks; grab all text and join
    text_parts = [b.text for b in message.content if hasattr(b, "text")]
    return "\n".join(text_parts).strip() or "News unavailable."


def fetch_news() -> str:
    """Try newsletters first; fall back to web search if none are found."""
    try:
        service = get_gmail_service()
        newsletter_news = fetch_news_from_newsletters(service)
        if newsletter_news:
            return newsletter_news + "\n\n(Source: your morning newsletters)"
        # No newsletters today → web fallback
        web_news = fetch_news_from_web()
        return web_news + "\n\n(Source: web search — no newsletters found this morning)"
    except Exception as e:
        # If newsletters fail for any reason, still try the web before giving up
        try:
            web_news = fetch_news_from_web()
            return web_news + "\n\n(Source: web search fallback)"
        except Exception as e2:
            return f"Could not fetch news: {e} / {e2}"


# ── Claude Call ───────────────────────────────────────────────────────────────
def generate_brief(weather_data: str, calendar_data: str, email_data: str, news_data: str, today_str: str) -> str:
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

    system = (
        "You are a personal assistant generating a concise morning brief. "
        "Be direct and scannable. No fluff. Use the raw data provided to produce "
        "a structured HTML email. The recipient is Élie, a law student in Montréal."
    )

    prompt = f"""Today is {today_str}. I'm in Montréal, QC (America/Toronto timezone).

Here is the raw data. Produce my morning brief as clean HTML (no markdown) with four sections:

---

1. 🌤 WEATHER
{weather_data}

2. 📅 CALENDAR
{calendar_data}

3. 📬 INBOX
{email_data}

4. 📰 NEWS
{news_data}

---

FORMAT RULES:
- Output ONLY valid HTML (no markdown, no backticks).
- Use a clean, readable style with inline CSS. White background, dark text, max-width 600px.
- Each section has a bold header with the emoji.
- Calendar: list today's events first under "Today", then flag notable events in the next 7 days under "Coming up".
- Inbox: START with the count line exactly as given (e.g. "47 emails total (6 unread)") as the first line of the section. THEN list each relevant email with sender (bold), subject, and one-line summary. Skip anything that looks like a newsletter or promo even if it slipped through. If there are no relevant emails, keep the count line and say the inbox has nothing needing attention.
- News: present the curated stories as a clean bullet list. Each bullet is the one-sentence summary with the article title/source linked (use the URL provided as an <a href> link). Keep links clickable. Group related items if the data already grouped them.
- Weather: give a 2-line summary — current conditions and high/low — plus one sentence of advice if warranted (umbrella, layers, etc.).
- End with a short "⚡ Action items" section: a bullet list of anything from calendar or inbox that seems to require action today.
- Keep the whole thing concise. Aim for something readable in under 2 minutes.
"""

    message = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=4000,
        messages=[{"role": "user", "content": prompt}],
        system=system,
    )

    return message.content[0].text


# ── Email Sender ──────────────────────────────────────────────────────────────
def send_email(service, html_body: str, subject: str):
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["To"] = RECIPIENT_EMAIL
    msg["From"] = "me"
    msg.attach(MIMEText(html_body, "html"))

    raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
    service.users().messages().send(userId="me", body={"raw": raw}).execute()
    print(f"Brief sent to {RECIPIENT_EMAIL}")


# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    now_et = datetime.datetime.now(MONTREAL_TZ)
    today_str = now_et.strftime("%A, %B %d, %Y")
    subject = f"☀️ Morning Brief — {today_str}"

    print("Fetching weather...")
    weather = fetch_weather()

    print("Fetching calendar...")
    calendar = fetch_calendar_events()

    print("Fetching emails...")
    emails = fetch_emails()

    print("Fetching news from newsletters...")
    news = fetch_news()

    print("Generating brief with Claude...")
    html = generate_brief(weather, calendar, emails, news, today_str)

    print("Sending email...")
    gmail = get_gmail_service()
    send_email(gmail, html, subject)

    print("Done.")


if __name__ == "__main__":
    main()
