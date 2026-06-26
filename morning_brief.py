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
def fetch_weather(mode: str = "today") -> str:
    """Fetch Montréal weather via OpenWeatherMap.
    mode='today': next ~24h in 3h steps (detailed).
    mode='week': the full 5-day forecast, summarized per day (for the Sunday edition)."""
    if not OPENWEATHER_API_KEY:
        return "Weather API key not configured."

    # 'today' pulls 8 x 3h slices (~24h); 'week' pulls the full 40-slice 5-day forecast.
    cnt = 8 if mode == "today" else 40
    url = (
        f"https://api.openweathermap.org/data/2.5/forecast"
        f"?q=Montreal,CA&appid={OPENWEATHER_API_KEY}&units=metric&cnt={cnt}"
    )
    try:
        r = requests.get(url, timeout=10)
        r.raise_for_status()
        data = r.json()
        items = data["list"]

        if mode == "week":
            # Group slices by calendar day; report each day's min/max temp, total rain,
            # and the dominant condition. Gives Claude enough to write a week-ahead line.
            from collections import defaultdict
            days = defaultdict(lambda: {"temps": [], "rain": 0.0, "snow": 0.0, "descs": []})
            for item in items:
                dt = datetime.datetime.fromtimestamp(item["dt"], tz=MONTREAL_TZ)
                key = dt.strftime("%A %b %d")
                days[key]["temps"].append(item["main"]["temp"])
                days[key]["rain"] += item.get("rain", {}).get("3h", 0)
                days[key]["snow"] += item.get("snow", {}).get("3h", 0)
                days[key]["descs"].append(item["weather"][0]["description"])
            lines = []
            for day, d in days.items():
                lo, hi = min(d["temps"]), max(d["temps"])
                # most common description that day
                dominant = max(set(d["descs"]), key=d["descs"].count)
                precip = ""
                if d["rain"]:
                    precip += f", total rain {d['rain']:.1f}mm"
                if d["snow"]:
                    precip += f", total snow {d['snow']:.1f}mm"
                lines.append(f"{day}: {dominant}, {lo:.0f}–{hi:.0f}°C{precip}")
            return "\n".join(lines)

        # mode == "today": detailed 3h slices
        lines = []
        for item in items:
            dt = datetime.datetime.fromtimestamp(item["dt"], tz=MONTREAL_TZ)
            desc = item["weather"][0]["description"]
            temp = item["main"]["temp"]
            feels = item["main"]["feels_like"]
            wind = item["wind"]["speed"]
            pop = item.get("pop", 0) * 100
            rain_mm = item.get("rain", {}).get("3h", 0)
            snow_mm = item.get("snow", {}).get("3h", 0)
            precip = ""
            if rain_mm:
                precip += f", rain {rain_mm:.1f}mm/3h"
            if snow_mm:
                precip += f", snow {snow_mm:.1f}mm/3h"
            lines.append(
                f"{dt.strftime('%H:%M')}: {desc}, {temp:.0f}°C (feels {feels:.0f}°C), "
                f"wind {wind:.0f} m/s, {pop:.0f}% chance{precip}"
            )
        return "\n".join(lines)
    except Exception as e:
        return f"Could not fetch weather: {e}"



