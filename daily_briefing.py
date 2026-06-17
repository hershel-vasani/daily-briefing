#!/usr/bin/env python3
"""Daily morning briefing — weather, calendar, news, markets, and sports scores."""

import json
import os
import re
import sys
import subprocess
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta

SKIP_CALENDAR = os.environ.get("BRIEFING_SKIP_CALENDAR") == "1"


def fetch(url, timeout=10):
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.read().decode("utf-8", errors="replace")
    except Exception:
        pass
    try:
        result = subprocess.run(
            ["curl", "-sL", "--max-time", str(timeout), "-A", "Mozilla/5.0", url],
            capture_output=True, text=True, timeout=timeout + 5
        )
        return result.stdout if result.returncode == 0 else None
    except Exception:
        return None


def strip_html(text):
    text = re.sub(r'<[^>]+>', ' ', text)
    text = (text.replace('&amp;', 'and').replace('&lt;', '<').replace('&gt;', '>')
                .replace('&quot;', '"').replace('&#39;', "'").replace('&nbsp;', ' '))
    return re.sub(r'\s+', ' ', text).strip()


def truncate_words(text, max_words=60):
    words = text.split()
    if len(words) <= max_words:
        return text
    return ' '.join(words[:max_words]) + '...'


# ---------------------------------------------------------------------------
# Weather
# ---------------------------------------------------------------------------

def get_weather():
    data = fetch("https://wttr.in/48226?format=j1")
    if not data:
        return "Weather information is currently unavailable."
    try:
        w = json.loads(data)
        cur = w["current_condition"][0]
        today = w["weather"][0]
        temp = cur["temp_F"]
        desc = cur["weatherDesc"][0]["value"]
        feels = cur["FeelsLikeF"]
        high = today["maxtempF"]
        low = today["mintempF"]
        rain_chance = max(int(h.get("chanceofrain", 0)) for h in today["hourly"])
        snow_chance = max(int(h.get("chanceofsnow", 0)) for h in today["hourly"])

        text = (
            f"Detroit weather: It's currently {temp} degrees and {desc}, "
            f"feeling like {feels}. Today's high will be {high}, low {low}."
        )
        if snow_chance > 30:
            text += f" There's a {snow_chance} percent chance of snow."
        elif rain_chance > 30:
            text += f" There's a {rain_chance} percent chance of rain."
        return text
    except Exception:
        return "Weather data is unavailable right now."


# ---------------------------------------------------------------------------
# Calendar (Apple Calendar via AppleScript)
# ---------------------------------------------------------------------------

def get_calendar():
    script = """
    tell application "Calendar"
        set today to current date
        set startOfDay to today - (time of today)
        set endOfDay to startOfDay + (24 * 60 * 60 - 1)
        set output to {}
        repeat with cal in calendars
            set evts to (every event of cal whose start date >= startOfDay and start date <= endOfDay)
            repeat with e in evts
                try
                    set t to start date of e
                    set h to hours of t
                    set m to minutes of t
                    set ap to "AM"
                    if h >= 12 then
                        set ap to "PM"
                        if h > 12 then set h to h - 12
                    end if
                    if h = 0 then set h to 12
                    set mins to text -2 thru -1 of ("0" & (m as string))
                    set label to (h as string) & ":" & mins & " " & ap & " " & (summary of e)
                    set end of output to label
                on error
                    set end of output to (summary of e)
                end try
            end repeat
        end repeat
        return output
    end tell
    """
    try:
        result = subprocess.run(
            ["osascript", "-e", script], capture_output=True, text=True, timeout=15
        )
        raw = result.stdout.strip()
        if not raw or raw in ("{}", ""):
            return "You have no calendar events scheduled for today."
        events = [e.strip() for e in raw.split(",") if e.strip()]
        if not events:
            return "You have no calendar events scheduled for today."
        joined = ". ".join(events)
        return f"On your calendar today: {joined}."
    except Exception:
        return "Calendar is unavailable right now."


# ---------------------------------------------------------------------------
# News (RSS feeds with per-headline summaries)
# ---------------------------------------------------------------------------

