#!/usr/bin/env python3
"""Daily morning briefing — weather, calendar, news, and sports scores."""

import json
import os
import sys
import subprocess
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta

# Set to "1" to skip the calendar section (e.g. when running in the cloud,
# where there's no access to the local Apple Calendar).
SKIP_CALENDAR = os.environ.get("BRIEFING_SKIP_CALENDAR") == "1"


def fetch(url, timeout=10):
    # Try urllib first; fall back to curl if SSL fails (Python 3.9 system SSL limitation)
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
# News (RSS feeds, no API key needed)
# ---------------------------------------------------------------------------

def rss_headlines(url, count=3):
    data = fetch(url)
    if not data:
        return []
    try:
        root = ET.fromstring(data)
        titles = []
        for item in root.findall(".//item")[:count * 2]:
            t = item.find("title")
            if t is not None and t.text:
                clean = t.text.strip().replace("&amp;", "and").replace("&lt;", "<").replace("&gt;", ">")
                if clean and "[" not in clean[:3]:  # skip feed-meta items
                    titles.append(clean)
            if len(titles) == count:
                break
        return titles
    except Exception:
        return []


def get_news():
    parts = []

    # Local Detroit
    local_feeds = [
        "https://www.detroitnews.com/rss/",
        "https://rss.freep.com/freep/news/local/",
        "https://www.clickondetroit.com/rss/news.xml",
    ]
    local = []
    for feed in local_feeds:
        local += rss_headlines(feed, 3)
        if len(local) >= 3:
            break
    if local:
        parts.append("Local Detroit headlines: " + ". ".join(local[:3]) + ".")

    # National
    national_feeds = [
        "https://feeds.feedburner.com/APTopStories",
        "https://rss.nytimes.com/services/xml/rss/nyt/HomePage.xml",
        "https://feeds.npr.org/1001/rss.xml",
    ]
    national = []
    for feed in national_feeds:
        national += rss_headlines(feed, 3)
        if len(national) >= 3:
            break
    if national:
        parts.append("National headlines: " + ". ".join(national[:3]) + ".")

    # World
    world_feeds = [
        "https://feeds.bbci.co.uk/news/world/rss.xml",
        "https://feeds.reuters.com/reuters/worldNews",
    ]
    world = []
    for feed in world_feeds:
        world += rss_headlines(feed, 3)
        if len(world) >= 3:
            break
    if world:
        parts.append("World headlines: " + ". ".join(world[:3]) + ".")

    return " ".join(parts) if parts else "News headlines are unavailable right now."


# ---------------------------------------------------------------------------
# Sports scores (ESPN public API, no key needed)
# ---------------------------------------------------------------------------

DETROIT_PRO = [
    ("baseball",  "mlb",               "DET",  "Tigers"),
    ("football",  "nfl",               "DET",  "Lions"),
    ("basketball","nba",               "DET",  "Pistons"),
    ("hockey",    "nhl",               "DET",  "Red Wings"),
]

NATIONAL_LEAGUES = [
    ("football",  "nfl"),
    ("basketball","nba"),
    ("baseball",  "mlb"),
    ("hockey",    "nhl"),
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
    """Return (home_abbr, away_abbr, score_str) or None if not final."""
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


def get_sports():
    yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y%m%d")
    detroit_results = []
    seen_games = set()

    # Detroit pro teams
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

    # Michigan State
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

    # National scores (top 3 per league, skip Detroit)
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

    print("Fetching sports...", file=sys.stderr)
    sections.append(get_sports())

    sections.append("That's your daily update. Have a great day!")

    # Print the final briefing text to stdout (Shortcut reads this)
    print(" ".join(sections))


if __name__ == "__main__":
    main()
