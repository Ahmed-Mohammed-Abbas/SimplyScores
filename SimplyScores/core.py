# -*- coding: utf-8 -*-
"""Shared helpers: paths, HTTP, text formatting and the channel store.

Nothing in this module imports enigma, so it can be tested off the box.
"""
import json
import os
import re
import ssl
import threading
import time

try:
    import requests
    try:
        requests.packages.urllib3.disable_warnings()
    except Exception:
        pass
except Exception:  # requests is optional; urllib is used instead
    requests = None

PLUGIN_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = "/etc/enigma2/simplyscores.json"
CACHE_DIR = "/tmp/simplyscores"
_CHROME_141 = 1759190400        # 2025-09-30, release day of Chrome 141


def chrome_major(now=None):
    """A recent Chrome version for today's date (an outdated one looks like a bot)."""
    days = int(((now or time.time()) - _CHROME_141) // 86400)
    return max(141, 141 + days // 32 - 2)


def browser_ua():
    return ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/%d.0.0.0 Safari/537.36" % chrome_major())


USER_AGENT = browser_ua()


def log(*args):
    print("[SimplyScores]", *args)


def ensure_dir(path):
    try:
        os.makedirs(path, exist_ok=True)
    except OSError:
        pass


_playlog_lock = threading.Lock()


def _playlog_path():
    return os.path.join(CACHE_DIR, "playback.txt")


def playlog(text):
    """One line in /tmp/simplyscores/playback.txt (the connection test shows the latest)."""
    log(text)
    with _playlog_lock:
        try:
            ensure_dir(CACHE_DIR)
            path = _playlog_path()
            if os.path.exists(path) and os.path.getsize(path) > 65536:
                with open(path, "r", encoding="utf-8", errors="replace") as f:
                    keep = f.readlines()[-200:]
                with open(path, "w", encoding="utf-8") as f:
                    f.writelines(keep)
            with open(path, "a", encoding="utf-8") as f:
                f.write("%s %s\n" % (time.strftime("%H:%M:%S"), text))
        except Exception:
            pass


def playlog_tail(count=25):
    try:
        with open(_playlog_path(), "r", encoding="utf-8", errors="replace") as f:
            return [line.rstrip("\n") for line in f.readlines()[-count:]]
    except Exception:
        return []


# --------------------------------------------------------------------------
# HTTP
# --------------------------------------------------------------------------
class HttpError(Exception):
    pass


def http_get(url, params=None, headers=None, timeout=15, binary=False):
    """GET a URL and return text (or bytes). Raises HttpError."""
    hdrs = {"User-Agent": browser_ua(), "Accept": "application/json, text/plain, */*",
            "Accept-Language": "en-US,en;q=0.9"}
    if headers:
        hdrs.update(headers)
    if requests is not None:
        try:
            try:
                r = requests.get(url, params=params, headers=hdrs, timeout=timeout)
            except requests.exceptions.SSLError:
                # Old boxes often have a stale CA bundle or a wrong clock.
                log("SSL verification failed for", url[:60], "- retrying unverified")
                r = requests.get(url, params=params, headers=hdrs, timeout=timeout, verify=False)
        except requests.RequestException as e:
            raise HttpError(short_error(e))
        if r.status_code >= 400:
            raise HttpError("HTTP %d" % r.status_code)
        return r.content if binary else r.content.decode("utf-8", "replace")

    from urllib.parse import urlencode
    from urllib.request import Request, urlopen
    from urllib.error import HTTPError, URLError
    full = url
    if params:
        full += ("&" if "?" in url else "?") + urlencode(params)
    req = Request(full, headers=hdrs)
    try:
        try:
            resp = urlopen(req, timeout=timeout)
        except URLError as e:
            if not isinstance(getattr(e, "reason", None), ssl.SSLError):
                raise
            log("SSL verification failed for", url[:60], "- retrying unverified")
            resp = urlopen(req, timeout=timeout, context=ssl._create_unverified_context())
        data = resp.read()
    except HTTPError as e:
        raise HttpError("HTTP %d" % e.code)
    except Exception as e:
        raise HttpError(short_error(e))
    return data if binary else data.decode("utf-8", "replace")


def http_get_json(url, params=None, headers=None, timeout=15):
    text = http_get(url, params=params, headers=headers, timeout=timeout)
    try:
        return json.loads(text)
    except ValueError:
        raise HttpError("server did not return JSON")


def short_error(e):
    msg = str(e) or e.__class__.__name__
    if "timed out" in msg.lower() or "timeout" in msg.lower():
        return "connection timed out"
    if "Name or service not known" in msg or "getaddrinfo" in msg or "resolve" in msg.lower():
        return "no internet / DNS error"
    return msg[:120]


# --------------------------------------------------------------------------
# Text helpers
# --------------------------------------------------------------------------
# Emoji and pictographs: receiver fonts have no glyphs for them, so they would
# show as empty boxes.
_EMOJI_RE = re.compile(
    "["
    "\U0001F000-\U0001FAFF"
    "\U000E0000-\U000E007F"
    "⌀-⏿"
    "☀-➿"
    "⬀-⯿"
    "⁦-⁩"
    "︀-️"
    "-"
    "‍⃣〰〽"
    "]+")
_TAG_RE = re.compile(r"#[^\s#]+")
_WS_RE = re.compile(r"\s+")
_ARABIC_RE = re.compile("[؀-ۿݐ-ݿࢠ-ࣿﭐ-﷿ﹰ-﻿]")
_LATIN_RE = re.compile("[A-Za-z]")


def clean_text(text):
    if not text:
        return ""
    text = _EMOJI_RE.sub(" ", text)
    return _WS_RE.sub(" ", text).strip()


def split_caption(raw):
    """Return (title, hashtags) from a TikTok caption."""
    text = clean_text(raw)
    tags, seen = [], set()
    for tag in _TAG_RE.findall(text):
        key = tag.lower()
        if key not in seen and len(tag) > 1:
            seen.add(key)
            tags.append(tag)
    title = _WS_RE.sub(" ", _TAG_RE.sub(" ", text)).strip(" -|:.,")
    return title, tags


def is_rtl(text):
    if not text:
        return False
    return len(_ARABIC_RE.findall(text)) > len(_LATIN_RE.findall(text))


def fix_bidi(text):
    """Reshape + reorder Arabic for images that cannot render it themselves.

    Only used when the user enables it: images that already handle Arabic
    would otherwise show the text reversed.
    """
    if not text or not _ARABIC_RE.search(text):
        return text
    try:
        import arabic_reshaper
        from bidi.algorithm import get_display
        return get_display(arabic_reshaper.reshape(text))
    except Exception:
        return text


def fmt_count(value):
    try:
        n = int(value)
    except (TypeError, ValueError):
        return "0"
    for div, suffix in ((1000000000, "B"), (1000000, "M"), (1000, "K")):
        if n >= div:
            v = n / float(div)
            s = ("%.1f" % v) if v < 100 else ("%d" % v)
            if s.endswith(".0"):
                s = s[:-2]
            return s + suffix
    return str(n)


def fmt_duration(seconds):
    try:
        seconds = int(seconds)
    except (TypeError, ValueError):
        return ""
    if seconds <= 0:
        return ""
    return "%d:%02d" % (seconds // 60, seconds % 60)


def time_ago(ts, now=None, short=False):
    if not ts:
        return ""
    now = now or time.time()
    d = max(0, int(now - ts))
    if d < 60:
        return "now" if short else "just now"
    if d < 3600:
        return ("%dm" if short else "%dm ago") % (d // 60)
    if d < 86400:
        return ("%dh" if short else "%dh ago") % (d // 3600)
    if d < 7 * 86400:
        return ("%dd" if short else "%dd ago") % (d // 86400)
    lt = time.localtime(ts)
    if lt.tm_year == time.localtime(now).tm_year:
        return time.strftime("%d %b", lt)
    return time.strftime("%d %b %Y", lt)


_USER_RE = re.compile(r"^[a-z0-9._]{2,24}$")


def normalize_username(text):
    """Accept 'name', '@name' or a tiktok.com profile/video link."""
    if not text:
        return ""
    t = text.strip()
    m = re.search(r"tiktok\.com/@([A-Za-z0-9._]+)", t)
    if m:
        t = m.group(1)
    t = t.strip().lstrip("@").strip().lower()
    return t if _USER_RE.match(t) else ""


_LINK_RE = re.compile(r"(?:https?://)?(?<![\w.-])(?:[A-Za-z0-9-]+\.)*tiktok\.com/[^\s<>\"',;]*", re.I)
_LINK_USER_RE = re.compile(r"tiktok\.com/@([A-Za-z0-9._]+)", re.I)


def link_username(link):
    """The username in a tiktok.com/@name/... link, or ''."""
    m = _LINK_USER_RE.search(link or "")
    user = m.group(1).lower() if m else ""
    return user if user != "_" and _USER_RE.match(user) else ""


def parse_channel_input(text, limit=30):
    """Channels in what was typed or pasted: usernames and TikTok links.

    Several channels can be given one per line, separated by commas or semicolons,
    or as '@name @name'. Text shared from the TikTok app ("Check out ...
    https://vt.tiktok.com/ZS.../") counts only for its link.
    Returns (entries, rejected): entries are ("user", name) or ("link", url), in
    order and without repeats; rejected are the parts that are neither.
    """
    entries, rejected = [], []

    def add(kind, value):
        if (kind, value) not in entries and len(entries) < limit:
            entries.append((kind, value))

    for part in re.split(r"[\r\n,;]+", text or ""):
        part = part.strip()
        if not part:
            continue
        links = _LINK_RE.findall(part)
        for link in links:
            link = link.rstrip(".!?)]}")
            user = link_username(link)
            if user:
                add("user", user)
            else:
                add("link", link if "://" in link else "https://" + link)
        words = _LINK_RE.sub(" ", part).split()
        handles = [w for w in words if w.startswith("@")]
        if len(words) == 1 or (words and len(handles) == len(words)):
            for word in words:
                user = normalize_username(word)
                if user:
                    add("user", user)
                elif not links:
                    rejected.append(word)
        elif words and not links:
            rejected.append(part)        # e.g. a display name such as "Premier League"
    return entries, rejected


# --------------------------------------------------------------------------
# Channel / league store (/etc/enigma2/simplyscores.json)
# --------------------------------------------------------------------------
DEFAULT_CHANNELS = [
    {"name": "Kayfa1x Summaries", "username": "kayfa1x_2", "enabled": True},
    {"name": "Champions League", "username": "championsleague", "enabled": True},
    {"name": "LaLiga", "username": "laliga", "enabled": True},
    {"name": "Premier League", "username": "premierleague", "enabled": True},
    {"name": "CBS Sports Golazo", "username": "cbssportsgolazo", "enabled": True},
]

# Offered under GREEN "Add channels" and on the phone page: channels that post match
# summaries, goals and highlights like Kayfa1x. Each handle was checked against the
# league's own website or press coverage (October 2026); adding one still checks it on
# TikTok first.
SUGGESTED_CHANNELS = [
    {"username": "kayfa1x_2", "name": "Kayfa1x Summaries", "about": "match summaries and goals"},
    {"username": "spl", "name": "Saudi Pro League", "about": "official league channel, Arabic"},
    {"username": "qsl", "name": "Qatar Stars League", "about": "official league channel, Arabic"},
    {"username": "fifaworldcup", "name": "FIFA World Cup", "about": "official World Cup channel"},
    {"username": "championsleague", "name": "Champions League", "about": "official UEFA channel"},
    {"username": "premierleague", "name": "Premier League", "about": "official league channel"},
    {"username": "laliga", "name": "LaLiga", "about": "official league channel"},
    {"username": "433", "name": "433", "about": "goals, skills and big moments"},
    {"username": "brfootball", "name": "B/R Football", "about": "highlights and football culture"},
    {"username": "cbssportsgolazo", "name": "CBS Sports Golazo", "about": "highlights and studio shows"},
]

# Channels the user picked as preferred: their clips come first in "For You".
# Added once (also to existing lists); a share link is turned into its channel on the box.
PREFERRED_SEED = 1
# names are filled in from TikTok on the first update
PREFERRED_CHANNELS = ["football_actuality10", "kayfa1x_2", "kayfa1x", "myintthuhighlights5", "ligue1",
                      "mouhamedfoot333", "zzcombs3", "koglogrgorden"]
PREFERRED_LINKS = ["https://vt.tiktok.com/ZSgyS93uw/"]

NEW_LEAGUES = ("uefa.europa", "uefa.europa.conf")      # added to existing lists once
DEFAULT_LEAGUES = [
    {"name": "UEFA Champions League", "code": "uefa.champions"},
    {"name": "UEFA Europa League", "code": "uefa.europa"},
    {"name": "UEFA Conference League", "code": "uefa.europa.conf"},
    {"name": "Spanish LaLiga", "code": "esp.1"},
    {"name": "English Premier League", "code": "eng.1"},
    {"name": "Italian Serie A", "code": "ita.1"},
    {"name": "German Bundesliga", "code": "ger.1"},
    {"name": "French Ligue 1", "code": "fra.1"},
]

_STORE_KEYS = ("tiktok_channels", "score_leagues", "last_visit")
_SEC_UID_RE = re.compile(r"^MS4wLjABAAAA[\w-]{20,}$")


def _valid_sec_uid(value):
    """TikTok's permanent account id ('secUid'); cached so TikTok needs fewer page loads."""
    value = (value or "").strip() if isinstance(value, str) else ""
    return value if _SEC_UID_RE.match(value) else ""


class ChannelStore(object):
    """Channels, leagues and the last-visit stamp, kept in one JSON file."""

    def __init__(self, path=None):
        self.path = path or CONFIG_PATH
        self.channels = []
        self.leagues = []
        self.last_visit = 0
        self.extra = {}
        self.load()

    def load(self):
        data = None
        if os.path.exists(self.path):
            try:
                with open(self.path, "r", encoding="utf-8") as f:
                    data = json.load(f)
            except Exception as e:
                log("config unreadable, keeping a copy and using defaults:", e)
                try:
                    os.rename(self.path, self.path + ".broken")
                except OSError:
                    pass
        if not isinstance(data, dict):
            data = {}
        chans = data.get("tiktok_channels")
        if chans is None:
            chans = DEFAULT_CHANNELS
        self.channels = []
        seen = set()
        for c in chans:
            if isinstance(c, str):
                c = {"username": c}
            if not isinstance(c, dict):
                continue
            user = normalize_username(c.get("username", ""))
            if not user or user in seen:
                continue
            seen.add(user)
            self.channels.append({
                "username": user,
                "name": clean_text(c.get("name") or "") or user,
                "enabled": bool(c.get("enabled", True)),
                "preferred": bool(c.get("preferred", False)),
                "sec_uid": _valid_sec_uid(c.get("sec_uid")),
            })
        leagues = data.get("score_leagues")
        if leagues is None:
            leagues = DEFAULT_LEAGUES
        self.leagues = [{"name": l.get("name") or l["code"], "code": l["code"]}
                        for l in leagues if isinstance(l, dict) and l.get("code")]
        try:
            self.last_visit = int(data.get("last_visit") or 0)
        except (TypeError, ValueError):
            self.last_visit = 0
        self.extra = dict((k, v) for k, v in data.items() if k not in _STORE_KEYS)
        added = self._add_new_leagues()
        if int(self.extra.get("preferred_seed") or 0) < PREFERRED_SEED:
            self._seed_preferred()
        elif added or not os.path.exists(self.path):
            self.save()

    def _add_new_leagues(self):
        """Leagues added to the defaults after a list was saved (once each)."""
        done = set(self.extra.get("leagues_added") or [])
        codes = [l["code"] for l in self.leagues]
        changed = False
        for i, league in enumerate(DEFAULT_LEAGUES):
            if league["code"] in NEW_LEAGUES and league["code"] not in done:
                if league["code"] not in codes:
                    before = DEFAULT_LEAGUES[i - 1]["code"] if i else None
                    at = codes.index(before) + 1 if before in codes else len(codes)
                    self.leagues.insert(at, dict(league))
                    codes.insert(at, league["code"])
                done.add(league["code"])
                changed = True
        if changed:
            self.extra["leagues_added"] = sorted(done)
        return changed

    def _seed_preferred(self):
        """Put the preferred channels at the top of the list (once)."""
        top = []
        for user in PREFERRED_CHANNELS:
            c = self.get(user)
            if c:
                self.channels.remove(c)
                c["enabled"] = True
            else:
                c = {"username": user, "name": user, "enabled": True, "sec_uid": ""}
            c["preferred"] = True
            top.append(c)
        self.channels = top + self.channels
        pending = list(self.extra.get("pending_links") or [])
        self.extra["pending_links"] = pending + [u for u in PREFERRED_LINKS if u not in pending]
        self.extra["preferred_seed"] = PREFERRED_SEED
        self.save()

    def save(self):
        data = dict(self.extra)
        data["tiktok_channels"] = self.channels
        data["score_leagues"] = self.leagues
        data["last_visit"] = int(self.last_visit)
        tmp = self.path + ".tmp"
        try:
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            os.replace(tmp, self.path)
            return True
        except Exception as e:
            log("could not save", self.path, e)
            return False

    # -- queries --
    def usernames(self, enabled_only=True):
        return [c["username"] for c in self.channels if c["enabled"] or not enabled_only]

    def preferred(self):
        return set(c["username"] for c in self.channels if c.get("preferred"))

    def get(self, username):
        for c in self.channels:
            if c["username"] == username:
                return c
        return None

    def index(self, username):
        for i, c in enumerate(self.channels):
            if c["username"] == username:
                return i
        return -1

    # -- edits (each one saves) --
    def add(self, username, name=None, sec_uid=None, preferred=False):
        user = normalize_username(username)
        if not user or self.get(user):
            return False
        entry = {"username": user, "name": clean_text(name or "") or user, "enabled": True,
                 "preferred": bool(preferred), "sec_uid": _valid_sec_uid(sec_uid)}
        if preferred:       # after the other preferred channels
            at = max([i + 1 for i, c in enumerate(self.channels) if c.get("preferred")] or [0])
            self.channels.insert(at, entry)
        else:
            self.channels.append(entry)
        return self.save()

    def toggle_preferred(self, username):
        c = self.get(username)
        if not c:
            return False
        c["preferred"] = not c.get("preferred")
        return self.save()

    def drop_pending_link(self, url):
        links = [u for u in self.extra.get("pending_links") or [] if u != url]
        self.extra["pending_links"] = links
        return self.save()

    def set_sec_uid(self, username, sec_uid):
        c = self.get(username)
        sec_uid = _valid_sec_uid(sec_uid)
        if not c or not sec_uid or c.get("sec_uid") == sec_uid:
            return False
        c["sec_uid"] = sec_uid
        return self.save()

    def remove(self, username):
        i = self.index(username)
        if i < 0:
            return False
        del self.channels[i]
        return self.save()

    def toggle(self, username):
        c = self.get(username)
        if not c:
            return False
        c["enabled"] = not c["enabled"]
        return self.save()

    def rename(self, username, name):
        c = self.get(username)
        name = clean_text(name or "")
        if not c or not name:
            return False
        c["name"] = name
        return self.save()

    def move(self, username, delta):
        i = self.index(username)
        j = i + delta
        if i < 0 or j < 0 or j >= len(self.channels):
            return False
        self.channels[i], self.channels[j] = self.channels[j], self.channels[i]
        return self.save()
