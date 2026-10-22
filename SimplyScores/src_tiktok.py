# -*- coding: utf-8 -*-
"""TikTok's own website as a video source (no third-party service).

Follows yt-dlp's TikTok extractor (2026):
  1. https://www.tiktok.com/@name carries the account's secUid in the
     __UNIVERSAL_DATA_FOR_REHYDRATION__ JSON. TikTok sometimes answers with a
     "Please wait..." page first: a SHA-256 puzzle that is solved here and
     sent back as a cookie.
  2. /api/creator/item_list/?secUid=...&type=1 lists the newest posts.
  3. Playable links come from each clip's own page, loaded in a session of
     its own: TikTok's CDN refuses links unless the request carries the
     cookies of the session that loaded them (links from the list API are
     usually refused). Playback goes through the local stream relay.
"""
import base64
import hashlib
import json
import random
import re
import string
import threading
import time
from urllib.parse import urljoin, urlparse

from . import net
from .core import clean_text, link_username, split_caption
from .net import NetError, Session, SourceError, block_reason, browser_ua, describe, junk_headers

BASE = "https://www.tiktok.com"
# Share links from the TikTok app ("Copy link"): vm./vt.tiktok.com/<code>/ and tiktok.com/t/<code>/
SHORT_HOSTS = {"vm.tiktok.com": "https://vm.tiktok.com", "vt.tiktok.com": "https://vt.tiktok.com"}
_VIDEO_ID_RE = re.compile(r"/(?:video|v)/(\d{6,})")
_CANONICAL_RE = re.compile(r"https?://(?:www\.|m\.)?tiktok\.com/@[A-Za-z0-9._]*/video/\d+")
PAGE_SIZE = 15
_UNIVERSAL_RE = re.compile(
    r'<script[^>]+\bid=["\']__UNIVERSAL_DATA_FOR_REHYDRATION__["\'][^>]*>(.*?)</script>', re.S)
_FRONTITY_RE = re.compile(
    r'<script[^>]+\bid=["\']__FRONTITY_CONNECT_STATE__["\'][^>]*>(.*?)</script>', re.S)
_URL_KEY_RE = re.compile(r"v[^_]+_(?P<codec>[^_]+)_(?P<res>\d+)p_(?P<br>\d+)")
PAGE_HEADERS = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Sec-Fetch-Dest": "document", "Sec-Fetch-Mode": "navigate", "Sec-Fetch-Site": "none",
    "Upgrade-Insecure-Requests": "1",
}


def _int(value):
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _proto(url):
    if isinstance(url, str) and url.startswith("//"):
        return "https:" + url
    return url if isinstance(url, str) else ""


def _device_id():
    return str(random.randint(7250000000000000000, 7325099899999994577))


def _ua(bare):
    """'Mozilla/5.0' alone (yt-dlp's trick for TikTok pages) or a full current Chrome."""
    return "Mozilla/5.0" if bare else browser_ua()


def _page_problem(reply):
    reason = block_reason(reply)
    if reason:
        return "HTTP %d %s" % (reply.status, reason)
    return "HTTP 200 without page data" if reply.status == 200 else "HTTP %d" % reply.status


# --------------------------------------------------------------------------
# Page parsing
# --------------------------------------------------------------------------
def universal_data(html):
    m = _UNIVERSAL_RE.search(html or "")
    if not m:
        return {}
    try:
        data = json.loads(m.group(1))
    except ValueError:
        return {}
    scope = data.get("__DEFAULT_SCOPE__") if isinstance(data, dict) else None
    return scope if isinstance(scope, dict) else {}


def _element_class(html, elem_id):
    m = re.search(r'<[^<>]*\bid=["\']%s["\'][^<>]*>' % re.escape(elem_id), html or "")
    if not m:
        return None
    a = re.search(r'\bclass=["\']([^"\']*)["\']', m.group(0))
    return a.group(1) if a else None


def solve_challenge(html, limit=1000000):
    """Answer TikTok's 'Please wait...' SHA-256 puzzle.

    Returns [(cookie name, value), ...] to send with the next request, or None
    when the page is not a challenge.
    """
    raw = _element_class(html, "cs")
    if not raw:
        return None
    try:
        data = json.loads(base64.b64decode(raw + "==="))
        expected = base64.b64decode(data["v"]["c"])
        base = hashlib.sha256(base64.b64decode(data["v"]["a"]))
    except Exception:
        raise SourceError("TikTok's bot check changed format", blocked=True)
    answer = None
    for i in range(limit + 1):
        number = str(i).encode()
        h = base.copy()
        h.update(number)
        if h.digest() == expected:
            answer = number
            break
    if answer is None:
        raise SourceError("couldn't solve TikTok's bot check", blocked=True)
    data["d"] = base64.b64encode(answer).decode()
    name = _element_class(html, "wci")
    if not name:
        raise SourceError("TikTok's bot check changed format", blocked=True)
    cookies = [(name, base64.b64encode(json.dumps(data, separators=(",", ":")).encode()).decode())]
    rci, rs = _element_class(html, "rci"), _element_class(html, "rs")
    if rci and rs:
        cookies.append((rci, rs))
    return cookies


