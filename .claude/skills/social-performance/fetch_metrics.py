#!/usr/bin/env python3
"""Fetch Instagram + Facebook Page metrics via direct Meta Graph API calls, weekly.

Reads credentials from env vars (set in ~/.claude/settings.json):
  META_FB_PAGE_ACCESS_TOKEN, META_FB_PAGE_ID, META_IG_BUSINESS_ACCOUNT_ID

Usage:
  python3 fetch_metrics.py --year 2026 --month 9

Metric definitions (per user decision on 2026-09-24):
  - Reach: TOTAL (organic + paid). Instagram has a real `reach` metric for this.
    Facebook has NO reach metric in the current Graph API (confirmed by testing
    page_reach, page_impressions_unique, post_impressions, post_reach, page_fans_online,
    page_media_view_unique - all invalid). The closest available proxy is
    `page_video_views` (total video views, includes paid, NOT true unique reach) -
    exposed as facebook.*.reach_proxy with a note. It does not match any true
    "reach" concept; treat it as an approximation only.
  - Impressions per Video: TOTAL impressions (incl. paid) for the period divided
    by the number of videos posted that period (per user correction on 2026-09-24:
    "total impressions divided by number of videos", no organic filtering at all).
    Instagram: account `views` total / video_count. Facebook: `page_video_views`
    (total) / video_count.
  - Engagement Rate: organic engagements (Instagram: `total_interactions` with the
    AD bucket excluded; Facebook: summed likes+comments+shares per post) divided by
    the TOTAL reach (Instagram: `reach`; Facebook: the `page_video_views` proxy).
  - Saves/Share Ratio (Instagram only): saves / shares, using TOTAL (not organic-
    filtered) counts.
  - Followers - TWO separate rows (per user instruction on 2026-09-24):
      * Total Follower Growth = gross new follows for the period (Instagram:
        `follower_count`, limited to Instagram's trailing-30-day API window - null
        outside it. Facebook: `page_daily_follows`, has full history).
      * Net Followers = Total Follower Growth minus unfollows, i.e. end-of-period
        total minus start-of-period total (the net account movement). Facebook:
        computed live via `page_follows` (has full history). Instagram: Instagram's
        API has NO historical daily follower-count endpoint at all (only "today"),
        so instagram.*.followers_start/followers_end are always null here - paste
        them in from existing records when building the report.

Design note: every video/post in the requested date range is listed and its
per-item insights fetched exactly ONCE, in parallel, then bucketed into weeks
in-memory (no redundant re-fetching per period).
"""
import argparse
import calendar
import json
import os
import subprocess
import sys
import time
import urllib.parse
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta

GRAPH = "https://graph.facebook.com/v26.0"
WORKERS = 12


def env(name):
    v = os.environ.get(name)
    if not v:
        sys.exit(f"Missing required env var {name}")
    return v


def curl_json(url, retries=4):
    """Fetch a URL via curl (avoids Python.org's missing-root-certs SSL issue on macOS).
    Retries on transient network failures (curl exit codes), not on API-level errors."""
    last_exc = None
    for attempt in range(retries):
        result = subprocess.run(["curl", "-s", "--retry", "2", url], capture_output=True, text=True)
        if result.returncode != 0:
            last_exc = RuntimeError(f"curl exit {result.returncode}: {result.stderr.strip()}")
            time.sleep(1.5 * (attempt + 1))
            continue
        try:
            data = json.loads(result.stdout)
        except json.JSONDecodeError:
            last_exc = RuntimeError(f"non-JSON response: {result.stdout[:200]!r}")
            time.sleep(1.5 * (attempt + 1))
            continue
        if isinstance(data, dict) and "error" in data:
            raise RuntimeError(data["error"].get("message", str(data["error"])))
        return data
    raise last_exc


def graph_get(path, **params):
    token = env("META_FB_PAGE_ACCESS_TOKEN")
    params = {k: v for k, v in params.items() if v is not None}
    params["access_token"] = token
    url = f"{GRAPH}/{path}?{urllib.parse.urlencode(params)}"
    return curl_json(url)


def graph_get_url(url):
    return curl_json(url)


def total_and_organic(insight_row):
    """Given one insights 'data' row (possibly with a media_product_type breakdown),
    return (total_including_ads, organic_excluding_ads)."""
    tv = insight_row.get("total_value", {})
    total = tv.get("value", 0)
    breakdowns = tv.get("breakdowns")
    if not breakdowns:
        return total, total
    organic = 0
    for b in breakdowns:
        for r in b["results"]:
            if "AD" not in r["dimension_values"]:
                organic += r["value"]
    return total, organic


IG_METRICS = ["views", "reach", "total_interactions", "shares", "saves"]