def fetch_article_summary(url, max_words=75):
    """Fetch article page and extract a clean recap.

    Strategy:
    1. og:description meta tag — always clean prose, no parsing noise.
    2. <article>/<main> body paragraphs — scoped to avoid nav/JS pollution.
    3. Return "" if both fail (caller falls back to RSS blurb).
    """
    html = fetch(url, timeout=8)
    if not html:
        return ""

    # 1. og:description / meta description — always clean prose, purpose-built summary.
    # Search only within <head> to avoid false matches in body script blocks.
    head_m = re.search(r'<head[^>]*>(.*?)</head>', html, re.DOTALL | re.IGNORECASE)
    head = head_m.group(1) if head_m else html

    # Flexible two-pass: find any <meta> tag that has both a description key and content.
    for meta_block in re.findall(r'<meta\s[^>]+>', head, re.IGNORECASE):
        is_desc = re.search(
            r'(?:property=["\']og:description["\']|name=["\']description["\'])',
            meta_block, re.IGNORECASE
        )
        if not is_desc:
            continue
        content_m = re.search(r'content=["\']([^"\']{40,})["\']', meta_block, re.IGNORECASE)
        if content_m:
            desc = strip_html(content_m.group(1)).strip()
            if len(desc.split()) >= 20:
                return truncate_words(desc, max_words)

    # 2. Article body paragraphs only
    return _extract_body_paragraphs(html, max_words)


def _extract_body_paragraphs(html, max_words):
    """Extract clean paragraphs from <article> or <main>, avoiding JS/nav noise."""
    # Narrow to article or main element first
    scoped = html
    for tag in ("article", "main"):
        m = re.search(rf'<{tag}[^>]*>(.*?)</{tag}>', html, re.DOTALL | re.IGNORECASE)
        if m:
            scoped = m.group(1)
            break

    paragraphs = re.findall(r'<p[^>]*>(.*?)</p>', scoped, re.DOTALL | re.IGNORECASE)
    collected, word_count = [], 0
    for p in paragraphs:
        text = strip_html(p).strip()
        words = text.split()
        # skip nav blurbs, JS, CSS, sharing bars, bylines, and image captions
        if len(words) < 10:
            continue
        if '{' in text or text.lstrip().startswith('#'):
            continue
        first = words[0].lower()
        if first in ('share', 'watch', 'listen', 'read', 'follow'):
            continue
        if any(x in text for x in ('Getty Images', 'AP Photo', 'Reuters/', 'AFP/')):
            continue
        collected.append(text)
        word_count += len(words)
        if word_count >= max_words:
            break
    return truncate_words(' '.join(collected), max_words) if collected else ""


def rss_headlines(url, count=3):
    """Return list of (title, rss_desc, article_url) tuples from an RSS feed."""
    data = fetch(url)
    if not data:
        return []
    try:
        root = ET.fromstring(data)
        items = []
        for item in root.findall(".//item")[:count * 2]:
            t = item.find("title")
            d = item.find("description")
            lnk = item.find("link")
            if t is not None and t.text:
                clean_title = (t.text.strip()
                               .replace("&amp;", "and").replace("&lt;", "<").replace("&gt;", ">"))
                if clean_title and "[" not in clean_title[:3]:
                    rss_desc = ""
                    if d is not None and d.text:
                        rss_desc = truncate_words(strip_html(d.text), 75)
                    article_url = lnk.text.strip() if lnk is not None and lnk.text else ""
                    items.append((clean_title, rss_desc, article_url))
            if len(items) == count:
                break
        return items
    except Exception:
        return []


def format_stories(stories):
    """Format stories with a full recap: try fetching the article, fall back to RSS desc."""
    parts = []
    for title, rss_desc, article_url in stories:
        recap = ""
        if article_url:
            recap = fetch_article_summary(article_url)
        if not recap:
            recap = rss_desc  # fallback to RSS blurb
        if recap:
            parts.append(f"{title}. {recap}")
        else:
            parts.append(title)
    result = ". ".join(parts) + "."
    return re.sub(r'\.{2,}', '.', result)  # collapse "..", "..." for clean TTS