def video_detail(data):
    """The post object of a clip page, or SourceError with TikTok's reason."""
    detail = data.get("webapp.video-detail") or {}
    status = _int(detail.get("statusCode"))
    item = (detail.get("itemInfo") or {}).get("itemStruct") or {}
    if item and not status:
        return item
    if status == 10204:
        raise SourceError("TikTok blocks this network for this video", blocked=True)
    if status in (10216, 10222):
        raise SourceError("private video", final=True)
    raise SourceError("video unavailable (TikTok status %s)" % status)


# --------------------------------------------------------------------------
# Posts
# --------------------------------------------------------------------------
def _codec(name):
    name = (name or "").lower()
    if "bytevc2" in name or "266" in name or "vvc" in name:
        return None                              # no receiver can decode these
    if "264" in name or "avc" in name:
        return "h264"
    if "265" in name or "hevc" in name or "bytevc1" in name or "hvc" in name:
        return "h265"
    return "h264"


def collect_streams(video):
    """[[url, codec, width, height, bitrate, flag], ...] for a TikTok 'video' object."""
    out, seen = [], set()

    def add(url, codec, w, h, br, flag=""):
        url = _proto(url)
        if not url.startswith("http") or url in seen or codec is None:
            return
        parsed = urlparse(url)
        if parsed.hostname == "www.tiktok.com" or parsed.path.endswith("/media-video-hvc1/"):
            return                               # broken / video-only links (see yt-dlp)
        seen.add(url)
        out.append([url, codec, _int(w), _int(h), _int(br), flag])

    for info in video.get("bitrateInfo") or []:
        addr = info.get("PlayAddr") or {}
        key = _URL_KEY_RE.search(addr.get("UrlKey") or "")
        codec = _codec(info.get("CodecType") or (key and key.group("codec")) or "")
        bitrate = info.get("Bitrate") or (key and key.group("br")) or 0
        for url in addr.get("UrlList") or []:
            add(url, codec, addr.get("Width"), addr.get("Height"), bitrate)
    play = video.get("playAddr")
    plays = [play] if isinstance(play, str) else [p.get("src") for p in play or [] if isinstance(p, dict)]
    for url in plays:
        add(url, _codec(video.get("codecType") or "h264"), video.get("width"), video.get("height"),
            video.get("bitrate"))
    download = video.get("downloadAddr")
    if isinstance(download, str):
        add(download, "h264", video.get("width"), video.get("height"), 0, "wm")
    return out


def order_streams(streams, hd=False):
    """Best first: H.264 before HEVC, a size that suits the setting, watermark-free first."""
    target = 1080 if hd else 720

    def key(s):
        url, codec, w, h, br, flag = (list(s) + [0, 0, 0, 0, 0, ""])[:6]
        width = min(w, h) if w and h else 0
        fits = 1 if not width else (0 if width <= target else 2)
        return (1 if flag == "wm" else 0,
                {"h264": 0, "h265": 1}.get(codec, 2),
                0 if (flag == "hd") == hd else 1,
                fits,
                -width if fits == 0 else width,
                -(br or 0))
    return sorted([s for s in streams or [] if s and s[0]], key=key)