def fetch_calendar_events(start_offset_days: int = 0, end_offset_days: int = 8) -> str:
    """Fetch events from [today+start_offset, today+end_offset) across all calendars.
    Default: today through next 7 days. start_offset_days=1 skips today entirely."""
    try:
        service = get_calendar_service()
        now_et = datetime.datetime.now(MONTREAL_TZ)
        midnight = now_et.replace(hour=0, minute=0, second=0, microsecond=0)
        window_start = midnight + datetime.timedelta(days=start_offset_days)
        window_end = midnight + datetime.timedelta(days=end_offset_days)
        today_start = window_start  # name kept for downstream references

        # Calendars to check: primary + the shared/subscribed ones
        calendar_ids = [
            "primary",
            "REMOVED_CALENDAR_ID",
            "REMOVED_CALENDAR_ID",
            "REMOVED_CALENDAR_ID",
        ]

        all_events = []
        for cal_id in calendar_ids:
            try:
                events_result = service.events().list(
                    calendarId=cal_id,
                    timeMin=window_start.isoformat(),
                    timeMax=window_end.isoformat(),
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


def fetch_starred() -> str:
    """Fetch all starred emails (no time filter — stars are a persistent follow-up system)."""
    try:
        service = get_gmail_service()
        # No "after:" filter — a star means "still to follow up", regardless of age.
        results = service.users().messages().list(
            userId="me", q="is:starred", maxResults=15,
        ).execute()

        messages = results.get("messages", [])
        if not messages:
            return "No starred emails."

        starred_lines = []
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
            starred_lines.append(f"From: {sender}\nSubject: {subject}\nSnippet: {snippet}")

        return "\n\n".join(starred_lines)
    except Exception as e:
        return f"Could not fetch starred emails: {e}"


# ── Newsletter News ───────────────────────────────────────────────────────────
class _TextExtractor(HTMLParser):
    """Strips HTML to readable text. Keeps a link's URL ONLY if the link has real
    anchor text — this drops the hundreds of bare image/icon/spacer tracking links
    that otherwise eat the whole budget, while keeping meaningful article links."""
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
            # Only emit the URL if the link actually had visible text (i.e. it's a
            # real article link, not an image/icon/spacer). Also skip obvious
            # boilerplate destinations.
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
        # Collapse runs of empty table-cell separators ("| | | |" -> "")
        out = re.sub(r"(\s*\|\s*){2,}", " ", out)
        out = re.sub(r"^\s*\|\s*$", "", out, flags=re.MULTILINE)
        # Drop lines that are now just whitespace/separators
        lines = [ln.rstrip() for ln in out.split("\n")]
        lines = [ln for ln in lines if ln.strip() and ln.strip() != "|"]
        out = "\n".join(lines)
        out = re.sub(r"\n{3,}", "\n\n", out)
        out = re.sub(r"[ \t]{2,}", " ", out)
        return out.strip()


# Boilerplate destinations to drop even when they carry anchor text.
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


def fetch_news_from_newsletters(service, news_length: str = "normal") -> str:
    """Find today's News-labelled emails and have Claude pick top articles. Returns '' if none found.
    news_length: 'short' (~3-5 stories), 'normal' (~5-10), 'long' (~10-15)."""
    # Pull anything labelled "News" since 18:00 yesterday. The "after:" timestamp is applied
    # together with the label, so even if the "News" label holds thousands of emails total,
    # only the last ~13h are returned (a handful in practice). maxResults caps it regardless.
    since = int((datetime.datetime.now() - datetime.timedelta(hours=18)).timestamp())
    query = f"label:News after:{since}"

    results = service.users().messages().list(
        userId="me", q=query, maxResults=15,
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
        body = body[:25000]  # cap per newsletter (raised — extraction is now much denser after stripping link/cell noise)
        newsletters.append(f"=== From: {sender} | Subject: {subject} ===\n{body}")

    combined = "\n\n".join(newsletters)

    # Story-count target varies by edition (weekend = longer, Sunday = shorter).
    count_targets = {
        "short": "Aim for 3-5 STORIES (not articles — one story can bundle several links).",
        "normal": "Aim for 5-10 STORIES (not articles — one story can bundle several links). It's fine to exceed 10 links total if the stories warrant it.",
        "long": "Aim for 10-15 STORIES (not articles — one story can bundle several links). This is a weekend edition, so go deeper — include more analysis, more opinion pieces matching my interests, and more of the second-tier stories you'd normally cut. It's fine to exceed 15 links total.",
    }
    count_line = count_targets.get(news_length, count_targets["normal"])

    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    news_prompt = f"""Below are the raw contents of this morning's news newsletters from my inbox (Globe and Mail, Economist, NYT, Guardian).

I read the news hourly, so I already know the big headlines. DON'T just recap what happened — I know that. Your job is to surface the SPECIFIC ANGLE: the new detail, the follow-up development, the analysis, the consequence I might have missed.

HOW TO HANDLE EACH STORY:
- For major breaking news: give a brief one-line recap for context, then emphasize the specifics — and pull those specifics from ACROSS the different newsletters. Each outlet often has a different angle; synthesize them into one story.
  Example of the style I want:
  "Montréal shooting: the killer's motive was revealed as [X] (Globe). Police are now warning of potential copycats (NYT)."
  → One story, multiple sources, each adding a distinct specific — not the same recap repeated.
- Group all coverage of the same event into a SINGLE story, even if 3 outlets cover it. A story can carry multiple links.

SELECTION:
- {count_line}
- Target a rough balance across these four buckets (~25% each). It's a guide, not a hard quota — BUT if a bucket has source material in the newsletters, you MUST represent it. Never silently drop a whole bucket that has content available. Only let a bucket be thin if the newsletters genuinely contain little/nothing for it that morning. The business/markets bucket in particular is frequently under-filled — actively check for a markets/business newsletter and pull from it.
  • 🇨🇦 Canada / Quebec (~25%)
  • 🇺🇸 United States (~25%)
  • 🌍 International (~25%)
  • 📈 Business / markets / macro (~25%)

WHAT INTERESTS ME, BY BUCKET:
- 🇨🇦 Canada/Quebec: federal AND Quebec politics; constitutional law broadly (the courts, the Charter, anything judicial or legal); party and parliamentary affairs; criminal law; environment; the economy; the French language. Quebec issues of any kind interest me. Favor the specific angle and analysis here — I follow this closely.
- 🇺🇸 United States: federal politics broadly, especially constitutional debates. I like sharp opinion pieces on current political trends. Favor angle and analysis.
- 🌍 International: general international news — I'm less expert here, so I'm more open to straightforward breaking-news coverage, not just angles. Cover ASIA when relevant, not only Europe and North America. Don't let this bucket become Europe-only.
- 📈 Business/markets: anything genuinely interesting — public and private market trends, economic and regulatory policy, technology, central banks, major corporate news. IMPORTANT: the "skip what I already know / give me the angle" rule applies LESS here. For markets, the DATA ITSELF is what I want, even if I "know" it — index moves (S&P, Nasdaq, TSX, KOSPI, etc.), notable earnings (who reports today, who beat/missed), big corporate moves (IPOs, bond sales, lawsuits, M&A), key macro prints (PMI, CPI, rate decisions). If a business/markets newsletter is present (e.g. Economist "Business in Brief"), you MUST surface its key market data and top business stories — do NOT drop this bucket. A concise markets line (e.g. "S&P −1.5%, Nasdaq −2.2% on AI-overvaluation fears; Micron earnings today") is exactly what I want.

- Beyond the big shared stories, INCLUDE narrower or single-source pieces (including opinion/analysis) when they fit the interests above. Skip lifestyle fluff, puzzles, recipes, horoscopes, and generic opinion that doesn't touch these interests.

FORMAT:
- Return plain text only (no HTML, no markdown headers).
- Order the stories by bucket: Canada/Quebec first, then US, then International, then Business/markets.
- Each story on its own line as:
• [one-line recap if needed +] the specific angle(s), with source attributions inline — [url1] [url2]
- Pull the actual article URLs from the newsletter text (they appear in parentheses after the link text).

Newsletters:
{combined}"""

    message = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=4000,
        messages=[{"role": "user", "content": news_prompt}],
    )
    text = next((b.text for b in message.content if hasattr(b, "text")), "")
    return text.strip()


def fetch_news_from_web(news_length: str = "normal") -> str:
    """Fallback: web search for top stories when no newsletters are available."""
    counts = {"short": "3-5", "normal": "5-10", "long": "10-15"}
    n = counts.get(news_length, "5-10")
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    web_prompt = f"""Search the web for the most significant news from the last 24 hours. Cover four areas:
- 🇨🇦 Canada/Quebec: federal politics, Quebec politics, major policy or legal developments.
- 🇺🇸 United States: federal politics, constitutional debates, notable policy.
- 🌍 International: significant geopolitical events, elections, conflicts, major diplomatic moves (include Asia, not just Europe).
- 📈 Business/markets: index moves, central bank moves, major corporate news, macro developments.

Give {n} stories total, roughly balanced across the four areas. For each: a one-sentence summary followed by a source link.
Return plain text only (no HTML, no markdown headers). Format each item as:
• [summary] — [url]
Skip fluff — only genuinely significant developments."""

    message = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=2500,
        tools=[{"type": "web_search_20250305", "name": "web_search"}],
        messages=[{"role": "user", "content": web_prompt}],
    )
    # Response has search tool blocks + text blocks; grab all text and join
    text_parts = [b.text for b in message.content if hasattr(b, "text")]
    return "\n".join(text_parts).strip() or "News unavailable."


