# CLAUDE.md

Guidance for Claude Code (claude.ai/code) when working in this repository.

## What this project is

A serverless **morning brief**: a Python script that runs daily in GitHub Actions,
gathers data from several APIs, has Claude compose an HTML email, and sends it via
Gmail. It runs fully in the cloud — no always-on machine required.

Delivery: **cron-job.org** fires at a set local time → calls the GitHub API
(`repository_dispatch`) → GitHub Actions runs `morning_brief.py`.

## Architecture (data flow)

```
cron-job.org (scheduled, real timezone)
   → POST repository_dispatch to GitHub API
   → GitHub Actions (.github/workflows/morning_brief.yml)
   → morning_brief.py:
        fetch_weather()           OpenWeatherMap (today detail OR week-ahead)
        fetch_calendar_events()   Google Calendar (primary + shared, windowed)
        fetch_emails()            Gmail (exact counts + relevant unread)
        fetch_starred()           Gmail (starred follow-ups)
        fetch_news()              Gmail "News" label → newsletters, else web search
        generate_brief()          Claude composes HTML from present sections
        send_email()              Gmail sends it
```

Two Claude API calls per run: one curates the news (`fetch_news_from_newsletters`
or `fetch_news_from_web`), one composes the final brief (`generate_brief`).

## Key files

- `morning_brief.py` — all logic, single file.
- `config.py` — **personal settings (git-ignored)**: name, city, timezone, calendar
  IDs, news label, interests. Created from `config.example.py`.
- `config.example.py` — committed template with placeholders.
- `debug_news.py` — read-only diagnostic; dumps exactly what Claude receives as news.
- `get_tokens.py` — one-time local Google OAuth helper (run once, never committed output).
- `.github/workflows/morning_brief.yml` — the scheduled workflow.
- `SYSTEM_GUIDE.md` — operations/maintenance guide.

## Setup for local work

```bash
pip install anthropic google-auth google-auth-oauthlib google-auth-httplib2 \
    google-api-python-client requests python-dateutil pytz
cp config.example.py config.py        # then fill in config.py
python3 get_tokens.py                  # generates gmail_token.json + gcal_token.json
```

Secrets are read from environment variables (set as GitHub Actions secrets in
production, or exported locally for testing):
`ANTHROPIC_API_KEY`, `OPENWEATHER_API_KEY`, `RECIPIENT_EMAIL`,
`GMAIL_TOKEN_JSON`, `GCAL_TOKEN_JSON`.

Locally, `get_gmail_service()` / `get_calendar_service()` also fall back to reading
`gmail_token.json` / `gcal_token.json` files if the env vars are absent. (Confirm
this when editing auth — see those functions.)

## Running

```bash
# Full run (sends an email — be careful):
ANTHROPIC_API_KEY=... OPENWEATHER_API_KEY=... RECIPIENT_EMAIL=... python3 morning_brief.py

# Inspect what the news step receives (no email, no Claude call):
python3 debug_news.py        # writes debug_news_output.txt
```

There is no test suite. Validate changes by (a) `python3 -c "import ast; ast.parse(open('morning_brief.py').read())"`,
(b) running `debug_news.py` for news changes, and (c) a guarded full run to a test
recipient.

## Editions (per-day behavior)

`get_edition(now)` returns a config based on the weekday. `main()` reads it to decide
what to fetch; `generate_brief()` only renders sections present in the `sections` dict.

| Edition | Days | Weather | Calendar | Inbox | Starred | News |
|---|---|---|---|---|---|---|
| weekday | Mon–Fri | today | today + 7d, routine-filtered | yes | yes | normal (5–10) |
| weekend | Sat | today | weekend only (today+2d) | **no** | yes | long (10–15) |
| week-ahead | Sun | week outlook | Mon–Fri, no "today" | yes | yes | short (3–5) |

To add behavior to ALL editions, add it once in the fetch list (`main()`) and the
section list (`generate_brief()`). To make it edition-specific, gate it in
`get_edition()`. **Do not** duplicate prompts per edition — the design is one
skeleton + per-day config + conditional prompt fragments (`_RULE_*` constants).

## Conventions & invariants (do not regress)

- **Personal data lives only in `config.py`.** Never hardcode names, city, calendar
  IDs, or interests into `morning_brief.py`. The repo is public.
- **Inbox counts** use Gmail `labels.get` on `INBOX` (exact), not `resultSizeEstimate`.
- **Inbox relevant-list** excludes `-label:<NEWS_LABEL>` so newsletters are counted
  but never analyzed for relevance.
- **Web-search responses**: collect text via `[b.text for b in msg.content if hasattr(b, "text")]`,
  never `content[0].text` (tool-use blocks precede text).
- **News HTML extraction** (`_TextExtractor`): keep a link's URL only if the link has
  visible anchor text; drop boilerplate via `_URL_BLOCKLIST`; collapse empty table
  cells. This keeps the per-newsletter char cap affordable — do not revert to keeping
  all links.
- **Weather**: judge rain by actual mm volume, not just % probability.
- **News cost controls**: `maxResults=6` newsletters, `body[:15000]` char cap each.
  Mirror any change in `debug_news.py`. (Cost rose to ~$0.50/run at 15/25000; these
  values target ~$0.10–0.15/run.)
- **TL;DR ("In brief")** is produced in the single `generate_brief` call — do not
  split it into an extra Claude call.
- **Language**: the brief's prose is English; proper nouns / event titles stay in
  their original language.

## Cost model

GitHub Actions, cron-job.org, OpenWeatherMap, Google APIs: free at this usage.
Anthropic is the only real cost — two calls/run. Adding data that folds into the
existing `generate_brief` call is near-free; adding a NEW `messages.create()` call is
what materially increases cost. Budget per new Claude call, not per data source.

## Maintenance note

A GitHub fine-grained PAT (stored in cron-job.org, not in the repo) triggers the
workflow and expires periodically; if briefs stop arriving, that token is the first
suspect. See `SYSTEM_GUIDE.md` §5 for the full maintenance schedule.
