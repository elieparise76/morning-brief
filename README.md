# Morning Brief — Setup Guide

A GitHub Actions workflow that emails you a personalized daily brief.
Runs entirely in the cloud — once it's set up, it works on its own with nothing kept
running on your end.

The delivery time is **not** hardcoded — it's controlled externally by the scheduler
(cron-job.org), so you can change it whenever you like without touching the code.

---

## What it does

Each morning, it:
1. Pulls the day's weather for your city (OpenWeatherMap)
2. Reads your Google Calendar (window depends on the edition — see "Editions")
3. Scans your Gmail for relevant unread email, and lists your starred follow-ups
4. Curates a news section from newsletters labelled in Gmail (or a web search fallback)
5. Calls Claude to compose a clean HTML brief from all of the above
6. Emails it to you via your Gmail account

The content adapts by day of week (a weekday edition, a longer weekend edition, and a
start-of-week "week ahead" edition on Sunday). See [SYSTEM_GUIDE.md](SYSTEM_GUIDE.md).

---

## Setup (one-time)

### Step 1 — Get the project files into a repo

Add the project files to your repo:
- `.github/workflows/morning_brief.yml`
- `morning_brief.py`
- `config.example.py`
- `debug_news.py`, `get_tokens.py`, `.gitignore`

> `config.py` is git-ignored and holds your personal settings. It's created next and must
> never be committed — which is what makes this repo safe to keep public.

---

### Step 2 — Create your config

```bash
cp config.example.py config.py
```

Edit `config.py`: your name, city, timezone, calendar IDs, news label, and interests.
Each field is documented in `config.example.py`.

---

### Step 3 — Get an Anthropic API key

https://console.anthropic.com → API Keys → Create key. You'll add it as a secret in Step 6.

---

### Step 4 — Get an OpenWeatherMap API key (free)

Sign up at https://openweathermap.org/api → API Keys tab → copy your key.

---

### Step 5 — Set up Google OAuth (Gmail + Calendar)

The most involved step. You need credentials that can read Gmail/Calendar and send mail.

**5a — Google Cloud project**
1. https://console.cloud.google.com → create a project (e.g. "Morning Brief")
2. Enable the **Gmail API** and **Google Calendar API**
3. **APIs & Services → Credentials → Create Credentials → OAuth client ID**
4. Application type: **Desktop app**
5. Download the JSON — this is your `credentials.json`

**5b — Authorize and generate tokens (run locally, one time)**
```bash
pip install google-auth-oauthlib google-auth-httplib2 google-api-python-client
python get_tokens.py
```
This opens a browser, asks you to log in, and saves `gmail_token.json` and
`gcal_token.json`. Keep these safe — they let the script act as you. They're git-ignored.

---

### Step 6 — Add GitHub Secrets

Repo → **Settings → Secrets and variables → Actions → New repository secret**

| Secret name | Value |
|---|---|
| `ANTHROPIC_API_KEY` | Your Anthropic API key |
| `OPENWEATHER_API_KEY` | Your OpenWeatherMap API key |
| `RECIPIENT_EMAIL` | Where the brief is sent |
| `GMAIL_TOKEN_JSON` | Full contents of `gmail_token.json` |
| `GCAL_TOKEN_JSON` | Full contents of `gcal_token.json` |
| `CONFIG_PY` | Full contents of your `config.py` |

**Why `CONFIG_PY`?** Since `config.py` is git-ignored, it isn't in the repo when GitHub
Actions runs. The workflow recreates it from this secret at runtime (see the "Create
config.py" step in the workflow), so your personal settings stay out of the public repo.

---

### Step 7 — Schedule it (cron-job.org)

The workflow is triggered externally for reliable, timezone-aware scheduling. See
[CRON_SETUP.md](CRON_SETUP.md) for the full walkthrough. In short: a cron-job.org job
POSTs to the GitHub API on your schedule, which fires the workflow via
`repository_dispatch`. Because cron-job.org supports real timezones, it handles
daylight-saving automatically, and you can change the delivery time anytime there —
no code change needed.

> The workflow also keeps a backup GitHub `schedule:` cron, but cron-job.org is the
> primary trigger.

---

### Step 8 — Test it

Repo → **Actions** tab → **Morning Brief** → **Run workflow** (or "Run now" in
cron-job.org). Check your inbox shortly after.

---

## Editions (per-day content)

The script picks an edition from the weekday — weekday, weekend (Saturday), and
week-ahead (Sunday) — each with different sections and news length. Full table in
[SYSTEM_GUIDE.md](SYSTEM_GUIDE.md).

---

## Customizing

- **Personal settings** (name, city, calendars, news label, interests): edit `config.py`.
- **Behavior** (section rules, news length, token caps, cost knobs): edit `morning_brief.py`.
- **Inspect what the news step receives**: run `python3 debug_news.py` (writes
  `debug_news_output.txt`, sends nothing).

---

## Documentation

- [SYSTEM_GUIDE.md](SYSTEM_GUIDE.md) — operations, maintenance schedule, troubleshooting.
- [CLAUDE.md](CLAUDE.md) — architecture and conventions (for Claude Code / contributors).
- [CRON_SETUP.md](CRON_SETUP.md) — external scheduler setup.

---

## Files

```
morning-brief/
├── .github/workflows/morning_brief.yml   ← workflow (recreates config.py, runs the script)
├── morning_brief.py                       ← main script
├── config.example.py                      ← committed template
├── config.py                              ← personal settings (GIT-IGNORED)
├── debug_news.py                          ← news diagnostic (read-only)
├── get_tokens.py                          ← one-time Google auth helper
├── .gitignore
├── README.md
├── SYSTEM_GUIDE.md
├── CLAUDE.md
└── CRON_SETUP.md
```