def fetch_news(news_length: str = "normal") -> str:
    """Try newsletters first; fall back to web search if none are found."""
    try:
        service = get_gmail_service()
        newsletter_news = fetch_news_from_newsletters(service, news_length=news_length)
        if newsletter_news:
            return newsletter_news + "\n\n(Source: your morning newsletters)"
        # No newsletters today → web fallback
        web_news = fetch_news_from_web(news_length=news_length)
        return web_news + "\n\n(Source: web search — no newsletters found this morning)"
    except Exception as e:
        # If newsletters fail for any reason, still try the web before giving up
        try:
            web_news = fetch_news_from_web(news_length=news_length)
            return web_news + "\n\n(Source: web search fallback)"
        except Exception as e2:
            return f"Could not fetch news: {e} / {e2}"


# ── Claude Call ───────────────────────────────────────────────────────────────

# Reusable format-rule fragments, keyed by section. Only the rules for sections
# actually present in the brief get included in the prompt.
_RULE_TLDR = '- TL;DR — at the VERY TOP, write a short summary paragraph (bold header "In brief"). A single flowing prose paragraph in ENGLISH that synthesizes ACROSS all the sections present — surface cross-cutting things no single section sees on its own (e.g. a starred email from someone I\'m meeting; a tight turnaround between two events; a deadline; a market move touching my holdings). Lead with the day\'s/period\'s "shape", then the 2-4 things that matter. ALWAYS include it, scaled to how much is going on: one or two sentences when quiet, 3-5 when busy. Don\'t pad. Write it last but place it first.'

