# Morning Brief — System & Maintenance Guide

A serverless automation that emails a daily brief at a set local time, 7 days a week.
Runs entirely in the cloud — no always-on machine required.

Two purposes:
1. **Maintenance** — what to renew, when, and how (tokens, keys, billing).
2. **Context handoff** — paste this file (plus `CLAUDE.md`) to Claude in a new chat
   or to Claude Code if you need help and have lost prior context.

> **Personal settings** (name, city, calendar IDs, interests, recipient) live in
> `config.py`, which is **git-ignored**. This repo is public; nothing personal is in
> the committed code. Copy `config.example.py` → `config.py` to configure.

---

## 1. What it does

Each morning a cloud job runs and emails a brief. The content adapts by day (see §6).
Possible sections, in order:

0. **In brief (TL;DR)** — a short English prose paragraph that synthesizes ACROSS all
   sections (cross-cutting things no single section sees). Scales to how busy the day is.
1. **🌤 Weather** — local forecast. Judges rain by actual **mm volume**, not just
   probability. (Sunday: a week-ahead outlook instead.)
2. **📅 Calendar** — primary + shared/subscribed calendars. Window and filtering vary
   by edition. On weekdays: everything today, plus a routine-filtered "coming up".
3. **📬 Inbox** — exact count (total + unread via `labels.get`), then relevant unread
   from the last 24h. Newsletters are counted but never analyzed.
4. **⭐ À suivre (starred)** — starred emails as one-line follow-ups (no time filter).
5. **📰 News** — newsletters labelled in Gmail, curated by Claude; geographic balance
   (Canada/Quebec, US, International, Business/markets). Falls back to web search if no
   newsletters. Length varies by edition.
6. **⚡ Action items** — to-dos pulled from calendar/inbox/starred.

Brief prose is in English; proper nouns / event titles keep their original language.

---

## 2. Architecture

```
cron-job.org  (fires at the set time, real timezone → handles DST automatically)
      │  POST repository_dispatch to the GitHub API
      ▼
GitHub Actions  (.github/workflows/morning_brief.yml)
      ▼
morning_brief.py
      ├─ OpenWeatherMap  → weather (today detail or week-ahead)
      ├─ Google Calendar → primary + shared calendars (windowed per edition)
      ├─ Gmail           → inbox counts + relevant emails + starred + newsletters
      ├─ Anthropic       → news curation call + final brief composition call
      ▼
Gmail (send) → emails the brief → phone notification
```

**Why cron-job.org, not GitHub's own cron?** GitHub's schedule is unreliable (late or
skipped) and timezone-naive. cron-job.org fires on time and supports real timezones.
The workflow keeps a backup `schedule:` cron, but cron-job.org is the primary trigger.

---

## 3. Accounts & tools

| Service | Purpose | Cost |
|---|---|---|
| GitHub | Hosts code + runs the job (Actions) | Free |
| cron-job.org | Triggers the job daily | Free |
| Anthropic Console | Claude API (news + brief composition) | ~$3–5/month |
| OpenWeatherMap | Weather data | Free tier |
| Google Cloud | OAuth credentials for Gmail + Calendar | Free |

---

## 4. Secrets (GitHub → Settings → Secrets and variables → Actions)

| Secret | What it is | Expires? |
|---|---|---|
| `ANTHROPIC_API_KEY` | Claude API key | No (unless rotated) |
| `OPENWEATHER_API_KEY` | Weather API key | No |
| `RECIPIENT_EMAIL` | Where the brief is sent | No |
| `GMAIL_TOKEN_JSON` | Google OAuth token (Gmail read+send) | Auto-refreshes |
| `GCAL_TOKEN_JSON` | Google OAuth token (Calendar read) | Auto-refreshes |

A **GitHub Personal Access Token** is stored in **cron-job.org** (not in the repo) to
trigger the workflow — this is the one with a periodic expiry. See §5.

---

## 5. MAINTENANCE SCHEDULE ⚠️

| Item | Expires | If it lapses | Renew |
|---|---|---|---|
| **GitHub PAT** (in cron-job.org) | ~90 days (your setting) | Trigger gets 401, no brief | §5a |
| **Anthropic credits** | At $0 balance | Job crashes at Claude step | Top up in Console → Billing |
| **Google OAuth tokens** | Don't expire if used regularly | Breaks only if unused ~6mo or revoked | Re-run `get_tokens.py`, update both secrets |
| **OpenWeatherMap key** | No expiry | — | — |

> A recurring calendar reminder fires ~3 days before the PAT expiry with the renewal
> steps. Also enable a **spend alert** in Anthropic Console as an early warning.

### 5a. Renew the GitHub PAT
1. https://github.com/settings/tokens?type=beta (Fine-grained tokens)
2. Regenerate / recreate: repo access = this repo only; permission = **Contents: Read
   and write**; expiration as desired.
3. Copy the token.
4. cron-job.org → your trigger job → Headers → set `Authorization: Bearer <new token>`.
5. Hit **Run now** to confirm a run appears in GitHub Actions.

> Setting the PAT to no-expiration removes this chore (slightly lower security).

---

## 6. Editions (per-day content)

Driven by `get_edition()` in code. The script picks the edition from the weekday; the
delivery time is set in cron-job.org (Sunday can be scheduled later via a second job).