def get_news():
    parts = []

    local_feeds = [
        "https://www.clickondetroit.com/arc/outboundfeeds/rss/category/news/local/?outputType=xml",
        "https://www.michiganradio.org/news.rss",
        "https://www.wxyz.com/index.rss",
    ]
    local = []
    for feed in local_feeds:
        local += rss_headlines(feed, 3)
        if len(local) >= 3:
            break
    if local:
        parts.append("Local Detroit headlines: " + format_stories(local[:3]))

    national_feeds = [
        "https://rss.nytimes.com/services/xml/rss/nyt/HomePage.xml",
        "https://feeds.npr.org/1001/rss.xml",
        "https://www.theguardian.com/us-news/rss",
    ]
    national = []
    for feed in national_feeds:
        national += rss_headlines(feed, 3)
        if len(national) >= 3:
            break
    if national:
        parts.append("National headlines: " + format_stories(national[:3]))

    world_feeds = [
        "https://feeds.bbci.co.uk/news/world/rss.xml",
        "https://www.theguardian.com/world/rss",
    ]
    world = []
    for feed in world_feeds:
        world += rss_headlines(feed, 3)
        if len(world) >= 3:
            break
    if world:
        parts.append("World headlines: " + format_stories(world[:3]))

    return " ".join(parts) if parts else "News headlines are unavailable right now."


# ---------------------------------------------------------------------------
# Markets (Yahoo Finance, no API key needed)
# ---------------------------------------------------------------------------

def get_markets():
    indices = [
        ("%5EGSPC", "S and P 500"),
        ("%5EDJI",  "Dow Jones"),
        ("%5EIXIC", "NASDAQ"),
    ]
    results = []
    for symbol, name in indices:
        data = fetch(
            f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?interval=1d&range=5d",
            timeout=12,
        )
        if not data:
            continue
        try:
            j = json.loads(data)
            quote = j["chart"]["result"][0]["indicators"]["quote"][0]
            closes = [c for c in quote["close"] if c is not None]
            if len(closes) < 2:
                continue
            prev, last = closes[-2], closes[-1]
            change = last - prev
            pct = (change / prev) * 100
            direction = "up" if change >= 0 else "down"
            results.append(
                f"{name} {direction} {abs(pct):.1f} percent, closing at {last:,.0f}"
            )
        except Exception:
            continue

    if not results:
        return "Market data is unavailable right now."
    return "At the last market close: " + ". ".join(results) + "."


# ---------------------------------------------------------------------------
# Sports scores (ESPN public API, no key needed)
# ---------------------------------------------------------------------------

DETROIT_PRO = [
    ("baseball",   "mlb",  "DET", "Tigers"),
    ("football",   "nfl",  "DET", "Lions"),
    ("basketball", "nba",  "DET", "Pistons"),
    ("hockey",     "nhl",  "DET", "Red Wings"),
]

NATIONAL_LEAGUES = [
    ("football",   "nfl"),
    ("basketball", "nba"),
    ("baseball",   "mlb"),
    ("hockey",     "nhl"),
]

MSU_LEAGUES = [
    ("basketball", "mens-college-basketball"),
    ("football",   "college-football"),
]


def espn_scoreboard(sport, league, date_str, extra=""):
    url = (
        f"https://site.api.espn.com/apis/site/v2/sports/{sport}/{league}"
        f"/scoreboard?dates={date_str}{extra}"
    )
    return fetch(url)


def parse_game(competition):
    """Return (home_abbr, away_abbr, score_str, home_name, away_name) or None if not final."""
    try:
        if competition["status"]["type"]["name"] != "STATUS_FINAL":
            return None
        competitors = competition["competitors"]
        home = next(c for c in competitors if c["homeAway"] == "home")
        away = next(c for c in competitors if c["homeAway"] == "away")
        return (
            home["team"]["abbreviation"].upper(),
            away["team"]["abbreviation"].upper(),
            f"{away['team']['shortDisplayName']} {away['score']}, "
            f"{home['team']['shortDisplayName']} {home['score']}",
            home["team"].get("displayName", "").lower(),
            away["team"].get("displayName", "").lower(),
        )
    except Exception:
        return None


