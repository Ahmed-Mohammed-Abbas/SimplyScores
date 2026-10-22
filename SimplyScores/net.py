# -*- coding: utf-8 -*-
"""HTTP sessions for the video sources: browser-like headers, block detection
and a request log that the connection test shows to the user."""
import json
import random
import time
from email.utils import mktime_tz, parsedate_tz
from urllib.parse import urlparse

from .core import browser_ua, chrome_major, log, short_error

try:
    import requests
    try:
        requests.packages.urllib3.disable_warnings()
    except Exception:
        pass
except Exception:
    requests = None

_clock = {"offset": 0.0}


class NetError(Exception):
    """No HTTP answer at all (DNS, timeout, connection refused...)."""


class SourceError(Exception):
    """A video source could not deliver.

    blocked: the server refused this box (403, bot check...): try another source.
    final:   a definite answer such as 'account not found'.
    """

    def __init__(self, message, blocked=False, final=False):
        Exception.__init__(self, message)
        self.blocked = blocked
        self.final = final


# --------------------------------------------------------------------------
# Time: TikTok's video list is paged by timestamps, so a wrong box clock
# would hide new videos. Servers' Date headers correct it.
# --------------------------------------------------------------------------
def now():
    return time.time() + _clock["offset"]


def clock_offset():
    return _clock["offset"]


def _note_date(value):
    if not value:
        return
    try:
        diff = mktime_tz(parsedate_tz(value)) - time.time()
    except Exception:
        return
    _clock["offset"] = diff if abs(diff) > 120 else 0.0


# --------------------------------------------------------------------------
# Header helpers
# --------------------------------------------------------------------------
def client_hints():
    v = chrome_major()
    return {"sec-ch-ua": '"Google Chrome";v="%d", "Chromium";v="%d", "Not/A)Brand";v="24"' % (v, v),
            "sec-ch-ua-mobile": "?0",
            "sec-ch-ua-platform": '"Windows"'}


def junk_headers(low=2, high=6):
    """Random harmless headers that change the request's header fingerprint.

    yt-dlp does the same to get past TikTok's HTTP 403 blocks.
    """
    letters = "bcdfghjklmnpqrstvwxz"

    def word(a, b):
        return "".join(random.choice(letters) for _ in range(random.randint(a, b)))
    return dict((word(8, 20), word(12, 28)) for _ in range(random.randint(low, high)))


# --------------------------------------------------------------------------
# Replies
# --------------------------------------------------------------------------
class Reply(object):
    def __init__(self, status, headers, content, url, insecure=False, elapsed=0.0):
        self.status = status
        self.headers = dict((k.lower(), v) for k, v in (headers or {}).items())
        self.content = content or b""
        self.url = url
        self.insecure = insecure
        self.elapsed = elapsed
        self._text = None

    @property
    def text(self):
        if self._text is None:
            self._text = self.content.decode("utf-8", "replace")
        return self._text

    def json(self):
        return json.loads(self.text)


def block_reason(reply):
    """Why a server refused us, in a few words ('' when it doesn't look like a block)."""
    h = reply.headers
    body = reply.text[:8000].lower() if reply.content else ""
    cloudflare = "cf-ray" in h or "cloudflare" in h.get("server", "").lower()
    if h.get("cf-mitigated") == "challenge" or (cloudflare and (
            "just a moment" in body or "challenge-platform" in body or "cf-chl" in body)):
        return "Cloudflare challenge"
    if cloudflare and reply.status >= 400:
        if "1010" in body or "browser signature" in body or "browser_signature" in body:
            return "Cloudflare banned this client"
        if "1020" in body or "access denied" in body:
            return "Cloudflare firewall rule"
        if "1015" in body or reply.status == 429:
            return "Cloudflare rate limit"
        if "1006" in body or "1007" in body or "1008" in body:
            return "Cloudflare banned this IP"
        return "Cloudflare"
    if "_wafchallengeid" in body or ('id="cs"' in body and "please wait" in body):
        return "TikTok bot check"
    if reply.status == 429:
        return "rate limited"
    if reply.insecure and reply.status != 200:
        return "network filter? (certificate mismatch)"
    return ""


def describe(reply):
    why = block_reason(reply)
    return "HTTP %d%s" % (reply.status, (" (%s)" % why) if why else "")


def short_url(url):
    p = urlparse(url)
    path = p.path if len(p.path) <= 50 else p.path[:47] + "..."
    return p.netloc + path


def host_of(url):
    return urlparse(url).netloc or url[:30]


def note(trace, text):
    log(text)
    if trace is not None:
        trace.append(text)


# --------------------------------------------------------------------------
# Session
# --------------------------------------------------------------------------
class Session(object):
    """requests.Session wrapper. ua=None keeps the requests default User-Agent."""

    def __init__(self, ua=None, headers=None):
        if requests is None:
            raise NetError("python3-requests is not installed")
        self.s = requests.Session()
        if ua:
            self.s.headers["User-Agent"] = ua
        self.s.headers["Accept-Language"] = "en-US,en;q=0.9"
        if headers:
            self.s.headers.update(headers)
        self.ua = self.s.headers.get("User-Agent")

    def _send(self, method, url, **kw):
        try:
            try:
                return self.s.request(method, url, **kw), False
            except requests.exceptions.SSLError:
                # Old receivers often have an outdated CA bundle or a wrong clock.
                log("certificate check failed for %s - retrying without it" % host_of(url))
                kw["verify"] = False
                return self.s.request(method, url, **kw), True
        except requests.RequestException as e:
            raise NetError(short_error(e))

    def request(self, method, url, params=None, data=None, headers=None, timeout=15,
                trace=None, label="", allow_redirects=True):
        t0 = time.time()
        try:
            r, insecure = self._send(method, url, params=params, data=data, headers=headers,
                                     timeout=timeout, allow_redirects=allow_redirects)
        except NetError as e:
            note(trace, "%s %s %s -> failed: %s (%.1fs)" % (label, method, short_url(url), e,
                                                           time.time() - t0))
            raise
        reply = Reply(r.status_code, r.headers, r.content, r.url, insecure, time.time() - t0)
        _note_date(reply.headers.get("date"))
        note(trace, "%s %s %s -> %s, %d bytes (%.1fs)%s" % (
            label, method, short_url(url), describe(reply), len(reply.content), reply.elapsed,
            " [certificate check off]" if insecure else ""))
        return reply

    def open(self, url, headers=None, timeout=(8, 25)):
        """Streaming GET for the video relay. The caller must close() the response."""
        return self._send("GET", url, headers=headers, timeout=timeout, stream=True,
                          allow_redirects=True)[0]

    def cookie(self, name):
        for c in self.s.cookies:
            if c.name == name:
                return c.value
        return None

    def cookie_header(self, url):
        host = urlparse(url).hostname or ""
        pairs = []
        for c in self.s.cookies:
            domain = (c.domain or "").lstrip(".")
            if domain and (host == domain or host.endswith("." + domain)):
                pairs.append("%s=%s" % (c.name, c.value))
        return "; ".join(pairs)

    def set_cookie(self, name, value, domain):
        self.s.cookies.set(name, value, domain=domain, path="/")

    def drop_cookie(self, name, domain):
        try:
            self.s.cookies.clear(domain, "/", name)
        except KeyError:
            pass


__all__ = ["NetError", "SourceError", "Session", "Reply", "block_reason", "describe", "browser_ua",
           "client_hints", "junk_headers", "now", "clock_offset", "note", "host_of", "short_url"]