def parse_item(item, username):
    """One TikTok post as the plugin's video dict, or None for photo posts and ads."""
    if not isinstance(item, dict) or item.get("imagePost") or item.get("isAd") or item.get("is_ad"):
        return None
    vid = str(item.get("id") or "")
    if not vid:
        return None
    video = item.get("video") or {}
    stats = item.get("stats") or {}
    stats2 = item.get("statsV2") or {}
    author = item.get("author") if isinstance(item.get("author"), dict) else {}
    music = item.get("music") or {}
    title, tags = split_caption(item.get("desc") or "")
    music_line = clean_text(music.get("title") or "")
    if music.get("authorName") and music_line and music.get("authorName") not in music_line:
        music_line += " - " + clean_text(music.get("authorName"))
    user = (author.get("uniqueId") or username or "_").lower()

    def stat(name):
        return _int(stats.get(name) if stats.get(name) is not None else stats2.get(name))
    return {
        "id": vid,
        "user": username or user,
        "author": clean_text(author.get("nickname") or ""),
        "avatar": _proto(author.get("avatarThumb") or author.get("avatarMedium") or ""),
        "title": title,
        "tags": tags,
        "created": _int(item.get("createTime")),
        "duration": _int(video.get("duration")),
        "cover": _proto(video.get("cover") or video.get("originCover") or ""),
        "plays": stat("playCount"),
        "likes": stat("diggCount"),
        "comments": stat("commentCount"),
        "shares": stat("shareCount"),
        "saves": stat("collectCount"),
        "music": music_line,
        "pinned": bool(item.get("isPinnedItem")),
        "src": "tiktok",
        "links_from": "list",
        "streams": collect_streams(video),
        "page": "%s/@%s/video/%s" % (BASE, user, vid),
    }


def _short_target(url):
    """The address to ask for a share link, or None when url isn't one."""
    p = urlparse(url)
    host = (p.hostname or "").lower()
    if host in SHORT_HOSTS:
        return SHORT_HOSTS[host] + (p.path or "/")
    if host.endswith("tiktok.com") and p.path.startswith("/t/"):
        return BASE + p.path
    return None


def author_sec_uid(item):
    author = item.get("author")
    if isinstance(author, dict) and author.get("secUid"):
        return author["secUid"]
    return item.get("authorSecId") or ""


