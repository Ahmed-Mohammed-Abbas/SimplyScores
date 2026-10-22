# -*- coding: utf-8 -*-
"""Picks the video source that works from this network and gets playable links.

Automatic mode tries the source that worked last time first. A source that
refuses this box (HTTP 403, bot check...) is skipped for 20 minutes.

Playable links: TikTok's CDN refuses links from the video-list API, so (like
yt-dlp) each clip's links come from the clip's own page, loaded in a session
of its own whose cookies the CDN checks. LinkResolver fetches them in the
background, the clip about to play first, then the next ones, so the player
never waits on TikTok.
"""
import re
import threading
import time
import traceback
from collections import OrderedDict

from . import src_tiktok
from .core import log, playlog
from .net import NetError, Session, SourceError, browser_ua, host_of, note
from .src_tikwm import TikWM
from .src_tiktok import TikTokWeb, order_streams

SKIP_BLOCKED = 20 * 60
LINK_TTL = 45 * 60
KEEP_SESSIONS = 12
_EXPIRE_RE = re.compile(r"[?&](?:x-)?expires?=(\d{9,11})")


def join_problems(problems):
    return " | ".join("%s: %s" % (label, text) for label, text in problems) or "no source available"


def describe_stream(entry):
    """'h264 576p from v16-webapp-prime.tiktok.com'."""
    if not entry:
        return "?"
    url, codec, w, h = entry[0], entry[1], entry[2], entry[3]
    kind = "%s %dp" % (codec, min(w, h)) if w and h else codec
    return "%s from %s" % (kind, host_of(url))


def stream_kinds(streams):
    """'h264 720p, h264 576p, h265 1080p' in the order they would be tried."""
    kinds = []
    for s in order_streams(streams or []):
        kind = "%s %dp" % (s[1], min(s[2], s[3])) if s[2] and s[3] else s[1]
        if kind not in kinds:
            kinds.append(kind)
    return ", ".join(kinds[:6]) or "none"


def _expiry(streams):
    for s in streams or []:
        m = _EXPIRE_RE.search(s[0])
        if m:
            return int(m.group(1))
    return 0


