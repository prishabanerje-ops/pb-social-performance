---
name: social-performance
description: Generate the monthly Instagram + Facebook organic performance report (Views, Reach, Engagement Rate, Watch Time, Follower Growth/Retention, etc.) for policybazaaruae / Policybazaar.ae, pulling live data directly from the Meta Graph API. Invoke with /social-performance.
---

# Social Performance Report

Produces the two-table monthly report (Instagram, then Facebook) in this exact shape:

| Insta | July Overall | Aug KPIs | Week 1 | Week 2 | ... | Aug Overall |
|---|---|---|---|---|---|---|
| Total Views | ... | ... | ... | ... | | ... |
| ... | | | | | | |

(and the same structure for FB, with its extra AVT Long/Short Video rows.)

## Step 1 — Ask the user

Before running anything, ask:

1. **Which month** to report on (e.g. "August 2026"). Default to last fully-completed calendar month if they don't say.
2. **This month's KPI targets** for each metric row (the "Aug KPIs" column) — these are never fetched, always user-supplied fresh each run. If they don't have new targets, ask if last month's report's targets should be reused, and if so where that report lives.
3. **Historical Instagram follower counts** for the target month and comparison month (Instagram's API cannot supply these — only Facebook's API can). For each period you'll need `followers_start` / `followers_end`:
   - Target month overall, compare month overall
   - Each week of the target month, each week of the compare month
   If the user doesn't have all of these, proceed with whatever they can give you and leave the rest blank in the report (mark "N/A" — do not guess or interpolate).

## Step 2 — Run the fetch script

