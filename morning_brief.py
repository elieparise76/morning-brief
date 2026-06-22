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
    """Fetch today's events + next 7 days from Google Calendar."""
    try:
        service = get_calendar_service()
        now_et = datetime.datetime.now(MONTREAL_TZ)
        today_start = now_et.replace(hour=0, minute=0, second=0, microsecond=0)
        week_end = today_start + datetime.timedelta(days=8)

        events_result = service.events().list(
            calendarId="primary",
            timeMin=today_start.isoformat(),
            timeMax=week_end.isoformat(),
            singleEvents=True,
            orderBy="startTime",
            maxResults=50,
        ).execute()

        events = events_result.get("items", [])
        if not events:
            return "No events found."

        lines = []
        for e in events:
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
    """Fetch unread emails from the last 24 hours, skipping newsletters/promos."""
    try:
        service = get_gmail_service()
        since = int((datetime.datetime.now() - datetime.timedelta(hours=24)).timestamp())
        query = f"is:unread after:{since} -category:promotions -category:social -category:updates -label:newsletters"

        results = service.users().messages().list(
            userId="me",
            q=query,
            maxResults=30,
        ).execute()

        messages = results.get("messages", [])
        if not messages:
            return "No relevant unread emails."

        email_lines = []
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


# ── Claude Call ───────────────────────────────────────────────────────────────
def generate_brief(weather_data: str, calendar_data: str, email_data: str, today_str: str) -> str:
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
Search the web for breaking news from the last 12–24 hours. Cover three areas:
- 🇨🇦 Canada/Quebec: federal politics, Quebec politics, major policy or legal developments.
- 🌍 International: significant geopolitical events, elections, conflicts, major diplomatic moves.
- 📈 Financial: markets, central bank moves, major corporate news, macro developments (focus on North America and global impact).
Keep each item to one sentence. Aim for 3–5 bullets per area. Skip fluff — only genuinely significant developments.

---

FORMAT RULES:
- Output ONLY valid HTML (no markdown, no backticks).
- Use a clean, readable style with inline CSS. White background, dark text, max-width 600px.
- Each section has a bold header with the emoji.
- Calendar: list today's events first under "Today", then flag notable events in the next 7 days under "Coming up".
- Inbox: for each email, show sender (bold), subject, and one-line summary. Skip anything that looks like a newsletter or promo even if it slipped through. If the inbox is clean, say so.
- Weather: give a 2-line summary — current conditions and high/low — plus one sentence of advice if warranted (umbrella, layers, etc.).
- End with a short "⚡ Action items" section: a bullet list of anything from calendar or inbox that seems to require action today.
- Keep the whole thing concise. Aim for something readable in under 2 minutes.
"""

    message = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=2000,
        messages=[{"role": "user", "content": prompt}],
        system=system,
        tools=[{"type": "web_search_20250305", "name": "web_search"}],
    )

    return next(block.text for block in message.content if hasattr(block, "text"))


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

    print("Generating brief with Claude...")
    html = generate_brief(weather, calendar, emails, today_str)

    print("Sending email...")
    gmail = get_gmail_service()
    send_email(gmail, html, subject)

    print("Done.")


if __name__ == "__main__":
    main()