class Sources(object):
    def __init__(self, state=None, mode=None, codec=None):
        state = state if isinstance(state, dict) else {}
        self.tikwm = TikWM(state.get("tikwm_style", 0))
        self.tiktok = TikTokWeb(state.get("tiktok"))
        self.preferred = state.get("source") if state.get("source") in ("tikwm", "tiktok") else "tikwm"
        self.mode = mode or (lambda: "auto")
        self.codec = codec or (lambda: "auto")
        self.h264_only = False          # learned when the player can't decode H.265
        self.skip_until = {}
        self.sessions = OrderedDict()   # clip id -> the session that loaded its page
        self.served = {}                # clip id -> the stream entry that was played
        self._plain = None
        self._lock = threading.Lock()

    def state(self):
        return {"source": self.preferred, "tikwm_style": self.tikwm.style,
                "tiktok": self.tiktok.prefs()}

    def by_name(self, name):
        return self.tiktok if name == "tiktok" else self.tikwm

    def order(self):
        mode = self.mode()
        if mode in ("tikwm", "tiktok"):
            return [self.by_name(mode)]
        first = self.by_name(self.preferred)
        both = [first, self.tikwm if first is self.tiktok else self.tiktok]
        now = time.time()
        usable = [s for s in both if self.skip_until.get(s.name, 0) <= now]
        return usable or both

    def _run(self, src, fn, problems):
        try:
            return fn()
        except SourceError as e:
            if e.blocked:
                self.skip_until[src.name] = time.time() + SKIP_BLOCKED
            problems.append((src.label, str(e)))
        except Exception as e:          # a bug in one source must not stop the others
            log("%s failed unexpectedly:\n%s" % (src.label, traceback.format_exc()))
            problems.append((src.label, "internal error (%s)" % e.__class__.__name__))
        return None

    def fetch_channel(self, channel, count, trace=None):
        """(videos, source name, newly found secUid or None). Blocking."""
        problems = []
        for src in self.order():
            result = self._run(src, lambda: src.user_posts(channel, count, trace), problems)
            if result is not None:
                self.skip_until.pop(src.name, None)
                if self.mode() == "auto":
                    self.preferred = src.name
                return result[0], src.name, result[1]
        raise SourceError(join_problems(problems))

    def channel_info(self, username, trace=None):
        """Profile of a channel being added; includes 'source' and maybe 'sec_uid'."""
        problems = []
        for src in self.order():
            info = self._run(src, lambda: src.user_info(username, trace), problems)
            if info is not None:
                info["source"] = src.name
                return info
        raise SourceError(join_problems(problems))

    def link_owner(self, url, trace=None):
        """Username behind a pasted TikTok link (profile, video or app share link)."""
        problems = []
        sources = [self.tiktok]
        if self.mode() != "tiktok" and self.skip_until.get("tikwm", 0) <= time.time():
            sources.append(self.tikwm)        # TikWM can look links up too, when it answers us
        for src in sources:
            try:
                return src.link_owner(url, trace)
            except SourceError as e:
                problems.append((src.label, str(e)))
            except Exception as e:
                log("%s link lookup failed unexpectedly:\n%s" % (src.label, traceback.format_exc()))
                problems.append((src.label, "internal error (%s)" % e.__class__.__name__))
        raise SourceError(join_problems(problems))

    # ------------------------------------------------------------------ links
    def needs_links(self, video):
        """True when the clip should get links from its page before it plays."""
        if video.get("links_from") == "page":
            expires = _expiry(video.get("streams")) or 1e12
            fresh_until = min(video.get("linked_at", 0) + LINK_TTL, expires - 120)
            return video["id"] not in self.sessions or time.time() > fresh_until
        if video.get("src") == "tikwm":
            return self.skip_until.get("tikwm", 0) > time.time()     # TikWM refuses us
        return True

    def prepare(self, video, trace=None):
        """Fresh links from the clip's page, in a session of its own. (ok, error). Blocking."""
        t0 = time.time()
        label = "@%s/%s" % (video.get("user") or "_", video["id"])
        try:
            session, streams = self.tiktok.resolve(video, trace)
        except SourceError as e:
            playlog("links %s: %s" % (label, e))
            return False, str(e)
        except Exception as e:
            log("link fetch failed unexpectedly:\n%s" % traceback.format_exc())
            return False, "internal error (%s)" % e.__class__.__name__
        if not streams:
            playlog("links %s: the clip page has no video links" % label)
            return False, "the clip page has no video links"
        with self._lock:
            self.sessions[video["id"]] = session
            self.sessions.move_to_end(video["id"])
            while len(self.sessions) > KEEP_SESSIONS:
                old = self.sessions.popitem(last=False)[1]
                try:
                    old.s.close()
                except Exception:
                    pass
        video.update({"src": "tiktok", "streams": streams, "links_from": "page",
                      "linked_at": time.time(),
                      "page": "%s/@%s/video/%s" % (src_tiktok.BASE, video.get("user") or "_", video["id"])})
        video.pop("good", None)
        playlog("links %s ready in %.1fs: %s" % (label, time.time() - t0, stream_kinds(streams)))
        return True, None

    def h264_wanted(self):
        return self.h264_only or self.codec() == "h264"

    def plain_session(self):
        with self._lock:
            if self._plain is None:
                self._plain = Session(ua=browser_ua())
            return self._plain

    def stream_plan(self, video, hd=False):
        """[(url, session, headers, stream entry), ...] in the order to try."""
        origin = video.get("links_from") or ("tikwm" if video.get("src") == "tikwm" else "list")
        if origin == "page":
            session = self.sessions.get(video["id"]) or self.tiktok.session()
            referer = video.get("page") or src_tiktok.BASE + "/"
        elif origin == "list":
            session = self.tiktok.session()
            referer = video.get("page") or src_tiktok.BASE + "/"
        else:
            session = self.plain_session()
            referer = "https://www.tikwm.com/"
        streams = video.get("streams")
        if not streams and video.get("play"):           # cache written by version 1.0
            streams = [[video["play"], "h264", 0, 0, 0, ""]]
        streams = order_streams(streams, hd)
        if self.h264_wanted():
            streams = [s for s in streams if s[1] == "h264"]
        if origin == "list":
            streams = streams[:2]        # TikTok's CDN usually refuses these; don't lose time
        good = video.get("good")
        streams.sort(key=lambda s: 0 if s[0] == good else 1)
        return [(s[0], session, {"Referer": referer}, s) for s in streams]

    def open_stream(self, video, hd=False, byte_range=None, trace=None):
        """Open the first working link of a clip: (response, None) or (None, reason).

        When every known link fails (refused, expired) fresh links are fetched
        from the clip's page, which also rescues TikWM clips when TikWM is blocked.
        """
        problems = []
        for attempt in range(2):
            plan = self.stream_plan(video, hd)
            if not plan and video.get("streams"):
                problems.append("no H.264 link for this clip" if self.h264_wanted() else "no usable link")
            for url, session, headers, entry in plan:
                h = dict(headers)
                h.update({"Accept": "*/*", "Accept-Encoding": "identity"})
                if byte_range:
                    h["Range"] = byte_range
                t0 = time.time()
                try:
                    resp = session.open(url, headers=h)
                except NetError as e:
                    note(trace, "stream %s -> failed: %s" % (host_of(url), e))
                    problems.append("%s: %s" % (host_of(url), e))
                    continue
                note(trace, "stream %s -> HTTP %d (%.1fs)" % (host_of(url), resp.status_code,
                                                             time.time() - t0))
                if resp.status_code in (200, 206, 416):
                    video["good"] = url
                    self.served[video["id"]] = entry
                    return resp, None
                problems.append("%s: HTTP %d" % (host_of(url), resp.status_code))
                resp.close()
            if attempt:
                break
            ok, err = self.prepare(video, trace)
            if not ok:
                problems.append("fresh link: %s" % err)
                break
        return None, "; ".join(problems[-3:]) or "no video link"

    def direct_url(self, video, hd=False):
        """Link with headers for the player itself (only if the relay can't start)."""
        plan = self.stream_plan(video, hd)
        if not plan:
            return None
        url, session, headers, _ = plan[0]
        extra = ["User-Agent=" + (session.ua or "Mozilla/5.0"), "Referer=" + headers["Referer"]]
        cookies = session.cookie_header(url)
        if cookies:
            extra.append("Cookie=" + cookies)
        return url + "#" + "&".join(extra)