def ig_metrics(ig_id, since, until):
    """Returns dict with both *_total and *_organic for each IG_METRICS entry."""
    data = graph_get(
        f"{ig_id}/insights",
        metric=",".join(IG_METRICS),
        metric_type="total_value",
        period="day",
        since=since.isoformat(),
        until=until.isoformat(),
        breakdown="media_product_type",
    )
    out = {}
    for row in data["data"]:
        total, organic = total_and_organic(row)
        out[f"{row['name']}_total"] = total
        out[f"{row['name']}_organic"] = organic
    return out


def ig_media_in_range(ig_id, since, until):
    results = []
    data = graph_get(f"{ig_id}/media", fields="id,media_type,media_product_type,timestamp", limit=50)
    while True:
        stop = False
        for m in data.get("data", []):
            ts = date.fromisoformat(m["timestamp"][:10])
            if since <= ts <= until:
                results.append(m)
            elif ts < since:
                stop = True
        if stop:
            break
        nxt = data.get("paging", {}).get("next")
        if not nxt:
            break
        data = graph_get_url(nxt)
    return results


def ig_fetch_all_videos(ig_id, since, until):
    """List every IG video/reel ONCE (just for per-period counting - Impressions per
    Video is now account-total/video_count, no per-item insight calls needed)."""
    media = [m for m in ig_media_in_range(ig_id, since, until) if m.get("media_type") == "VIDEO"]
    return [{"id": m["id"], "date": date.fromisoformat(m["timestamp"][:10])} for m in media]


def ig_bucket_video_stats(videos, since, until):
    subset = [v for v in videos if since <= v["date"] <= until]
    return {"video_count": len(subset)}


def ig_new_followers(ig_id, since, until):
    """Gross new follows summed per day. Instagram's API only allows the trailing 30 days."""
    try:
        data = graph_get(f"{ig_id}/insights", metric="follower_count", period="day",
                          since=since.isoformat(), until=until.isoformat())
        return sum(v["value"] for v in data["data"][0]["values"])
    except RuntimeError as e:
        return None if "last 30 days" in str(e) else 0


def fb_page_metric_values(page_id, metric, since, until):
    data = graph_get(f"{page_id}/insights", metric=metric, period="day",
                      since=since.isoformat(), until=until.isoformat())
    return data["data"][0]["values"] if data.get("data") else []


def fb_follows_start_end(page_id, since, until):
    day_before = since - timedelta(days=1)
    vals = fb_page_metric_values(page_id, "page_follows", day_before, until)
    if not vals:
        return None, None
    return vals[0]["value"], vals[-1]["value"]


def fb_posts_in_range(page_id, since, until):
    results = []
    data = graph_get(f"{page_id}/posts", fields="id,created_time", limit=50)
    while True:
        stop = False
        for p in data.get("data", []):
            ts = date.fromisoformat(p["created_time"][:10])
            if since <= ts <= until:
                results.append(p)
            elif ts < since:
                stop = True
        if stop:
            break
        nxt = data.get("paging", {}).get("next")
        if not nxt:
            break
        data = graph_get_url(nxt)
    return results


def _fb_fetch_one_post(p):
    pid = p["id"]
    result = {
        "id": pid,
        "date": date.fromisoformat(p["created_time"][:10]),
        "organic_engagement": 0,
        "is_video": False,
    }
    try:
        counts = graph_get(pid, fields="likes.summary(true).limit(0),comments.summary(true).limit(0),shares")
        likes = counts.get("likes", {}).get("summary", {}).get("total_count", 0)
        comments = counts.get("comments", {}).get("summary", {}).get("total_count", 0)
        shares = counts.get("shares", {}).get("count", 0)
        result["organic_engagement"] = likes + comments + shares
    except RuntimeError:
        pass
    try:
        att = graph_get(pid, fields="attachments{media_type}")
        attachments = att.get("attachments", {}).get("data", [])
    except RuntimeError:
        attachments = []
    result["is_video"] = any(a.get("media_type") == "video" for a in attachments)
    return result


def fb_fetch_all_posts(page_id, since, until):
    """List + fetch counts/insights for every FB post in range ONCE."""
    posts = fb_posts_in_range(page_id, since, until)
    if not posts:
        return []
    with ThreadPoolExecutor(max_workers=WORKERS) as ex:
        return list(ex.map(_fb_fetch_one_post, posts))


def fb_bucket_post_stats(posts, since, until):
    subset = [p for p in posts if since <= p["date"] <= until]
    organic_engagement = sum(p["organic_engagement"] for p in subset)
    videos = [p for p in subset if p["is_video"]]
    return {
        "post_count": len(subset),
        "organic_engagements": organic_engagement,
        "video_count": len(videos),
    }


def month_bounds(year, month):
    last_day = calendar.monthrange(year, month)[1]
    return date(year, month, 1), date(year, month, last_day)


