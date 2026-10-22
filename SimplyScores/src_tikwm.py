# -*- coding: utf-8 -*-
"""TikWM (tikwm.com): free TikTok API, no key.

  POST/GET /api/user/posts  unique_id=@name count=N cursor=0
  POST/GET /api/user/info   unique_id=@name
Replies are {"code": 0, "msg": "success", "data": {...}}.

TikWM sits behind Cloudflare, which sometimes answers one request style with
HTTP 403 while another style works. Each style below runs in its own fresh
session (no shared cookies), and the style that worked is remembered.
"""
import threading
import time

from .core import clean_text, log, split_caption
from .net import (NetError, Session, SourceError, block_reason, browser_ua, client_hints,
                  junk_headers)

HOSTS = ["https://www.tikwm.com", "https://tikwm.com"]
MIN_GAP = 1.15          # free tier: about one request per second
MAX_COUNT = 34

# (description, method, host index, header style)
STYLES = [
    ("POST www.tikwm.com, website style", "POST", 0, "site"),
    ("GET www.tikwm.com, browser style", "GET", 0, "browser"),
    ("GET tikwm.com, plain client", "GET", 1, "plain"),
    ("POST tikwm.com, plain client", "POST", 1, "plain"),
]


def _style_headers(style, host, method):
    if style == "site":         # what tikwm.com's own page sends
        headers = {"Accept": "application/json, text/javascript, */*; q=0.01",
                   "Origin": host, "Referer": host + "/", "X-Requested-With": "XMLHttpRequest",
                   "Sec-Fetch-Dest": "empty", "Sec-Fetch-Mode": "cors",
                   "Sec-Fetch-Site": "same-origin"}
        if method == "POST":
            headers["Content-Type"] = "application/x-www-form-urlencoded; charset=UTF-8"
        headers.update(client_hints())
        return browser_ua(), headers
    if style == "browser":
        headers = {"Accept": "application/json, text/plain, */*", "Referer": host + "/"}
        headers.update(junk_headers())
        return browser_ua(), headers
    return None, {"Accept": "application/json"}      # requests' own User-Agent


def _why(reply):
    reason = block_reason(reply)
    return "HTTP %d%s" % (reply.status, (" " + reason) if reason else "")


def _summary(problems):
    unique = []
    for p in problems:
        if p not in unique:
            unique.append(p)
    if not unique:
        return "no answer"
    return unique[0] if len(unique) == 1 else "%s; %s" % (unique[0], unique[1])


def abs_url(url, base):
    if not url:
        return ""
    url = url.strip()
    if url.startswith("//"):
        return "https:" + url
    if url.startswith("/"):
        return base + url
    return url


def _int(value):
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def parse_video(item, channel, base=HOSTS[0]):
    """One TikWM post as the plugin's video dict, or None for photo posts and ads."""
    if not isinstance(item, dict) or item.get("images") or item.get("is_ad"):
        return None
    vid = str(item.get("video_id") or item.get("id") or item.get("aweme_id") or "")
    play = abs_url(item.get("play") or "", base)
    hdplay = abs_url(item.get("hdplay") or "", base)
    if not vid or not (play or hdplay):
        return None
    author = item.get("author") or {}
    music = item.get("music_info") or {}
    title, tags = split_caption(item.get("title") or "")
    music_line = clean_text(music.get("title") or "")
    if music.get("author") and music_line and music.get("author") not in music_line:
        music_line += " - " + clean_text(music.get("author"))
    streams = []
    if play:
        streams.append([play, "h264", 0, 0, 0, ""])
    if hdplay and hdplay != play:
        streams.append([hdplay, "h264", 0, 0, 0, "hd"])
    return {
        "id": vid,
        "user": channel,
        "author": clean_text(author.get("nickname") or ""),
        "avatar": abs_url(author.get("avatar") or "", base),
        "title": title,
        "tags": tags,
        "created": _int(item.get("create_time")),
        "duration": _int(item.get("duration")),
        "cover": abs_url(item.get("cover") or item.get("origin_cover") or "", base),
        "plays": _int(item.get("play_count")),
        "likes": _int(item.get("digg_count")),
        "comments": _int(item.get("comment_count")),
        "shares": _int(item.get("share_count")),
        "saves": _int(item.get("collect_count")),
        "music": music_line,
        "pinned": bool(item.get("is_top")),
        "src": "tikwm",
        "streams": streams,
        "page": "https://www.tiktok.com/@%s/video/%s" % (channel, vid),
    }


