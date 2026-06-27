# Morning Brief — Setup Guide

A GitHub Actions workflow that emails you a daily morning brief at **7:30 AM ET** on weekdays.  
Runs entirely in the cloud — no Mac required, no app open.

---

## What it does

Each weekday at 7:30 AM, it:
1. Pulls today's weather for your city (OpenWeatherMap)
2. Reads your Google Calendar (today + next 7 days)
3. Scans your Gmail for unread emails from the last 24h (skipping newsletters/promos)
4. Calls Claude to generate a clean HTML email from all of the above
5. Emails you the result via your Gmail account

---

## Setup (one-time, ~30 minutes)

### Step 1 — Create a GitHub repo

Create a new repo (e.g. `morning-brief`) and add the project files:
- `.github/workflows/morning_brief.yml`
- `morning_brief.py`
- `config.example.py`
- `debug_news.py`, `get_tokens.py`, `.gitignore`

> **Note:** `config.py` is git-ignored and holds your personal settings — it is created
> in the next step and must never be committed (safe for a public repo).

---

### Step 1b — Create your config

```bash
cp config.example.py config.py
```

Edit `config.py` and fill in your name, city, timezone, calendar IDs, news label, and
interests. See the comments in `config.example.py` for each field.

---

### Step 2 — Get an Anthropic API key

Go to https://console.anthropic.com → API Keys → Create key.  
Save it — you'll add it as a secret in Step 5.

---

### Step 3 — Get an OpenWeatherMap API key (free)

1. Sign up at https://openweathermap.org/api
2. Go to API Keys tab, copy your key.

---

### Step 4 — Set up Google OAuth credentials

This is the most involved step. You need credentials that can access Gmail and Google Calendar.

#### 4a — Create a Google Cloud project

1. Go to https://console.cloud.google.com
2. Create a new project (e.g. "Morning Brief")
3. Enable these two APIs:
   - Gmail API
   - Google Calendar API
4. Go to **APIs & Services → Credentials → Create Credentials → OAuth client ID**
5. Application type: **Desktop app**
6. Download the JSON file — this is your `credentials.json`

#### 4b — Authorize and get tokens

Run this locally (one-time) to authorize your Google account and generate token files.

Install dependencies:
```bash
pip install google-auth-oauthlib google-auth-httplib2 google-api-python-client
```

Run the auth script:
```bash
python get_tokens.py
```

This will open a browser, ask you to log in, and save two files:
- `gmail_token.json`
- `gcal_token.json`

Keep these safe — they let the script act as you.

---

### Step 5 — Add GitHub Secrets

In your repo: **Settings → Secrets and variables → Actions → New repository secret**

Add these secrets:

| Secret name | Value |
|---|---|
| `ANTHROPIC_API_KEY` | Your Anthropic API key |
| `OPENWEATHER_API_KEY` | Your OpenWeatherMap API key |
| `RECIPIENT_EMAIL` | Your email address (where the brief will be sent) |
| `GMAIL_TOKEN_JSON` | Contents of `gmail_token.json` (paste the whole JSON) |
| `GCAL_TOKEN_JSON` | Contents of `gcal_token.json` (paste the whole JSON) |

> **Note on `GMAIL_CREDENTIALS_JSON`**: The credentials file is only needed during the one-time token generation (Step 4b). Once you have the token files, you don't need to store the credentials in GitHub.

---

### Step 6 — Test it

Go to your repo → **Actions** tab → **Morning Brief** → **Run workflow**.  
Check your inbox within a minute or two.

---

## Timezone note

The workflow runs at `11:30 UTC`, which is:
- **7:30 AM EDT** (summer, UTC-4) ✓
- **6:30 AM EST** (winter, UTC-5) — adjust cron to `12:30 UTC` in November

To avoid thinking about this, you can use two cron entries in the workflow:
```yaml
- cron: '30 11 * * 1-5'  # Summer (EDT)
- cron: '30 12 * * 1-5'  # Winter (EST)
```
GitHub Actions will just run it twice on the transition days — harmless.

---

## Customizing the prompt

Edit the `prompt` variable in `morning_brief.py` to adjust sections, tone, or what to prioritize.

---

## Upgrading news section

Currently the news section shows a placeholder because the Claude API call doesn't have web search enabled in this setup. To enable live news:

Option A — Enable web search tool in the Claude API call (add `tools=[{"type": "web_search_20250305", "name": "web_search"}]` to the `client.messages.create()` call).

Option B — Add a separate step that calls a news API (e.g. NewsAPI.org, free tier) and passes headlines as raw data to Claude, same as weather.

---

## Files

```
morning-brief/
├── .github/
│   └── workflows/
│       └── morning_brief.yml   ← GitHub Actions schedule
├── morning_brief.py             ← Main script
├── get_tokens.py                ← One-time auth helper (run locally, don't commit)
└── README.md
```
