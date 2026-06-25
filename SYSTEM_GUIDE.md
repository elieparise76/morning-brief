# Morning Brief — Complete System Guide

A serverless automation that emails Élie a daily morning brief at **7:30 AM ET on weekdays**
(Mon–Fri). Runs entirely in the cloud — no Mac required, no app open.

This guide has two purposes:
1. **Maintenance** — what to renew, when, and how (tokens, keys, billing).
2. **Context handoff** — paste this whole file to Claude in a new chat if you need help
   and have lost the original conversation. It explains the entire architecture.

*Last updated: June 2026, reflecting the label-based news, starred section, TL;DR,
calendar filtering, weather-volume, and HTML-extraction changes.*

---

## 1. What this system does

Every weekday at 7:30 AM, a cloud job runs and emails you a brief. Current sections,
in order:

0. **In brief (TL;DR)** — a short English prose paragraph at the very top that
   synthesizes ACROSS all sections (cross-cutting things no single section sees:
   a starred email from someone you're meeting today, a tight turnaround between
   events, a deadline due today, a market move touching your holdings). Scales to
   the day: one line on a calm day, 3–5 sentences when busy.
1. **🌤 Weather** — Montréal forecast (conditions, high/low, advice). Judges rain by
   actual **volume in mm**, not just probability, so light drizzle isn't over-reported.
2. **📅 Calendar** — TODAY shows everything; "Coming up" (next 7 days) filters out
   plain routine (recurring work/class blocks) but keeps routine that creates an
   interesting constraint (e.g. work ends 17:00, event at 17:30). Pulls primary +
   shared/subscribed calendars. Bias: include rather than omit.
3. **📬 Inbox** — exact count (total + unread via `labels.get`), then any relevant
   unread email from the last 24h (skipping newsletters/promos).
4. **⭐ À suivre (starred)** — all starred emails (no time filter — a star means
   "still to follow up"), each rendered as a single actionable line. Capped at 15.
   Section is omitted entirely if there are none.
5. **📰 News** — 5–10 *stories* (a story can bundle several source links). **Tries
   your newsletters first** (emails labelled **"News"**); if none, **falls back to a
   web search**. Assumes you already know the headlines — surfaces the *angle*, not
   the recap, synthesizing specifics across outlets. Geographic balance target
   ~25% each: Canada/Quebec, US, International (with explicit Asia inclusion),
   Business/markets. Business bucket is protected (market data is wanted even if "known").
6. **⚡ Action items** — bulleted to-dos pulled from calendar/inbox/starred.

