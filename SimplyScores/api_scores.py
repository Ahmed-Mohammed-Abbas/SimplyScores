# -*- coding: utf-8 -*-
"""Live scores from ESPN's public scoreboard JSON (no key needed).

GET https://site.api.espn.com/apis/site/v2/sports/soccer/<league>/scoreboard
League codes: eng.1, esp.1, ita.1, ger.1, fra.1, uefa.champions, ...
"""
import calendar
import re
import time

from .core import clean_text, http_get_json

URL = "https://site.api.espn.com/apis/site/v2/sports/soccer/%s/scoreboard"
HEADERS = {"Referer": "https://www.espn.com/", "Origin": "https://www.espn.com"}


def _epoch(text):
    if not text:
        return 0
    text = text.strip().replace("Z", "")
    for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M"):
        try:
            return calendar.timegm(time.strptime(text, fmt))
        except ValueError:
            pass
    return 0


def _team_name(competitor):
    team = competitor.get("team") or {}
    return clean_text(team.get("shortDisplayName") or team.get("displayName")
                      or team.get("abbreviation") or "?")


def parse_scoreboard(data):
    league = ""
    leagues = data.get("leagues") or []
    if leagues:
        league = clean_text(leagues[0].get("name") or "")
    matches = []
    for ev in data.get("events") or []:
        comp = (ev.get("competitions") or [{}])[0]
        teams = comp.get("competitors") or []
        if len(teams) < 2:
            continue
        home = next((t for t in teams if t.get("homeAway") == "home"), teams[0])
        away = next((t for t in teams if t is not home), teams[1])
        status = comp.get("status") or ev.get("status") or {}
        stype = status.get("type") or {}
        home_id = (home.get("team") or {}).get("id")
        goals = []
        for d in comp.get("details") or []:
            if not d.get("scoringPlay"):
                continue
            athletes = d.get("athletesInvolved") or [{}]
            name = athletes[0].get("shortName") or athletes[0].get("displayName") or ""
            goals.append({
                "name": clean_text(name),
                "minute": (d.get("clock") or {}).get("displayValue", ""),
                "side": "home" if (d.get("team") or {}).get("id") == home_id else "away",
                "og": bool(d.get("ownGoal")),
                "pen": bool(d.get("penaltyKick")),
            })
        matches.append({
            "id": str(ev.get("id") or ""),
            "home": _team_name(home),
            "away": _team_name(away),
            "hs": str(home.get("score") if home.get("score") is not None else ""),
            "as": str(away.get("score") if away.get("score") is not None else ""),
            "state": stype.get("state") or "pre",
            "detail": stype.get("shortDetail") or "",
            "clock": status.get("displayClock") or "",
            "kickoff": _epoch(ev.get("date") or comp.get("date")),
            "goals": goals,
        })
    order = {"in": 0, "post": 1, "pre": 2}
    matches.sort(key=lambda m: (order.get(m["state"], 3),
                                -m["kickoff"] if m["state"] == "post" else m["kickoff"]))
    return league, matches


def scoreboard(code):
    """(league name, matches) for an ESPN league code. Blocking."""
    return parse_scoreboard(http_get_json(URL % code, headers=HEADERS, timeout=12))


def status_text(match, now=None):
    state = match["state"]
    if state == "in":
        return match["detail"] or match["clock"] or "LIVE"
    if state == "post":
        return match["detail"] or "FT"
    if not match["kickoff"]:
        return match["detail"]
    lt = time.localtime(match["kickoff"])
    today = time.localtime(now or time.time())
    if (lt.tm_year, lt.tm_yday) == (today.tm_year, today.tm_yday):
        return time.strftime("%H:%M", lt)
    return time.strftime("%a %H:%M", lt)


def _compact(tokens, max_chars):
    out = ""
    for i, tok in enumerate(tokens):
        cand = tok if not out else out + ", " + tok
        if max_chars and out and len(cand) > max_chars:
            return "%s +%d" % (out, len(tokens) - i)
        out = cand
    return out


def scorers_text(match, home_chars=0, away_chars=0):
    """("Salah 23' 67'", "Haaland 81'") for the home and away columns.

    With a character budget, extra scorers collapse into "+N".
    """
    out = {}
    for side, budget in (("home", home_chars), ("away", away_chars)):
        names, minutes = [], {}
        for g in match["goals"]:
            if g["side"] != side:
                continue
            name = re.sub(r"^[A-Z]\.\s*", "", g["name"]) or "?"
            label = g["minute"] + (" og" if g["og"] else "") + (" p" if g["pen"] else "")
            if name not in minutes:
                names.append(name)
                minutes[name] = []
            minutes[name].append(label)
        out[side] = _compact(["%s %s" % (n, " ".join(minutes[n])) for n in names], budget)
    return out["home"], out["away"]
