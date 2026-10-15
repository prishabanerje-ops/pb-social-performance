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

python3 "/Users/poonambachiyani/Documents/FB & IG/.claude/skills/social-performance/fetch_metrics.py" --year <YYYY> --month <M>



This single call fetches BOTH the target month and the prior month (as the comparison baseline) — do not call it twice. It prints progress to stderr and the full JSON report to stdout. It takes a few minutes (it fetches every IG video and FB post in the combined date range, in parallel, once).

The JSON has this shape:
{
"month": "2026-08", "compare_month": "2026-07",
"instagram": { "overall": {...}, "compare_overall": {...}, "weeks": [...], "compare_weeks": [...] },
"facebook":  { "overall": {...}, "compare_overall": {...}, "weeks": [...], "compare_weeks": [...] }
}


`weeks` / `compare_weeks` are real Mon–Sun weeks overlapping that calendar month — **the count varies (4, 5, or occasionally 6) depending on how the month's days fall against Monday**. Do not force them into a fixed 4 columns; render however many weeks each month actually produced. A week can legitimately appear in both months' week lists if it straddles the boundary (e.g. the week of Jul 27–Aug 2 is July's last week AND August's first week) — that's correct, not a bug.

All Instagram and Facebook metrics in the JSON (views, reach, engagement, shares, impressions/video, watch time) are **organic only** — ad-driven views/reach/engagement have already been excluded via the `media_product_type` breakdown (Instagram) or the organic/paid post-video-view split (Facebook). Do not re-derive or second-guess these numbers.

`instagram.*.new_followers` will be `null` whenever the period falls outside Instagram's trailing-30-day API window (which is most periods, since Instagram cannot report historical daily follower counts at all). `instagram.*.followers_start` / `followers_end` are ALWAYS `null` from the script — Instagram's API has no historical follower-count endpoint whatsoever. You must fill these from what the user gave you in Step 1.

## Step 3 — Compute the derived fields per period

For every period object (Instagram and Facebook, overall + each week, target + compare):

- **Engagement Rate %** — Instagram: already computed by the script as `engagement_rate_pct` (organic total_interactions ÷ organic reach × 100). Facebook: **always report "N/A"** for this row. Confirmed there is no organic-only reach/impressions metric available for general Facebook posts (the organic/paid split only exists for video views specifically, and the page-level breakdown trick that works for Instagram returns "The breakdown value is invalid" on Facebook's page metrics) — do not substitute `post_media_view` or organic video views as a stand-in denominator.
- **Net New Followers Growth %** = `new_followers ÷ followers_start × 100`. For Instagram periods where `followers_start` is null (from the user) or `new_followers` is null (outside the 30-day window), report "N/A" — do not estimate.
- **Loyalty/Retention Rate %** = `(followers_end − new_followers) ÷ followers_start × 100`. Facebook: the script already computes this (`retention_rate_pct`) since Facebook's `page_follows` has full history. Instagram: compute it yourself using the user-supplied `followers_start`/`followers_end` plus the script's `new_followers` (if available) — if any of the three inputs is missing, report "N/A".
- **% comparisons** (the `(56%)`-style figures next to each number): compare each week/overall value against the **same week number in the compare month** (e.g. August Week 2 vs July Week 2), as `(current − prior) ÷ prior × 100`. If the compare month doesn't have a matching week number (e.g. an August Week 6 with no July Week 6), show "N/A" for that comparison.
- **Total Followers** row: Instagram — use the user-supplied numbers directly (there is no live value except "today", which only applies to the in-progress current week). Facebook — use `followers_end` from the script for each period.

## Step 4 — Render the report

Two markdown tables, Instagram first then Facebook, matching the original column layout (Overall for compare month, KPI targets, one column per week actually returned, Overall for target month). Round seconds/percentages to 1-2 decimal places for readability; keep raw counts as integers. Do not fabricate a number for any field you don't have — write "N/A" and, if it's a recurring gap (like Instagram's historical follower counts), you can footnote why once at the bottom of the report rather than repeating the caveat in every cell.
