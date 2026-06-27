"""
config.example.py — Template configuration for the Morning Brief.

SETUP:
    1. Copy this file to `config.py`:   cp config.example.py config.py
    2. Fill in your real values in config.py
    3. config.py is git-ignored, so your personal details never get committed.

morning_brief.py imports from config.py. If config.py is missing, the script
will tell you to create it from this template.
"""

# ── Personal identity (used in the Claude prompt) ─────────────────────────────
# A short description of who the brief is for. Used to tailor tone/relevance.
USER_NAME = "Your Name"
USER_DESCRIPTION = "a professional in Your City"  # e.g. "a teacher in Lyon"

# ── Location (weather + timezone) ─────────────────────────────────────────────
WEATHER_CITY = "Montreal,CA"          # OpenWeatherMap city query
TIMEZONE = "America/Toronto"          # IANA timezone name

# ── Calendars ─────────────────────────────────────────────────────────────────
# "primary" is your main Google calendar. Add any shared/subscribed calendar IDs
# (found in Google Calendar → calendar settings → "Integrate calendar" → Calendar ID).
CALENDAR_IDS = [
    "primary",
    # "xxxxxxxx@group.calendar.google.com",
    # "yyyyyyyy@group.calendar.google.com",
]

# ── News newsletters ──────────────────────────────────────────────────────────
# The Gmail label that your news newsletters are tagged with (via a Gmail filter).
NEWS_LABEL = "News"

# Your interests, used to steer news curation. Written as prose the model reads.
# Organized by geographic bucket. Edit freely.
NEWS_INTERESTS = """\
- 🇨🇦 Canada/Quebec: federal and provincial politics; law and the courts; \
party/parliamentary affairs; criminal law; environment; the economy. Favor angle and analysis.
- 🇺🇸 United States: federal politics, especially constitutional debates; sharp opinion on political trends.
- 🌍 International: general breaking news (more open here). Cover Asia, not only Europe/North America.
- 📈 Business/markets: public and private market trends, economic and regulatory policy, technology, \
central banks, major corporate news. Market DATA itself is wanted even if "known"."""

# ── Recipient ─────────────────────────────────────────────────────────────────
# Where the brief is emailed. Usually your own address. (Can also be set via the
# RECIPIENT_EMAIL environment variable / GitHub secret, which takes precedence.)
RECIPIENT_EMAIL_FALLBACK = ""