class TikWM(object):
    name = "tikwm"
    label = "TikWM"

    def __init__(self, style=0):
        self.style = style if isinstance(style, int) and 0 <= style < len(STYLES) else 0
        self._lock = threading.Lock()
        self._last = 0.0

    def _throttle(self):
        with self._lock:
            wait = MIN_GAP - (time.time() - self._last)
            if wait > 0:
                time.sleep(wait)
            self._last = time.time()

    def call(self, index, path, params, trace=None):
        """One request in one style, in a fresh session. Returns (host, Reply)."""
        _, method, host_index, style = STYLES[index]
        host = HOSTS[host_index]
        ua, headers = _style_headers(style, host, method)
        if style == "site":                     # the website adds these two
            params = dict(params, web=1, hd=1)
        session = Session(ua=ua)
        self._throttle()
        if method == "POST":
            reply = session.request("POST", host + path, data=params, headers=headers,
                                    trace=trace, label="TikWM")
        else:
            reply = session.request("GET", host + path, params=params, headers=headers,
                                    trace=trace, label="TikWM")
        return host, reply

    def api(self, path, params, trace=None):
        """Remembered style first, then the others. Returns (host, data)."""
        order = [self.style] + [i for i in range(len(STYLES)) if i != self.style]
        problems = []
        for i in order:
            for attempt in range(3):
                try:
                    host, reply = self.call(i, path, params, trace)
                except NetError as e:
                    problems.append(str(e))
                    break
                if reply.status != 200:
                    problems.append(_why(reply))
                    break
                try:
                    data = reply.json()
                except ValueError:
                    reason = block_reason(reply)
                    problems.append("not JSON" + (" (%s)" % reason if reason else ""))
                    break
                if not isinstance(data, dict):
                    problems.append("unexpected reply")
                    break
                if data.get("code") == 0:
                    if i != self.style:
                        log("TikWM works with style: %s" % STYLES[i][0])
                    self.style = i
                    return host, data.get("data") or {}
                msg = clean_text(str(data.get("msg") or "error %s" % data.get("code")))
                if "limit" in msg.lower():           # "Free Api Limit: 1 request/second"
                    time.sleep(1.5 * (attempt + 1))
                    continue
                raise SourceError(msg, final=True)   # e.g. unknown user: same in every style
        raise SourceError(_summary(problems), blocked=True)

    def user_posts(self, channel, count, trace=None):
        user = channel["username"]
        host, data = self.api("/api/user/posts", {
            "unique_id": "@" + user, "count": max(1, min(int(count), MAX_COUNT)), "cursor": 0}, trace)
        videos = [v for v in (parse_video(it, user, host) for it in data.get("videos") or []) if v]
        videos.sort(key=lambda v: v["created"], reverse=True)    # pinned posts break the order
        return videos, None

    def user_info(self, username, trace=None):
        host, data = self.api("/api/user/info", {"unique_id": "@" + username}, trace)
        user = data.get("user") or {}
        stats = data.get("stats") or {}
        if not user:
            raise SourceError("account not found", final=True)
        return {
            "username": (user.get("uniqueId") or username).lower(),
            "name": clean_text(user.get("nickname") or "") or username,
            "avatar": abs_url(user.get("avatarThumb") or user.get("avatarMedium") or "", host),
            "followers": _int(stats.get("followerCount")),
            "videos": _int(stats.get("videoCount")),
            "private": bool(user.get("privateAccount")),
            "sec_uid": user.get("secUid") or "",
        }

    def link_owner(self, url, trace=None):
        """Username behind a TikTok video or share link (TikWM's video lookup)."""
        _, data = self.api("/api/", {"url": url, "hd": 1}, trace)
        author = data.get("author") if isinstance(data.get("author"), dict) else {}
        name = (author.get("unique_id") or author.get("uniqueId") or "").lower()
        if not name:
            raise SourceError("no channel found for this link", final=True)
        return name

    def test_style(self, index, username, trace=None):
        """(ok, text) for the connection test."""
        try:
            _, reply = self.call(index, "/api/user/posts", {
                "unique_id": "@" + username, "count": 3, "cursor": 0}, trace)
        except NetError as e:
            return False, str(e)
        if reply.status != 200:
            return False, _why(reply)
        try:
            data = reply.json()
        except ValueError:
            return False, "HTTP 200 but not JSON (%s)" % (block_reason(reply) or "unexpected page")
        if isinstance(data, dict) and data.get("code") == 0:
            return True, "%d videos" % len((data.get("data") or {}).get("videos") or [])
        return False, "TikWM says: %s" % clean_text(str((data or {}).get("msg")))
