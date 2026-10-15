# pb-social-performance

Organic social performance reporting for Policybazaar/Paisabazaar, built as a Claude Code skill. Pulls metrics directly from each platform's official API — no third-party analytics tool in the data path.

## What's here

- `.claude/skills/social-performance/SKILL.md` — the skill definition. Invoke with `/social-performance` in Claude Code.
- `.claude/skills/social-performance/fetch_metrics.py` — fetches organic Instagram + Facebook Page metrics via direct Meta Graph API calls (see the file's docstring for exact metric definitions: what's organic vs. total, and known API gaps).

## Platforms

| Platform | Status |
|---|---|
| Facebook Page | ✅ Working — direct Graph API |
| Instagram Business Account | ✅ Working — direct Graph API |
| YouTube (Policybazaar UAE, Paisabazaar UAE) | ✅ Credentials connected (Views, Average View Duration, Subscriber Growth) — not yet wired into the skill script |
| LinkedIn Company Page | 🔄 In progress — Community Management API access requested from LinkedIn, pending their review |

## Setup

Credentials (Meta App ID/Secret, Page Access Token, IG Business Account ID, YouTube OAuth client/refresh token) are stored as environment variables in `~/.claude/settings.json`, **not** in this repo. See the docstrings in `fetch_metrics.py` for the exact env var names expected.

## Known limitations

- Instagram's API has no historical daily follower-count endpoint — only "today's" snapshot. Historical Followers-at-Start/End must be supplied manually when generating a report for past periods.
- Facebook's API exposes no page-level "reach" metric in the current API version; reports use `page_video_views` as the closest available proxy, not true unique reach.
- YouTube Impressions/CTR require the separate async YouTube Reporting API (batch CSV reports, 1-2 day latency) rather than the instant YouTube Analytics API — not yet implemented.