_RULE_WEATHER_TODAY = '- Weather: 2-line summary — current conditions and high/low — plus one sentence of advice if warranted. IMPORTANT on rain: the data gives a % chance AND the actual mm volume. Judge by VOLUME, not probability. Under ~1mm/3h is drizzle/trace — say "a chance of light rain", NOT steady rain. Only call it real rain at ~2mm+/3h. High % with tiny mm = "might sprinkle". Don\'t over-warn.'

_RULE_WEATHER_WEEK = '- Weather (week ahead): the data is a per-day forecast for the next ~5 days. Give a SHORT week-ahead outlook — the general trend (warming/cooling), and call out any specific days with notable rain, storms, or temperature swings. 2-4 lines total. Judge rain by mm volume, not just description. This replaces the usual daily weather since it\'s the start-of-week edition.'

_RULE_CALENDAR_FULL = '''- Calendar — TWO subsections:
  • "Today": list EVERYTHING scheduled today, no exceptions — including routine/recurring items. Today is complete.
  • "Coming up" (next 7 days): do NOT dump everything. Include what is actionable or notable (one-off events, appointments, deadlines). FILTER OUT plain recurring routine (a daily "Bureau"/"Travail"/"Cours" block) — but KEEP a routine item when it creates an interesting constraint (work ends 17:00 and an event at 17:30; an unusual time; routine absent when normally present). Infer "routine" from repeated titles/hours. When in doubt, INCLUDE. If you drop routine items, add a brief note like "(routine work/class days hidden)".'''

_RULE_CALENDAR_WEEKEND = '- Calendar (weekend): list everything scheduled for this weekend (today + the rest of the weekend). This is the weekend edition — show it all, no routine filtering needed, weekends are rarely routine.'

