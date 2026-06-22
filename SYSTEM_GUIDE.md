# Morning Brief — Complete System Guide

A serverless automation that emails Élie a daily morning brief at **7:30 AM ET on weekdays**
(Mon–Fri). Runs entirely in the cloud — no Mac required, no app open.

This guide has two purposes:
1. **Maintenance** — what to renew, when, and how (tokens, keys, billing).
2. **Context handoff** — paste this whole file to Claude in a new chat if you need help
   and have lost the original conversation. It explains the entire architecture.

---

## 1. What this system does

Every weekday at 7:30 AM, a cloud job runs and emails you a brief with four sections:

1. **🌤 Weather** — Montréal forecast (current conditions, high/low, advice).
2. **📅 Calendar** — today's events + notable items in the next 7 days, pulled from
   your primary calendar **plus two shared/subscribed calendars**.
3. **📬 Inbox** — exact count of inbox emails (total + unread), then any relevant
   unread email from the last 24h (skipping newsletters/promos).
4. **📰 News** — 5–10 curated stories. **Tries your newsletters first** (Globe and Mail,
   NYT, Economist, Guardian); if none have arrived, **falls back to a web search**.
   Selection is merit-based, with article links.

---

## 2. Architecture (how it actually works)

```
cron-job.org  (fires at 7:30 AM America/Toronto, handles EST/EDT automatically)
      │
      │  POST to GitHub API (repository_dispatch, event_type: "morning-brief")
      ▼
GitHub Actions  (.github/workflows/morning_brief.yml)
      │
      │  runs on Ubuntu, installs Python deps
      ▼
morning_brief.py
      │
      ├─ OpenWeatherMap API  → weather
      ├─ Google Calendar API → primary + 2 shared calendars
      ├─ Gmail API           → inbox counts + relevant emails + newsletters
      ├─ Anthropic API       → curates news + generates the final HTML brief
      │                        (Claude Sonnet 4.6; web search only on fallback)
      ▼
Gmail API (send) → emails the finished brief to you
      │
      ▼
Your phone buzzes (Gmail push notification)
```

**Why cron-job.org instead of GitHub's own schedule?** GitHub's cron is unreliable
(runs late, sometimes skips). cron-job.org fires on time and supports real timezones,
so it handles the daylight-saving switch for you. GitHub's `schedule:` block was
removed to avoid duplicate runs (and duplicate API charges).

---

## 3. Accounts & tools you signed up for

| Service | What it's for | Login / URL | Cost |
|---|---|---|---|
| **GitHub** | Hosts the code + runs the job (GitHub Actions) | github.com/elieparise76/morning-brief | Free |
| **cron-job.org** | Triggers the job at 7:30 AM daily | cron-job.org | Free |
| **Anthropic Console** | Claude API (news curation + brief generation) | console.anthropic.com | ~$0.50–2/month |
| **OpenWeatherMap** | Weather data | openweathermap.org | Free tier |
| **Google Cloud** | OAuth credentials for Gmail + Calendar | console.cloud.google.com | Free |

---

## 4. Secrets stored in GitHub

Repo → **Settings → Secrets and variables → Actions**:

| Secret name | What it is | Expires? |
|---|---|---|
| `ANTHROPIC_API_KEY` | Claude API key | No (unless you rotate it) |
| `OPENWEATHER_API_KEY` | Weather API key | No |
| `RECIPIENT_EMAIL` | Where the brief is sent | No |
| `GMAIL_TOKEN_JSON` | Google OAuth token (Gmail read+send) | Refreshes automatically |
| `GCAL_TOKEN_JSON` | Google OAuth token (Calendar read) | Refreshes automatically |

There is also a **GitHub Personal Access Token** stored in **cron-job.org** (not in
GitHub secrets) — this is the one with the 90-day expiry. See the maintenance table below.

---

## 5. MAINTENANCE SCHEDULE ⚠️

This is the part to actually keep track of.

| Item | Expires | What happens if it lapses | How to renew |
|---|---|---|---|
| **GitHub Personal Access Token** (in cron-job.org) | **90 days** ← you set this | cron-job.org gets 401, job stops firing, no brief | See §5a below |
| **Anthropic API credits** | When balance hits $0 | Job crashes at the Claude step, no brief | Top up at console.anthropic.com → Billing |
| **Google OAuth tokens** | Don't expire if used regularly | Would only break if unused 6+ months or you revoke access | Re-run `get_tokens.py` locally, update the two GitHub secrets |
| **OpenWeatherMap key** | No expiry | — | — |

> **Tip:** Set a calendar reminder ~3 days before the GitHub token's 90-day expiry.
> Also enable a **spend alert** in Anthropic Console (Billing → set monthly limit +
> email alert) so you're warned before credits run out.

### 5a. Renewing the GitHub Personal Access Token (every 90 days)

1. Go to https://github.com/settings/tokens?type=beta (Fine-grained tokens)
2. Either regenerate the existing token or create a new one with the same settings:
   - **Repository access:** Only `morning-brief`
   - **Permissions:** Repository → **Contents: Read and write**
   - **Expiration:** 90 days (or set longer / no-expiration to reduce maintenance)