def mon_sun_weeks(year, month):
    """All Mon-Sun weeks that overlap the month at all (4, 5, or occasionally 6)."""
    first, last = month_bounds(year, month)
    start = first - timedelta(days=first.weekday())
    weeks = []
    cur = start
    while cur <= last:
        w_end = cur + timedelta(days=6)
        weeks.append((cur, w_end))
        cur = w_end + timedelta(days=1)
    return weeks


def clip_period(since, until, today=None):
    """Clip `until` to today (Meta's insights APIs reject ranges entirely/mostly in
    the future). Returns (clipped_since, clipped_until, has_any_data)."""
    today = today or date.today()
    if since > today:
        return since, until, False
    return since, min(until, today), True


def ig_period(ig_id, videos, since, until):
    c_since, c_until, has_data = clip_period(since, until)
    m = ig_metrics(ig_id, c_since, c_until) if has_data else {f"{k}_total": None for k in IG_METRICS} | {f"{k}_organic": None for k in IG_METRICS}
    m.update(ig_bucket_video_stats(videos, since, until))
    m["reach"] = m["reach_total"]  # Absolute Reach row = total (organic + paid)
    m["impressions_per_video"] = (m["views_total"] / m["video_count"]) if m.get("views_total") and m.get("video_count") else None
    m["engagement_rate_pct"] = (m["total_interactions_organic"] / m["reach_total"] * 100) if m.get("reach_total") else None
    m["saves_share_ratio"] = (m["saves_total"] / m["shares_total"]) if m.get("shares_total") else None
    m["total_follower_growth"] = ig_new_followers(ig_id, c_since, c_until) if has_data else None
    m["followers_start"] = None  # Instagram has no historical follower-count API at all
    m["followers_end"] = None
    m["net_followers"] = None
    m["since"], m["until"] = since.isoformat(), until.isoformat()
    if not has_data:
        m["note"] = "period has not started yet"
    elif c_until < until:
        m["note"] = f"partial period - data only through {c_until.isoformat()} (today)"
    return m


def fb_period(page_id, posts, since, until):
    c_since, c_until, has_data = clip_period(since, until)
    out = {}
    if not has_data:
        out.update({"page_video_views": None, "followers_start": None, "followers_end": None, "total_follower_growth": None})
    else:
        out["page_video_views"] = sum(v["value"] for v in fb_page_metric_values(page_id, "page_video_views", c_since, c_until))
        start_f, end_f = fb_follows_start_end(page_id, c_since, c_until)
        out["followers_start"], out["followers_end"] = start_f, end_f
        out["total_follower_growth"] = sum(v["value"] for v in fb_page_metric_values(page_id, "page_daily_follows", c_since, c_until))
    out.update(fb_bucket_post_stats(posts, since, until))
    out["reach_proxy"] = out["page_video_views"]  # NOT true reach - see module docstring
    out["impressions_per_video"] = (out["page_video_views"] / out["video_count"]) if out.get("page_video_views") and out.get("video_count") else None
    out["engagement_rate_pct"] = (out["organic_engagements"] / out["page_video_views"] * 100) if out.get("page_video_views") else None
    out["net_followers"] = (out["followers_end"] - out["followers_start"]) if out.get("followers_start") is not None and out.get("followers_end") is not None else None
    out["since"], out["until"] = since.isoformat(), until.isoformat()
    if not has_data:
        out["note"] = "period has not started yet"
    elif c_until < until:
        out["note"] = f"partial period - data only through {c_until.isoformat()} (today)"
    return out


def build_report(ig_id, page_id, year, month):
    m_start, m_end = month_bounds(year, month)
    weeks = mon_sun_weeks(year, month)
    combined_start, combined_end = weeks[0][0], weeks[-1][1]

    print(f"Fetching IG videos and FB posts for {combined_start}..{combined_end} (fetched once, bucketed in-memory)...", file=sys.stderr)
    all_videos = ig_fetch_all_videos(ig_id, combined_start, combined_end)
    all_posts = fb_fetch_all_posts(page_id, combined_start, combined_end)
    print(f"Got {len(all_videos)} IG videos/reels, {len(all_posts)} FB posts.", file=sys.stderr)

    report = {
        "month": f"{year}-{month:02d}",
        "instagram": {"weeks": [ig_period(ig_id, all_videos, s, e) for s, e in weeks]},
        "facebook": {"weeks": [fb_period(page_id, all_posts, s, e) for s, e in weeks]},
    }
    return report


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--year", type=int, required=True)
    ap.add_argument("--month", type=int, required=True)
    args = ap.parse_args()
    ig_id = env("META_IG_BUSINESS_ACCOUNT_ID")
    page_id = env("META_FB_PAGE_ID")
    report = build_report(ig_id, page_id, args.year, args.month)
    print(json.dumps(report, indent=2, default=str))