_RULE_CALENDAR_WEEKAHEAD = '''- Calendar (week ahead): there is NO "today" section in this edition. Show the 5 upcoming weekdays (Mon-Fri). Apply the usual routine filter: include one-off events, appointments, deadlines, and any routine that creates an interesting constraint; filter out plain recurring routine blocks (note "(routine work/class days hidden)" if you drop them). This is the start-of-week planning view — help me see what the week holds.'''

_RULE_INBOX = '- Inbox: START with the count line exactly as given (e.g. "47 emails total (6 unread)"). THEN list each relevant email with sender (bold), subject, one-line summary. Skip newsletters/promos. If none relevant, keep the count line and say the inbox has nothing needing attention.'

_RULE_STARRED = '- À suivre (starred): emails I\'ve starred as follow-ups. Render each as a SINGLE actionable line capturing what to track — infer the action from sender/subject/snippet (e.g. "Paiement à venir de [personne]", "Échéance pour l\'envoi de [document]"). One line each, action-first. If none, omit this section entirely.'

_RULE_NEWS = '- News: the data is organized by geographic bucket (Canada/Quebec, US, International, Business/markets) and may group several source links per story. Preserve that order and grouping. Render each story as a bullet; make every source link a clickable <a href> using the outlet name as link text (e.g. "Globe", "NYT"). Keep multiple links on a story inline. Do not reorder or merge stories.'

_RULE_ACTION_ITEMS = '- End with a short "⚡ Action items" section: a bullet list of anything from calendar/inbox/starred that seems to require action.'


def generate_brief(sections: dict, today_str: str, edition_note: str = "") -> str:
    """Assemble and send the main brief prompt from whichever sections are present.
    `sections` maps a section key -> its raw data string. Missing keys are omitted
    entirely (data not fetched + rule not included + header not shown)."""
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

    system = (
        "You are a personal assistant generating a concise morning brief. "
        "Be direct and scannable. No fluff. Use the raw data provided to produce "
        "a structured HTML email. The recipient is Élie, a law student in Montréal. "
        "Write the ENTIRE brief in English (section headers, summaries, everything). "
        "Keep proper nouns and event titles in their original language as they appear "
        "in the data (e.g. a calendar event 'Souper entre chéris' stays as is), but all "
        "of your own prose — headers, the TL;DR, summaries, advice — must be in English. "
        "Only include sections for the data you are given; do not invent sections."
    )

    # Map each possible section to (emoji header, the format rule to include).
    section_meta = {
        "weather":        ("🌤 WEATHER", None),       # rule chosen separately (today vs week)
        "calendar":       ("📅 CALENDAR", None),       # rule chosen separately
        "inbox":          ("📬 INBOX", _RULE_INBOX),
        "starred":        ("⭐ À SUIVRE (starred emails)", _RULE_STARRED),
        "news":           ("📰 NEWS", _RULE_NEWS),
    }

    # Build the data block (only present sections) and collect the rules to include.
    data_blocks = []
    rules = [_RULE_TLDR]
    n = 1
    for key in ["weather", "calendar", "inbox", "starred", "news"]:
        if key not in sections:
            continue
        header, rule = section_meta[key]
        data_blocks.append(f"{n}. {header}\n{sections[key]}")
        n += 1
        # Weather and calendar pick a variant rule passed in via sections meta.
        if key == "weather":
            rules.append(sections.get("_weather_rule", _RULE_WEATHER_TODAY))
        elif key == "calendar":
            rules.append(sections.get("_calendar_rule", _RULE_CALENDAR_FULL))
        elif rule:
            rules.append(rule)
    rules.append(_RULE_ACTION_ITEMS)

    data_section = "\n\n".join(data_blocks)
    rules_section = "\n".join([
        "- Output ONLY valid HTML (no markdown, no backticks).",
        "- Use a clean, readable style with inline CSS. White background, dark text, max-width 600px.",
        "- Each section has a bold header with the emoji.",
        *rules,
        "- Keep the whole thing concise and scannable.",
    ])

    note_line = f"\n{edition_note}\n" if edition_note else ""

    prompt = f"""Today is {today_str}. I'm in Montréal, QC (America/Toronto timezone).{note_line}
Here is the raw data. Produce my brief as clean HTML (no markdown). Start with the TL;DR at the very top, then the sections below.

---

{data_section}

---

FORMAT RULES:
{rules_section}
"""

    message = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=8000,
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
def get_edition(now_et):
    """Pick the edition based on the weekday. Returns (name, config dict)."""
    weekday = now_et.weekday()  # Mon=0 .. Sat=5, Sun=6

    if weekday == 5:  # Saturday — weekend edition
        # Calendar window: today (Sat) through end of Sunday = 2 days.
        return "weekend", {
            "weather": "today",
            "calendar": ("weekend", 0, 2),   # (rule, start_offset, end_offset)
            "inbox": False,                   # no inbox on Saturday
            "starred": True,                  # starred only
            "news": "long",
        }

    if weekday == 6:  # Sunday — start-of-week edition
        # Calendar: skip today (Sun), show the next 5 days = Mon..Fri.
        # start_offset=1 (tomorrow), end_offset=6 (through Fri inclusive).
        return "week-ahead", {
            "weather": "week",
            "calendar": ("weekahead", 1, 6),
            "inbox": True,                    # full inbox like normal
            "starred": True,
            "news": "short",
        }

    # Mon-Fri — standard edition
    return "weekday", {
        "weather": "today",
        "calendar": ("full", 0, 8),           # today + next 7 days
        "inbox": True,
        "starred": True,
        "news": "normal",
    }