3. Copy the new token.
4. Go to **cron-job.org** → your "Morning Brief Trigger" job → **Headers** →
   update the `Authorization` header value to:
   ```
   Bearer YOUR_NEW_TOKEN
   ```
   (Keep the word `Bearer` and the space.)
5. Hit **Run now** in cron-job.org to confirm it triggers a run in GitHub Actions.

> Consider setting the token to **no expiration** next time to avoid this chore —
> the only tradeoff is slightly lower security if the token ever leaked.

---

## 6. cron-job.org configuration (for reference)

- **URL:** `https://api.github.com/repos/elieparise76/morning-brief/dispatches`
  (note: **api.**github.com — a common mistake is omitting the `api.` prefix → 422 error)
- **Method:** POST
- **Headers:**
  - `Accept: application/vnd.github+json`
  - `Authorization: Bearer <github token>`
  - `Content-Type: application/json`
- **Body:** `{"event_type": "morning-brief"}`
- **Schedule:** Mon–Fri, 7:30, timezone **America/Toronto**

---

## 7. Configuration details inside morning_brief.py

| Setting | Current value | Where to change |
|---|---|---|
| Timezone | America/Toronto | `MONTREAL_TZ` constant near top |
| Calendars | primary + 2 shared IDs | `calendar_ids` list in `fetch_calendar_events()` |
| Newsletter senders | globeandmail, globeandmailnewsletters, economist.com, nytimes, nytdirect, theguardian.com | `sender_query` in `fetch_news_from_newsletters()` |
| Newsletter lookback | last 18 hours | `since` in `fetch_news_from_newsletters()` |
| Inbox relevant-email lookback | last 24 hours | `since` in `fetch_emails()` |
| News count target | 5–10 stories | prompts in the news functions |
| Claude model | claude-sonnet-4-6 | all `client.messages.create()` calls |
| Max tokens (main brief) | 4000 | `generate_brief()` |
| Web search | fallback only | `fetch_news_from_web()` |

### The two shared calendar IDs
```
REMOVED_CALENDAR_ID
REMOVED_CALENDAR_ID
```

---

## 8. Cost breakdown

| Component | Cost |
|---|---|
| GitHub Actions | Free (uses ~20 of 2,000 free min/month) |
| cron-job.org | Free |
| OpenWeatherMap | Free |
| Google APIs | Free |
| Anthropic — newsletter days | ~$0.03–0.05/run |
| Anthropic — web-search fallback days | ~$0.05–0.10/run |
| **Total** | **~$0.50–2.00/month** |

---

## 9. Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| No brief arrived at all | GitHub token expired (90 days) | Renew token, update cron-job.org (§5a) |
| No brief, token is fine | Anthropic credits ran out | Top up in console |
| Brief arrived but news is empty/web fallback when you had newsletters | Newsletter arrived after 7:30, or sender not matched | Widen lookback window, or add sender to `sender_query` |
| 422 error in cron-job.org | URL missing `api.` prefix, or bad body | Check URL = `api.github.com/...`, body = `{"event_type":"morning-brief"}` |
| 401/403 in cron-job.org | Token wrong or lacks Contents:write | Regenerate token with correct permission |
| Calendar missing shared events | OAuth token can't see that calendar | Confirm calendar is subscribed at account level; check Actions log for "could not read calendar" warnings |
| Email count looks wrong | (Fixed) — uses labels.get for exact INBOX counts | n/a |
| `ServerToolUseBlock has no attribute text` | (Fixed) — code now collects only text blocks | n/a |

---

## 10. Files in the repo

```
morning-brief/
├── .github/workflows/morning_brief.yml   ← workflow (repository_dispatch trigger)
├── morning_brief.py                       ← main script (all logic)
├── get_tokens.py                          ← one-time Google auth helper (run locally, do NOT commit)
├── .gitignore                             ← keeps token files out of the repo
├── README.md                              ← original setup guide
├── CRON_SETUP.md                          ← cron-job.org setup guide
└── SYSTEM_GUIDE.md                        ← this file
```

---

## 11. For Claude (context handoff)

If Élie is pasting this to you in a new chat: this is a working serverless morning-brief
system. The architecture is in §2, the code lives in `morning_brief.py` (single file, all
functions: `fetch_weather`, `fetch_calendar_events`, `fetch_emails`, `fetch_news` +
`fetch_news_from_newsletters` + `fetch_news_from_web`, `generate_brief`, `send_email`,
`main`). It uses Google OAuth tokens (refresh-token based), the Anthropic API
(Sonnet 4.6, web search on fallback only), OpenWeatherMap, GitHub Actions triggered by
cron-job.org via `repository_dispatch`. Known prior fixes: inbox counts use `labels.get`
(not resultSizeEstimate); web-search responses must collect text blocks by `hasattr(b,
"text")` not `content[0].text`; main brief uses `max_tokens=4000` to avoid truncation.
Ask to see the current `morning_brief.py` before editing, since Élie may have changed it.