| Edition | Days | Weather | Calendar | Inbox | Starred | News |
|---|---|---|---|---|---|---|
| weekday | Mon–Fri | today | today + 7d (routine-filtered) | yes | yes | normal (5–10) |
| weekend | Sat | today | weekend only (today + 2d) | no | yes | long (10–15) |
| week-ahead | Sun | week outlook | Mon–Fri (no "today") | yes | yes | short (3–5) |

Email subjects differ per edition so they're easy to spot.

> **Delivery note:** cron-job.org should run 7 days/week. To send Sunday later than
> the weekday time, use two cron-job.org jobs (Mon–Sat at the normal time; Sun at the
> later time). The script auto-selects the edition by weekday regardless of when fired.

---

## 7. Configuration

### Personal settings → `config.py` (git-ignored)
`USER_NAME`, `USER_DESCRIPTION`, `WEATHER_CITY`, `TIMEZONE`, `CALENDAR_IDS`,
`NEWS_LABEL`, `NEWS_INTERESTS`, `RECIPIENT_EMAIL_FALLBACK`. See `config.example.py`.

### Behavior knobs (in `morning_brief.py`)
| Setting | Current | Where |
|---|---|---|
| Newsletters fetched | 6 | `maxResults` in `fetch_news_from_newsletters` |
| Per-newsletter char cap | 15,000 | `body[:15000]` in `fetch_news_from_newsletters` |
| Newsletter lookback | 18h | `since` in `fetch_news_from_newsletters` |
| Inbox lookback | 24h | `since` in `fetch_emails` |
| Inbox counts | exact via `labels.get` | `fetch_emails` |
| Inbox excludes newsletters | `-label:<NEWS_LABEL>` | `fetch_emails` query |
| Starred cap | 15, no time filter | `fetch_starred` |
| News length per edition | short/normal/long | `get_edition` + `fetch_news` |
| Model | claude-sonnet-4-6 | all `messages.create` calls |
| Max tokens (news call) | 4000 | `fetch_news_from_newsletters` |
| Max tokens (brief call) | 8000 | `generate_brief` |
| Web search | news fallback only | `fetch_news_from_web` |

### News HTML extraction
`_TextExtractor` keeps a link's URL **only if the link has visible anchor text**
(drops bare image/icon/spacer tracking links), drops boilerplate URLs (`_URL_BLOCKLIST`),
and collapses empty table cells. This is what keeps the char cap affordable — don't
revert to keeping all links.

---

## 8. Cost

| Component | Cost |
|---|---|
| GitHub Actions / cron-job.org / OpenWeatherMap / Google APIs | Free |
| Anthropic — 2 calls/run (news + brief) | ~$0.10–0.15/run |
| **Total** | **~$3–5/month** |

History: at 15 newsletters × 25,000 chars the cost reached ~$0.50/run; lowering to
6 × 15,000 brought it back down. Most additions fold into the existing brief call
(near-free); only a NEW separate Claude call materially moves the bill.

---

## 9. Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| No brief at all | GitHub PAT expired | Renew, update cron-job.org (§5a) |
| No brief, PAT fine | Anthropic credits out | Top up |
| News empty / web fallback when newsletters existed | Arrived after send time, or not labelled | Check the Gmail filter applies the label; widen lookback |
| News missing a bucket (e.g. business) | Content truncated or buried | Run `debug_news.py`; check cap + extraction; add a dedicated source |
| 422 from cron-job.org | URL missing `api.` prefix, or bad body | URL = `api.github.com/...`; body = `{"event_type":"morning-brief"}` |
| 401/403 from cron-job.org | PAT wrong / lacks Contents:write | Regenerate with correct permission |
| Calendar missing shared events | Token can't see that calendar | Confirm subscribed at account level; check Actions log warnings |
| Brief cut off mid-HTML | Hit token ceiling | Raise `max_tokens` in `generate_brief` |
| Newsletters clutter the inbox list | `-label:<NEWS_LABEL>` missing | Already excluded; verify the label name matches config |

---

## 10. Files

```
morning-brief/
├── .github/workflows/morning_brief.yml
├── morning_brief.py          ← all logic
├── config.example.py         ← committed template
├── config.py                 ← personal settings (GIT-IGNORED)
├── debug_news.py             ← news diagnostic (read-only)
├── get_tokens.py             ← one-time Google auth helper (run locally)
├── .gitignore
├── CLAUDE.md                 ← context for Claude Code
├── README.md                 ← setup guide
├── CRON_SETUP.md             ← cron-job.org setup
└── SYSTEM_GUIDE.md           ← this file
```

---

## 11. For Claude (context handoff)

Working serverless morning-brief. All logic in `morning_brief.py`; personal settings in
the git-ignored `config.py` (template: `config.example.py`). Per-day editions via
`get_edition()`; `generate_brief()` renders only the sections present in its `sections`
dict, assembling the prompt from `_RULE_*` fragments. Two Claude calls/run (news
curation + brief composition).

Invariants not to regress: personal data only in `config.py`; inbox counts via
`labels.get`; inbox list excludes the news label; web-search responses collect text
blocks by `hasattr(b,"text")`; `_TextExtractor` gates URLs on anchor text + blocklist;
weather judged by mm volume; news cost knobs `maxResults=6` / `body[:15000]` (mirror in
`debug_news.py`); TL;DR stays inside the single brief call; English prose with
original-language proper nouns. See `CLAUDE.md` for the full conventions list. Ask to
see the current `morning_brief.py` before editing — it's iterated on frequently.