The whole brief is written in **English** (Claude's prose); proper nouns and event
titles stay in their original language.

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
      ├─ OpenWeatherMap API  → weather (incl. actual rain/snow mm volume)
      ├─ Google Calendar API → primary + shared/subscribed calendars
      ├─ Gmail API           → inbox counts + relevant emails + starred + "News"-labelled newsletters
      ├─ Anthropic API       → curates news (own call) + generates the final HTML brief
      │                        (Claude Sonnet 4.6; web search only on news fallback)
      ▼
Gmail API (send) → emails the finished brief to you
      │
      ▼
Your phone buzzes (Gmail push notification)
```

**Why cron-job.org instead of GitHub's own schedule?** GitHub's cron is unreliable
(runs late, sometimes skips). cron-job.org fires on time and supports real timezones,
so it handles the daylight-saving switch automatically.

> **Note on triggers:** the workflow has BOTH a `repository_dispatch` trigger (fired by
> cron-job.org — the primary) AND a backup GitHub `schedule:` cron (`30 11 * * 1-5`).
> The two can both fire; cron-job.org is the reliable one. If you ever see duplicate
> briefs, remove the `schedule:` block from the workflow.

---

## 3. Accounts & tools you signed up for

| Service | What it's for | Login / URL | Cost |
|---|---|---|---|
| **GitHub** | Hosts the code + runs the job (GitHub Actions) | github.com/elieparise76/morning-brief | Free |
| **cron-job.org** | Triggers the job at 7:30 AM daily | cron-job.org | Free |
| **Anthropic Console** | Claude API (news curation + brief generation) | console.anthropic.com | ~$1–4/month |
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

> **Reminder already set:** a recurring Google Calendar event "🔑 Renew GitHub token
> (Morning Brief)" fires every 90 days, ~3 days before expiry, with the renewal steps
> in its description.
>
> **Tip:** enable a **spend alert** in Anthropic Console (Billing → set monthly limit +
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
  (note: **api.**github.com — omitting the `api.` prefix → 422 error)
- **Method:** POST
- **Headers:**
  - `Accept: application/vnd.github+json`
  - `Authorization: Bearer <github token>`
  - `Content-Type: application/json`
- **Body:** `{"event_type": "morning-brief"}`
- **Schedule:** currently set 7-days-a-week, 7:30, timezone **America/Toronto**
  (the workflow's backup cron is Mon–Fri only, but cron-job.org drives it daily)

---

## 7. Configuration details inside morning_brief.py

| Setting | Current value | Where to change |
|---|---|---|
| Timezone | America/Toronto | `MONTREAL_TZ` constant near top |
| Calendars | primary + 3 shared IDs | `calendar_ids` list in `fetch_calendar_events()` |
| News source | Gmail label **"News"** (replaced sender list) | `query` in `fetch_news_from_newsletters()` |
| Newsletter lookback | last 18 hours | `since` in `fetch_news_from_newsletters()` |
| Per-newsletter text cap | 25,000 chars | `body[:25000]` in `fetch_news_from_newsletters()` |
| Inbox relevant-email lookback | last 24 hours | `since` in `fetch_emails()` |
| Inbox counts | exact via `labels.get` on INBOX | `fetch_emails()` |
| Starred cap | 15, no time filter | `fetch_starred()` |
| News count target | 5–10 stories, ~25% per geo bucket | `news_prompt` in `fetch_news_from_newsletters()` |
| Claude model | claude-sonnet-4-6 | all `client.messages.create()` calls |
| Max tokens (news call) | 4000 | `fetch_news_from_newsletters()` |
| Max tokens (main brief) | 8000 | `generate_brief()` |
| Language | English prose, original-language proper nouns | `system` string in `generate_brief()` |
| Web search | fallback only (no newsletters) | `fetch_news_from_web()` |

### The shared calendar IDs (in addition to "primary")
```
REMOVED_CALENDAR_ID
REMOVED_CALENDAR_ID
REMOVED_CALENDAR_ID
```

### News HTML extraction (important)
The `_TextExtractor` class strips newsletter HTML to text. Key behavior: it keeps a
link's URL **only if the link has visible anchor text** (drops bare image/icon/spacer
tracking links that otherwise eat the character budget), drops boilerplate URLs
(unsubscribe, social, preferences — see `_URL_BLOCKLIST`), and collapses empty table
cells. This is why the per-newsletter cap could be raised to 25k without ballooning cost.

---

## 8. Cost breakdown

| Component | Cost |
|---|---|
| GitHub Actions | Free (uses ~20 of 2,000 free min/month) |
| cron-job.org | Free |
| OpenWeatherMap | Free |
| Google APIs | Free |
| Anthropic — news call + main brief call (2 calls/run) | ~$0.05–0.15/run |
| Anthropic — web-search fallback days | ~$0.05–0.10/run extra |
| **Total** | **~$1–4/month** (depends on newsletter volume) |

> Cost note: the news section and the main brief are **two separate Claude calls**.
> Most additions to the brief fold into the existing main call (near-zero extra cost);
> only adding NEW separate `messages.create()` calls materially moves the bill.

---

## 9. Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| No brief arrived at all | GitHub token expired (90 days) | Renew token, update cron-job.org (§5a) |
| No brief, token is fine | Anthropic credits ran out | Top up in console |
| News empty / web fallback when you had newsletters | Newsletter arrived after 7:30, OR not labelled "News" | Check the Gmail filter applies "News"; widen lookback |
| News missing a bucket (e.g. business) | Content truncated or buried in link noise | Run `debug_news.py` to see what Claude receives; check the 25k cap and extraction |
| 422 error in cron-job.org | URL missing `api.` prefix, or bad body | URL = `api.github.com/...`, body = `{"event_type":"morning-brief"}` |
| 401/403 in cron-job.org | Token wrong or lacks Contents:write | Regenerate token with correct permission |
| Calendar missing shared events | OAuth token can't see that calendar | Confirm subscribed at account level; check Actions log for "could not read calendar" warnings |
| Brief cut off mid-HTML | Main brief hit token ceiling | Raise `max_tokens` in `generate_brief()` (currently 8000) |
| Rain over-reported | (Fixed) — now judges by mm volume, not just % chance | n/a |
| Email count wrong | (Fixed) — uses `labels.get` for exact INBOX counts | n/a |
| `ServerToolUseBlock has no attribute text` | (Fixed) — code collects text blocks by `hasattr` | n/a |

---

## 10. Files in the repo

```
morning-brief/
├── .github/workflows/morning_brief.yml   ← workflow (repository_dispatch + backup cron)
├── morning_brief.py                       ← main script (all logic)
├── debug_news.py                          ← diagnostic: dumps the raw news text Claude receives
├── get_tokens.py                          ← one-time Google auth helper (run locally, do NOT commit)
├── .gitignore                             ← keeps token files out of the repo
├── README.md                              ← original setup guide
├── CRON_SETUP.md                          ← cron-job.org setup guide
└── SYSTEM_GUIDE.md                        ← this file
```

---

## 11. For Claude (context handoff)

If Élie is pasting this to you in a new chat: this is a working serverless morning-brief
system. Architecture in §2; all logic is in `morning_brief.py` (single file). Key
functions: `fetch_weather` (includes rain/snow mm volume), `fetch_calendar_events`
(primary + shared calendars, with a today-vs-coming-up routine filter applied in the
main prompt), `fetch_emails` (exact counts via `labels.get`), `fetch_starred`,
`fetch_news` → `fetch_news_from_newsletters` (pulls Gmail label "News", extracts via
`_TextExtractor`, caps 25k/newsletter, own Claude call, `max_tokens=4000`) +
`fetch_news_from_web` (web-search fallback), `generate_brief` (main HTML call,
`max_tokens=8000`, English prose), `send_email`, `main`.

Known prior fixes (do NOT regress these):
- Inbox counts use `labels.get` on INBOX, not `resultSizeEstimate`.
- Web-search responses collect text blocks via `hasattr(b, "text")`, not `content[0].text`.
- News selection: business bucket is explicitly protected; geographic balance ~25%/bucket
  with Asia called out; "give me the angle not the headline" applies LESS to markets.
- Weather judged by mm volume, not just % chance.
- `_TextExtractor` keeps URLs only for links with anchor text + a `_URL_BLOCKLIST`;
  this is what keeps the 25k cap affordable. Don't revert to keeping all links.
- TL;DR ("In brief") and the whole brief are produced in ONE main call (Tier A cost) —
  don't split into extra calls without reason.

There are TWO Claude calls per run (news curation + main brief). Ask to see the current
`morning_brief.py` before editing — Élie iterates on it frequently.

A diagnostic script `debug_news.py` dumps exactly what Claude receives as news (run it
locally with the Gmail token) — use it whenever the news section misbehaves.