def get_world_cup():
    yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y%m%d")
    results = []
    data = espn_scoreboard("soccer", "fifa.world", yesterday)
    if data:
        try:
            events = json.loads(data).get("events", [])
            for event in events:
                comp = event["competitions"][0]
                try:
                    # Soccer reports finished games as STATUS_FULL_TIME, not
                    # STATUS_FINAL — the `completed` flag is reliable across sports.
                    if not comp["status"]["type"].get("completed"):
                        continue
                    competitors = comp["competitors"]
                    home = next(c for c in competitors if c["homeAway"] == "home")
                    away = next(c for c in competitors if c["homeAway"] == "away")
                    results.append(
                        f"{away['team']['displayName']} {away['score']}, "
                        f"{home['team']['displayName']} {home['score']}"
                    )
                except Exception:
                    continue
        except Exception:
            pass

    if not results:
        return ""
    return "World Cup scores from yesterday: " + ". ".join(results) + "."


def get_sports():
    yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y%m%d")
    detroit_results = []
    seen_games = set()

    for sport, league, abbr, name in DETROIT_PRO:
        raw = espn_scoreboard(sport, league, yesterday)
        if not raw:
            continue
        try:
            events = json.loads(raw).get("events", [])
        except Exception:
            continue
        for event in events:
            parsed = parse_game(event["competitions"][0])
            if parsed and (parsed[0] == abbr or parsed[1] == abbr):
                if parsed[2] not in seen_games:
                    detroit_results.append(parsed[2])
                    seen_games.add(parsed[2])

    for sport, league in MSU_LEAGUES:
        raw = espn_scoreboard(sport, league, yesterday)
        if not raw:
            continue
        try:
            events = json.loads(raw).get("events", [])
        except Exception:
            continue
        for event in events:
            parsed = parse_game(event["competitions"][0])
            if parsed and ("michigan state" in parsed[3] or "michigan state" in parsed[4]):
                if parsed[2] not in seen_games:
                    detroit_results.append(parsed[2])
                    seen_games.add(parsed[2])

    national_results = []
    for sport, league in NATIONAL_LEAGUES:
        raw = espn_scoreboard(sport, league, yesterday)
        if not raw:
            continue
        try:
            events = json.loads(raw).get("events", [])
        except Exception:
            continue
        count = 0
        for event in events:
            parsed = parse_game(event["competitions"][0])
            if not parsed:
                continue
            if parsed[0] == "DET" or parsed[1] == "DET":
                continue
            if parsed[2] not in seen_games:
                national_results.append(parsed[2])
                seen_games.add(parsed[2])
                count += 1
            if count >= 3:
                break

    sections = []
    if detroit_results:
        sections.append(
            "Detroit and Michigan State scores from yesterday: "
            + ". ".join(detroit_results) + "."
        )
    else:
        sections.append("No Detroit or Michigan State games were played yesterday.")

    if national_results:
        sections.append("Other scores: " + ". ".join(national_results) + ".")

    world_cup = get_world_cup()
    if world_cup:
        sections.append(world_cup)

    return " ".join(sections)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    now = datetime.now()
    greeting_hour = now.hour
    if greeting_hour < 12:
        greeting = "Good morning"
    elif greeting_hour < 17:
        greeting = "Good afternoon"
    else:
        greeting = "Good evening"

    date_str = now.strftime("%A, %B %-d, %Y")

    print(f"{greeting}! Today is {date_str}.", file=sys.stderr)

    sections = [f"{greeting}! Today is {date_str}."]

    print("Fetching weather...", file=sys.stderr)
    sections.append(get_weather())

    if not SKIP_CALENDAR:
        print("Fetching calendar...", file=sys.stderr)
        sections.append(get_calendar())

    print("Fetching news...", file=sys.stderr)
    sections.append(get_news())

    print("Fetching markets...", file=sys.stderr)
    sections.append(get_markets())

    print("Fetching sports...", file=sys.stderr)
    sections.append(get_sports())

    sections.append("That's your daily update. Have a great day!")

    print(" ".join(sections))


if __name__ == "__main__":
    main()
