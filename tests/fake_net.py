"""A small fake internet for the tests: TikWM (behind a fake Cloudflare), TikTok
(pages with the SHA-256 bot check, the item_list API, a CDN that wants the
session cookie), ESPN and images. Scenario switches live on World."""
import base64
import hashlib
import json
import os
import random
import re
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from socketserver import ThreadingMixIn
from urllib.parse import parse_qs, urlparse

import sample_data

TOKEN = "chain-token-42"
MP4 = b"\x00\x00\x00\x18ftypmp42\x00\x00\x00\x00mp42isom" + bytes(range(256)) * 800
CF_PAGE = (b"<!DOCTYPE html><html><head><title>Just a moment...</title></head><body>"
           b"<script src=\"/cdn-cgi/challenge-platform/h/b/orchestrate/chl_page/v1\"></script>"
           b"</body></html>")


def sec_uid(user):
    return "MS4wLjABAAAA" + hashlib.sha256(user.encode()).hexdigest()[:64]


class World(object):
    def __init__(self):
        self.base = ""
        self.reset()

    def reset(self):
        self.tikwm = "blocked"          # blocked | ok | apex_get_only
        self.tiktok_page = "challenge"  # challenge | ok | blocked
        self.tiktok_api = "ok"          # ok | empty | blocked
        self.no_sec_uid = set()         # profiles that lack the secUid
        self.expired = set()            # CDN query fragments answered with 403
        self.list_links_work = False    # like the real report: CDN refuses video-list links
        self.clip_page_bare_only = True  # clip pages: 403 unless User-Agent is "Mozilla/5.0"
        self.hevc_only = set()          # clip ids whose page offers H.265 links only
        self.clip_bytes = MP4           # what the TikTok CDN serves for every clip
        self.media = getattr(self, "media", {})     # /media/<name> files (kept across resets)
        # share links: code -> where TikTok redirects it ("head405:" = no HEAD, canonical link in the page)
        self.short_links = {
            "ZSspl01": "https://www.tiktok.com/@spl/video/%s?_r=1&_t=ZS-8x" % sample_data._vid("spl", 0),
            "ZMold433": "https://m.tiktok.com/v/%s.html?u_code=x" % sample_data._vid("433", 0),
            "ZTbr": "head405:https://www.tiktok.com/@brfootball/video/%s" % sample_data._vid("brfootball", 0),
            "ZShome": "https://www.tiktok.com/",
            "ZSchain": "https://vt.tiktok.com/ZSspl01/",
        }
        self.gh_files = getattr(self, "gh_files", {})   # GitHub raw files: path -> bytes
        self.hits = {}
        self.challenges = {}
        self.lock = threading.Lock()

    def hit(self, key):
        with self.lock:
            self.hits[key] = self.hits.get(key, 0) + 1


WORLD = World()