def main():
    now_et = datetime.datetime.now(MONTREAL_TZ)
    today_str = now_et.strftime("%A, %B %d, %Y")
    edition_name, cfg = get_edition(now_et)
    print(f"Edition: {edition_name}")

    subject_prefix = {
        "weekend": "🌅 Weekend Brief",
        "week-ahead": "📆 Week Ahead",
        "weekday": "☀️ Morning Brief",
    }[edition_name]
    subject = f"{subject_prefix} — {today_str}"

    edition_notes = {
        "weekend": "This is the WEEKEND edition: weekend calendar only, no inbox section (starred follow-ups only), and a longer/deeper news section.",
        "week-ahead": "This is the START-OF-WEEK edition (Sunday): no 'today' — a week-ahead calendar (Mon-Fri) and a week-ahead weather outlook, normal inbox, shorter news.",
        "weekday": "",
    }
    edition_note = edition_notes[edition_name]

    sections = {}

    # Weather
    print("Fetching weather...")
    sections["weather"] = fetch_weather(mode=cfg["weather"])
    sections["_weather_rule"] = _RULE_WEATHER_WEEK if cfg["weather"] == "week" else _RULE_WEATHER_TODAY

    # Calendar
    print("Fetching calendar...")
    cal_rule_key, start_off, end_off = cfg["calendar"]
    sections["calendar"] = fetch_calendar_events(start_offset_days=start_off, end_offset_days=end_off)
    sections["_calendar_rule"] = {
        "full": _RULE_CALENDAR_FULL,
        "weekend": _RULE_CALENDAR_WEEKEND,
        "weekahead": _RULE_CALENDAR_WEEKAHEAD,
    }[cal_rule_key]

    # Inbox (optional)
    if cfg["inbox"]:
        print("Fetching emails...")
        sections["inbox"] = fetch_emails()

    # Starred (optional)
    if cfg["starred"]:
        print("Fetching starred emails...")
        sections["starred"] = fetch_starred()

    # News
    print(f"Fetching news ({cfg['news']})...")
    sections["news"] = fetch_news(news_length=cfg["news"])

    print("Generating brief with Claude...")
    html = generate_brief(sections, today_str, edition_note=edition_note)

    print("Sending email...")
    gmail = get_gmail_service()
    send_email(gmail, html, subject)

    print("Done.")


if __name__ == "__main__":
    main()