class LinkResolver(object):
    """Background worker that gets clip links ready: the clip about to play first."""

    def __init__(self, sources, done):
        self.sources = sources
        self.done = done                 # done(video, ok, error), called from the worker thread
        self.queue = []
        self.active = None
        self.stopped = False
        self.cond = threading.Condition()
        self.thread = threading.Thread(target=self._run)
        self.thread.daemon = True
        self.thread.start()

    def want(self, videos):
        """Clips to prepare, most urgent first. Replaces the previous wish list."""
        with self.cond:
            active = self.active["id"] if self.active else None
            self.queue = [v for v in videos
                          if v and v["id"] != active and self.sources.needs_links(v)]
            self.cond.notify()

    def stop(self):
        with self.cond:
            self.stopped = True
            self.queue = []
            self.cond.notify()

    def _run(self):
        while True:
            with self.cond:
                while not self.queue and not self.stopped:
                    self.cond.wait()
                if self.stopped:
                    return
                video = self.active = self.queue.pop(0)
            try:
                if self.sources.needs_links(video):
                    ok, err = self.sources.prepare(video)
                else:
                    ok, err = True, None
            except Exception as e:
                ok, err = False, str(e)
            with self.cond:
                self.active = None
                stopped = self.stopped
            if not stopped:
                try:
                    self.done(video, ok, err)
                except Exception:
                    log("link callback failed:\n%s" % traceback.format_exc())