def tiktok_item(user, i, age, caption, dur, tag="list", token="none"):
    base = WORLD.base
    vid = sample_data._vid(user, i)
    cdn = base + "/cdn/%s.mp4?tk=%s&" % (vid, token)
    if tag == "fresh" and vid in WORLD.hevc_only:
        return {
            "id": vid, "desc": caption, "createTime": int(sample_data.NOW - age),
            "author": {"id": "1", "uniqueId": user, "nickname": sample_data.NICK[user], "secUid": sec_uid(user)},
            "video": {"id": vid, "duration": dur, "width": 1080, "height": 1920, "codecType": "h265_hvc1",
                      "playAddr": cdn + "c=hevc_play&src=fresh",
                      "bitrateInfo": [{"Bitrate": 1800000, "CodecType": "h265_hvc1",
                                       "PlayAddr": {"Width": 1080, "Height": 1920,
                                                    "UrlList": [cdn + "c=hevc&src=fresh"]}}]},
            "stats": {}, "music": {}}
    return {
        "id": vid, "desc": caption, "createTime": int(sample_data.NOW - age),
        "author": {"id": "1", "uniqueId": user, "nickname": sample_data.NICK[user],
                   "secUid": sec_uid(user), "avatarThumb": base + "/img/avatar/%s.jpeg" % user},
        "video": {
            "id": vid, "duration": dur, "width": 576, "height": 1024, "codecType": "h264",
            "cover": base + "/img/cover/%s.jpeg" % vid,
            "playAddr": cdn + "c=play&src=" + tag,
            "downloadAddr": cdn + "c=dl&src=" + tag,
            "bitrateInfo": [
                {"Bitrate": 1800000, "CodecType": "bytevc1",
                 "PlayAddr": {"UrlKey": "v12044gd0000_bytevc1_1080p_1800000", "Width": 1080,
                              "Height": 1920, "UrlList": [cdn + "c=hevc&src=" + tag]}},
                {"Bitrate": 1200000, "CodecType": "h264",
                 "PlayAddr": {"UrlKey": "v12044gd0000_h264_720p_1200000", "Width": 720, "Height": 1280,
                              "UrlList": [cdn + "c=h264_720&src=" + tag, cdn + "c=h264_720b&src=" + tag,
                                          "https://www.tiktok.com/aweme/v1/play/?video_id=" + vid]}},
                {"Bitrate": 700000, "CodecType": "h264",
                 "PlayAddr": {"UrlKey": "v12044gd0000_h264_540p_700000", "Width": 576, "Height": 1024,
                              "UrlList": [cdn + "c=h264_540&src=" + tag]}},
                {"Bitrate": 500000, "CodecType": "bytevc2",
                 "PlayAddr": {"UrlList": [cdn + "c=vvc&src=" + tag]}},
            ]},
        "stats": {"playCount": 1200000 // (i + 1), "diggCount": 98400 // (i + 1),
                  "commentCount": 2310 // (i + 1), "shareCount": 870 // (i + 1), "collectCount": 4000},
        "music": {"title": "original sound", "authorName": sample_data.NICK[user]},
    }


def tiktok_items(user, token="none"):
    items = [tiktok_item(user, i, age, cap, dur, token=token)
             for i, (age, cap, dur) in enumerate(sample_data.CAPTIONS[user])]
    pinned = tiktok_item(user, 90, 60 * 86400, "Pinned: channel trailer", 30, token=token)
    pinned["isPinnedItem"] = True
    photo = tiktok_item(user, 91, 60, "Photo slideshow", 0, token=token)
    photo["imagePost"] = {"images": [{"imageURL": {"urlList": ["x"]}}]}
    return [pinned, photo] + items


def challenge_page():
    prefix = os.urandom(12)
    answer = random.randint(500, 20000)
    a = base64.b64encode(prefix).decode()
    c = base64.b64encode(hashlib.sha256(prefix + str(answer).encode()).digest()).decode()
    WORLD.challenges[a] = c
    cs = base64.b64encode(json.dumps({"v": {"a": a, "c": c}, "s": "x1"}).encode()).decode().rstrip("=")
    return ('<html><head><title>Please wait...</title></head><body><p class="%s" id="cs"></p>'
            '<p id="wci" class="_wafchallengeid"></p><p id="rci" class="waforiginalreid"></p>'
            '<p id="rs" class="r-77"></p>Please wait...</body></html>' % cs).encode()


def challenge_passed(cookie_header):
    m = re.search(r"_wafchallengeid=([^;]+)", cookie_header or "")
    if not m:
        return False
    try:
        data = json.loads(base64.b64decode(m.group(1)))
        a, c = data["v"]["a"], data["v"]["c"]
        number = base64.b64decode(data["d"])
    except Exception:
        return False
    return WORLD.challenges.get(a) == c and hashlib.sha256(base64.b64decode(a) + number).digest() == base64.b64decode(c)


def page(scope):
    return ('<html><head><script id="__UNIVERSAL_DATA_FOR_REHYDRATION__" type="application/json">%s'
            '</script></head><body></body></html>' % json.dumps({"__DEFAULT_SCOPE__": scope})).encode()


def profile_scope(user):
    if user not in sample_data.CAPTIONS:
        return {"webapp.user-detail": {"statusCode": 10221, "statusMsg": "user not exist", "userInfo": {}}}
    return {"webapp.user-detail": {"statusCode": 0, "userInfo": {
        "user": {"id": "1", "uniqueId": user, "nickname": sample_data.NICK[user],
                 "avatarThumb": WORLD.base + "/img/avatar/%s.jpeg" % user,
                 "secUid": "" if user in WORLD.no_sec_uid else sec_uid(user), "privateAccount": False},
        "stats": {"followerCount": 1534000, "videoCount": 812}}}}


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.0"

    def log_message(self, *args):
        pass

    def do_GET(self):
        self.route("GET", {})

    def do_HEAD(self):
        self.route("HEAD", {})

    def do_POST(self):
        body = self.rfile.read(int(self.headers.get("Content-Length") or 0)).decode()
        self.route("POST", parse_qs(body))

    def reply(self, status, body=b"", ctype="text/html", headers=None):
        if self.command == "HEAD":
            body = b""
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def short_link(self, method, code):
        """vm./vt.tiktok.com/<code>/ and tiktok.com/t/<code>/ share links."""
        WORLD.hit("short_link")
        target = WORLD.short_links.get(code)
        if target is None:
            return self.reply(404, b"<html>Not found</html>")
        if self.headers.get("User-Agent") != "facebookexternalhit/1.1":
            # browsers get the app's landing page; link-preview robots get a plain redirect
            return self.reply(200, b"<html><script>window.location='/foryou'</script></html>")
        if target.startswith("head405:"):
            target = target[8:]
            if method == "HEAD":
                return self.reply(405, b"")
            escaped = target.replace("/", "\\u002F")      # as TikTok writes URLs inside its page JSON
            return self.reply(200, ('<html><script id="data">{"canonical":"%s"}</script></html>' % escaped).encode())
        return self.reply(301, b"", headers={"Location": target})

    def json(self, data, headers=None):
        self.reply(200, json.dumps(data).encode(), "application/json", headers)

    def cloudflare(self):
        self.reply(403, CF_PAGE, headers={"Server": "cloudflare", "CF-RAY": "8d2c4f-BGW",
                                          "cf-mitigated": "challenge"})

    def media(self, data):
        rng = self.headers.get("Range")
        if rng:
            m = re.match(r"bytes=(\d+)-(\d*)", rng)
            start = int(m.group(1))
            end = min(int(m.group(2)) if m.group(2) else len(data) - 1, len(data) - 1)
            if start >= len(data):
                return self.reply(416, b"", headers={"Content-Range": "bytes */%d" % len(data)})
            return self.reply(206, data[start:end + 1], "video/mp4", {
                "Content-Range": "bytes %d-%d/%d" % (start, end, len(data)), "Accept-Ranges": "bytes"})
        self.reply(200, data, "video/mp4", {"Accept-Ranges": "bytes"})

    def route(self, method, form):
        url = urlparse(self.path)
        q = dict((k, v[0]) for k, v in parse_qs(url.query).items())
        q.update(dict((k, v[0]) for k, v in form.items()))
        path = url.path
        cookies = self.headers.get("Cookie") or ""

        m = re.match(r"^/(tw|twa)(/.*)$", path)
        if m:
            host, rest = m.groups()
            if rest.startswith("/api/"):
                WORLD.hit("tikwm_api")
                allowed = WORLD.tikwm == "ok" or (WORLD.tikwm == "apex_get_only" and host == "twa" and method == "GET")
                if not allowed:
                    return self.cloudflare()
                user = (q.get("unique_id") or "").lstrip("@")
                if rest == "/api/user/posts":
                    return self.json(sample_data.tikwm_posts(user))
                if rest == "/api/":
                    link = q.get("url") or ""
                    code = link.rstrip("/").rsplit("/", 1)[-1]
                    target = WORLD.short_links.get(code, link).split(":", 1)[-1]
                    m = re.search(r"@([\w.]+)/video/", target)
                    vm = re.search(r"/v/(\d+)", target)
                    owner = m.group(1) if m else next((u for u in sample_data.CAPTIONS for i in range(9)
                                                       if vm and sample_data._vid(u, i) == vm.group(1)), None)
                    if not owner:
                        return self.json({"code": -1, "msg": "Url parsing is failed! Please check url."})
                    return self.json({"code": 0, "data": {"id": "1", "author": {"unique_id": owner}}})
                if rest == "/api/user/info":
                    data = sample_data.tikwm_info(user)
                    if data.get("data"):
                        data["data"]["user"]["secUid"] = sec_uid(user)
                    return self.json(data)
                return self.reply(404)
            if WORLD.tikwm == "blocked":
                return self.cloudflare()
            vm = re.match(r"^/video/media/(?:hd)?play/(\d+)\.mp4$", rest)
            if vm:
                return self.reply(302, b"", headers={"Location": WORLD.base + "/cdn-open/%s.mp4" % vm.group(1)})
            return self.reply(200, sample_data.image_bytes(rest), "image/jpeg")

        sm = re.match(r"^/(?:vm|vt|tt/t)/(\w+)/?$", path)
        if sm:
            return self.short_link(method, sm.group(1))

        if path.startswith("/cdn-open/"):
            return self.media(MP4)

        if path.startswith("/cdn/"):
            WORLD.hit("cdn")
            WORLD.hit("cdn:" + q.get("c", ""))
            m = re.search(r"tt_chain_token=([^;]+)", cookies)
            if not m or m.group(1) != q.get("tk"):
                WORLD.hit("cdn_refused")
                return self.reply(403, b"token mismatch")
            if any(marker in url.query + "&" for marker in WORLD.expired):
                WORLD.hit("cdn_refused")
                return self.reply(403, b"expired")
            return self.media(WORLD.clip_bytes)

        if path.startswith("/media/"):
            data = WORLD.media.get(path[7:])
            return self.media(data) if data is not None else self.reply(404)

        if path.startswith("/tt/api/creator/item_list/"):
            WORLD.hit("tiktok_api")
            if WORLD.tiktok_api == "blocked":
                return self.reply(403, b"denied")
            if WORLD.tiktok_api == "empty":
                return self.reply(200, b"", "application/json")
            user = next((u for u in sample_data.CAPTIONS if sec_uid(u) == q.get("secUid")), None)
            if user is None:
                return self.json({"statusCode": 10201, "statusMsg": "unknown secUid"})
            cursor = int(q.get("cursor") or 0) // 1000
            m = re.search(r"tt_chain_token=([^;]+)", cookies)
            token = m.group(1) if (m and WORLD.list_links_work) else "listbogus"
            items = sorted((it for it in tiktok_items(user, token) if it["createTime"] <= cursor),
                           key=lambda it: -it["createTime"])
            count = int(q.get("count") or 15)
            return self.json({"statusCode": 0, "itemList": items[:count],
                              "hasMorePrevious": len(items) > count})

        if path.startswith("/tt/"):
            WORLD.hit("tiktok_page")
            if WORLD.tiktok_page == "blocked":
                return self.reply(403, b"<html>Access Denied</html>")
            em = re.match(r"^/tt/embed/@([\w.]+)$", path)
            if em:
                user = em.group(1)
                state = {"source": {"data": {"/embed/@" + user: {"videoList": [
                    {"id": it["id"]} for it in tiktok_items(user)[2:5]]}}}}
                return self.reply(200, ('<script id="__FRONTITY_CONNECT_STATE__" type="application/json">%s'
                                        '</script>' % json.dumps(state)).encode())
            vm = re.match(r"^/tt/@([\w.]+)/video/(\d+)$", path)
            if vm and WORLD.clip_page_bare_only and self.headers.get("User-Agent") != "Mozilla/5.0":
                WORLD.hit("clip_page_refused")
                return self.reply(403, b"")
            if WORLD.tiktok_page == "challenge" and not challenge_passed(cookies):
                return self.reply(200, challenge_page())
            if vm:
                # every clip page load hands out a new token; its links only work with it
                token = "t%06d" % random.randint(0, 999999)
                set_cookie = {"Set-Cookie": "tt_chain_token=%s; Path=/; HttpOnly" % token}
                WORLD.hit("clip_page")
                user, vid = vm.groups()
                if user == "_":                 # "@_/video/<id>": TikTok finds the clip by its id
                    user = next((u for u in sample_data.CAPTIONS for i in range(len(sample_data.CAPTIONS[u]))
                                 if sample_data._vid(u, i) == vid), "_")
                for i, (age, cap, dur) in enumerate(sample_data.CAPTIONS.get(user, [])):
                    if sample_data._vid(user, i) == vid:
                        scope = {"webapp.video-detail": {"statusCode": 0, "itemInfo": {
                            "itemStruct": tiktok_item(user, i, age, cap, dur, tag="fresh", token=token)}}}
                        return self.reply(200, page(scope), headers=set_cookie)
                return self.reply(200, page({"webapp.video-detail": {"statusCode": 10204}}), headers=set_cookie)
            pm = re.match(r"^/tt/@([\w.]+)$", path)
            if pm:
                headers = {}
                if "tt_chain_token=" not in cookies:
                    headers["Set-Cookie"] = "tt_chain_token=%s; Path=/; HttpOnly" % TOKEN
                return self.reply(200, page(profile_scope(pm.group(1))), headers=headers)
            return self.reply(404)

        if path.startswith("/gh/"):
            WORLD.hit("github")
            data = WORLD.gh_files.get(path[4:])
            return self.reply(200, data, "text/plain") if data is not None else self.reply(404, b"404: Not Found")

        if path.startswith("/espn/"):
            return self.json(sample_data.espn(path))
        if path.startswith("/img/"):
            return self.reply(200, sample_data.image_bytes(path), "image/jpeg")
        self.reply(404)


class _Server(ThreadingMixIn, HTTPServer):
    daemon_threads = True


def start():
    server = _Server(("127.0.0.1", 0), Handler)
    WORLD.base = "http://127.0.0.1:%d" % server.server_address[1]
    t = threading.Thread(target=server.serve_forever)
    t.daemon = True
    t.start()
    return WORLD