# --------------------------------------------------------------------------
# Client
# --------------------------------------------------------------------------
class TikTokWeb(object):
    name = "tiktok"
    label = "TikTok"

    def __init__(self, prefs=None):
        prefs = prefs if isinstance(prefs, dict) else {}
        self.lock = threading.RLock()
        # Which User-Agent works is remembered separately for profile pages / video
        # lists and for clip pages: TikTok treats them differently.
        self.list_bare = bool(prefs.get("list_bare", False))
        self.page_bare = bool(prefs.get("page_bare", True))
        self._session = None
        self.device_id = _device_id()
        self.warm = False              # a page load gave the list session TikTok's cookies
        self.solved = 0

    def prefs(self):
        return {"list_bare": self.list_bare, "page_bare": self.page_bare}

    def session(self):
        """Session for profile pages and the video-list API."""
        with self.lock:
            if self._session is None:
                self._session = Session(ua=_ua(self.list_bare))
                self.warm = False
            return self._session

    def _cookie_domain(self):
        host = urlparse(BASE).hostname or ""
        return ".tiktok.com" if host.endswith("tiktok.com") else host

    def _load(self, session, path, trace):
        """One page in one session, solving the bot check. Returns (universal data, reply)."""
        headers = dict(PAGE_HEADERS)
        headers.update(junk_headers())
        try:
            reply = session.request("GET", BASE + path, headers=headers, trace=trace, label="TikTok")
        except NetError as e:
            raise SourceError(str(e))
        if urlparse(reply.url).path.rstrip("/").endswith("/login"):
            raise SourceError("TikTok asks to log in for this page", final=True)
        data = universal_data(reply.text) if reply.status == 200 else {}
        if not data and reply.status == 200:
            t0 = time.time()
            cookies = solve_challenge(reply.text)
            if cookies:
                self.solved += 1
                net.note(trace, "TikTok bot check solved in %.1fs" % (time.time() - t0))
                domain = self._cookie_domain()
                for name, value in cookies:
                    session.set_cookie(name, value, domain)
                try:
                    reply = session.request("GET", BASE + path, headers=headers, trace=trace,
                                            label="TikTok")
                except NetError as e:
                    raise SourceError(str(e))
                finally:
                    for name, _ in cookies:
                        session.drop_cookie(name, domain)
                data = universal_data(reply.text) if reply.status == 200 else {}
        return data, reply

    def page(self, path, trace=None):
        """Universal data of a page in the list session: current UA, then the other one."""
        with self.lock:
            problem = "no answer"
            for _ in range(2):
                data, reply = self._load(self.session(), path, trace)
                if data:
                    self.warm = True
                    return data
                problem = _page_problem(reply)
                self.list_bare = not self.list_bare
                self._session = None
            raise SourceError(problem, blocked=True)

    def video_session(self, username, vid, trace=None):
        """(session, post) for one clip, loaded in a new session of its own."""
        path = "/@%s/video/%s" % (username or "_", vid)
        problem = "no answer"
        for _ in range(2):
            bare = self.page_bare
            session = Session(ua=_ua(bare))
            data, reply = self._load(session, path, trace)
            if data:
                return session, video_detail(data)
            problem = _page_problem(reply)
            self.page_bare = not bare
        raise SourceError("clip page " + problem, blocked=True)

    def video_item(self, username, vid, trace=None):
        return self.video_session(username, vid, trace)[1]

    def resolve(self, video, trace=None):
        """(session, fresh stream links) from the clip's own page."""
        session, item = self.video_session(video.get("user"), video["id"], trace)
        fresh = parse_item(item, video.get("user"))
        return session, (fresh or {}).get("streams") or []

    # -- links pasted by the user
    def link_owner(self, url, trace=None):
        """Username behind a TikTok link: a profile or video link, or a share link from
        the app (vm.tiktok.com/..., vt.tiktok.com/..., tiktok.com/t/...). Blocking."""
        url = url if "://" in url else "https://" + url
        for hop in range(5):
            user = link_username(url)
            if user:
                return user
            parsed = urlparse(url)
            m = _VIDEO_ID_RE.search(parsed.path)
            if m:
                return self._video_owner(m.group(1), trace)
            target, share = _short_target(url), True
            host = (parsed.hostname or "").lower()
            if not target and hop and parsed.path not in ("", "/") and (
                    host == "tiktok.com" or host.endswith(".tiktok.com")):
                target, share = url, False    # a further redirect step on TikTok: follow it too
            if not target:
                break
            url = self._follow(target, trace, read_page=share)
        raise SourceError("this link doesn't lead to a TikTok channel or video", final=True)

    def _follow(self, url, trace, read_page=True):
        """Where one share link points. Like yt-dlp: ask as a link-preview robot, which
        gets a plain redirect instead of the app's landing page. read_page: when there is
        no redirect, take the clip link from the share link's own page."""
        session = Session(ua="facebookexternalhit/1.1")
        reply = None
        for method in ("HEAD", "GET") if read_page else ("HEAD",):
            try:
                reply = session.request(method, url, headers={"Accept": "text/html,*/*;q=0.8"},
                                        trace=trace, label="TikTok link", allow_redirects=False)
            except NetError as e:
                raise SourceError(str(e))
            location = reply.headers.get("location")
            if reply.status in (301, 302, 303, 307, 308) and location:
                return urljoin(url, location)
            if method == "GET" and reply.status == 200:
                m = _CANONICAL_RE.search(reply.text.replace("\\u002F", "/"))
                if m:
                    return m.group(0)
        raise SourceError("the share link didn't open (%s)" % describe(reply), final=reply.status == 404)

    def _video_owner(self, vid, trace):
        item = self.video_item("_", vid, trace)
        author = item.get("author") if isinstance(item.get("author"), dict) else {}
        name = (author.get("uniqueId") or "").lower()
        if not name:
            raise SourceError("the video page doesn't name its channel")
        return name

    def profile(self, username, trace=None):
        data = self.page("/@" + username, trace)
        detail = data.get("webapp.user-detail") or {}
        status = _int(detail.get("statusCode"))
        info = detail.get("userInfo") or {}
        user = info.get("user") or {}
        stats = info.get("stats") or {}
        stats2 = info.get("statsV2") or {}
        if not user.get("uniqueId") and not user.get("secUid"):
            if status == 10222:
                raise SourceError("private account", final=True)
            raise SourceError("account not found (TikTok status %s)" % status if status
                              else "no account data on the page", final=bool(status))
        return {
            "username": (user.get("uniqueId") or username).lower(),
            "name": clean_text(user.get("nickname") or "") or username,
            "avatar": _proto(user.get("avatarThumb") or user.get("avatarMedium") or ""),
            "followers": _int(stats.get("followerCount") or stats2.get("followerCount")),
            "videos": _int(stats.get("videoCount") or stats2.get("videoCount")),
            "private": bool(user.get("privateAccount")) or status == 10222,
            "sec_uid": user.get("secUid") or "",
        }

    user_info = profile

    def sec_uid_from_embed(self, username, trace=None):
        """Fallback when the profile page lacks the secUid: embed page -> a clip -> its author."""
        try:
            reply = self.session().request("GET", "%s/embed/@%s" % (BASE, username),
                                           headers={"Accept": "text/html,*/*;q=0.8"},
                                           trace=trace, label="TikTok")
        except NetError:
            return ""
        m = _FRONTITY_RE.search(reply.text) if reply.status == 200 else None
        try:
            node = json.loads(m.group(1))["source"]["data"]["/embed/@" + username]
        except Exception:
            return ""
        for entry in (node.get("videoList") or [])[:3]:
            vid = str((entry or {}).get("id") or "")
            if not vid:
                continue
            try:
                sec = author_sec_uid(self.video_item(username, vid, trace))
            except SourceError:
                continue
            if sec:
                return sec
        return ""

    def _query(self, sec_uid, cursor, count):
        return {
            "aid": "1988", "app_language": "en", "app_name": "tiktok_web",
            "browser_language": "en-US", "browser_name": "Mozilla", "browser_online": "true",
            "browser_platform": "Win32", "browser_version": "5.0 (Windows)",
            "channel": "tiktok_web", "cookie_enabled": "true", "count": str(count),
            "cursor": str(cursor), "device_id": self.device_id, "device_platform": "web_pc",
            "focus_state": "true", "from_page": "user", "history_len": "2",
            "is_fullscreen": "false", "is_page_visible": "true", "language": "en",
            "os": "windows", "priority_region": "", "referer": "", "region": "US",
            "screen_height": "1080", "screen_width": "1920", "secUid": sec_uid,
            "type": "1",                  # newest to oldest
            "tz_name": "UTC",
            "verifyFp": "verify_" + "".join(random.choice(string.hexdigits) for _ in range(7)),
            "webcast_language": "en",
        }

    def item_list(self, username, sec_uid, count, trace=None):
        """Raw newest posts (dicts) of an account."""
        session = self.session()
        items, seen = [], set()
        cursor = int(net.now() * 1000)
        headers = {"Accept": "application/json, text/plain, */*",
                   "Referer": "%s/@%s" % (BASE, username),
                   "Sec-Fetch-Dest": "empty", "Sec-Fetch-Mode": "cors",
                   "Sec-Fetch-Site": "same-origin"}
        for _ in range(4):
            try:
                reply = session.request("GET", BASE + "/api/creator/item_list/",
                                        params=self._query(sec_uid, cursor, PAGE_SIZE),
                                        headers=headers, trace=trace, label="TikTok API")
            except NetError as e:
                raise SourceError(str(e))
            if reply.status != 200:
                reason = block_reason(reply)
                raise SourceError("video list HTTP %d%s" % (reply.status, (" " + reason) if reason else ""),
                                  blocked=True)
            if not reply.content.strip():
                raise SourceError("TikTok sent an empty video list (request refused)", blocked=True)
            try:
                data = reply.json()
            except ValueError:
                raise SourceError("video list is not JSON (%s)" % (block_reason(reply) or "unexpected page"),
                                  blocked=True)
            code = _int(data.get("statusCode", data.get("status_code")))
            if code:
                msg = clean_text(str(data.get("statusMsg") or data.get("status_msg") or ""))
                raise SourceError(("TikTok status %d %s" % (code, msg)).strip())
            batch = [it for it in data.get("itemList") or []
                     if isinstance(it, dict) and str(it.get("id") or "") not in seen]
            for it in batch:
                seen.add(str(it.get("id")))
                items.append(it)
            if len(items) >= count or not data.get("hasMorePrevious"):
                break
            older = _int(batch[-1].get("createTime")) * 1000 if batch else 0
            # No posts in this window: TikTok pages by time, so step back a week (as yt-dlp does)
            cursor = older if 0 < older < cursor else cursor - 7 * 86400000
        return items

    def user_posts(self, channel, count, trace=None):
        """(videos, newly found secUid or None)."""
        username = channel["username"]
        sec = channel.get("sec_uid") or ""
        found = None
        profile = None
        if not sec or not self.warm:
            try:
                profile = self.profile(username, trace)
            except SourceError:
                if not sec:
                    raise
            if profile:
                if profile["private"]:
                    raise SourceError("private account", final=True)
                if profile["sec_uid"] and profile["sec_uid"] != sec:
                    sec = found = profile["sec_uid"]
                if not sec:
                    sec = found = self.sec_uid_from_embed(username, trace)
        if not sec:
            raise SourceError("couldn't find the account id (secUid)")
        items = self.item_list(username, sec, count, trace)
        if not items and profile and profile.get("videos"):
            self.device_id = _device_id()       # a stale device id can return nothing
            items = self.item_list(username, sec, count, trace)
        videos = [v for v in (parse_item(it, username) for it in items) if v]
        videos.sort(key=lambda v: v["created"], reverse=True)
        return videos[:max(1, int(count))], found
