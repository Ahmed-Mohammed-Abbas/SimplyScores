# -*- coding: utf-8 -*-
"""A small web page on the receiver for adding and removing TikTok channels
from a phone or PC on the same network. It runs only while the channel
manager is open; the address is shown on the TV."""
import html
import socket
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from socketserver import ThreadingMixIn
from urllib.parse import parse_qs

from .core import log

PORTS = (8765, 8766, 8767, 0)

PAGE = """<!doctype html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">%(refresh)s
<title>SimplyScores channels</title>
<style>
body{font-family:system-ui,sans-serif;background:#111;color:#eee;margin:0;padding:16px;max-width:680px}
h1{font-size:22px;margin:0 0 12px}h1 span{color:#fe2c55}h2{font-size:17px;margin:22px 0 4px;color:#25f4ee}
form.add{display:flex;flex-direction:column;gap:8px;margin:12px 0}
textarea{width:100%%;box-sizing:border-box;min-height:84px;padding:12px;font-size:16px;border-radius:8px;
border:1px solid #444;background:#222;color:#fff;font-family:inherit}
button{padding:12px 16px;font-size:16px;border:0;border-radius:8px;background:#fe2c55;color:#fff}
button.minor{background:#333;padding:8px 12px;font-size:14px}button.go{background:#1f6f6c}
.msg{background:#1d2b2b;border-left:4px solid #25f4ee;padding:10px;margin:12px 0;white-space:pre-wrap}
.warn{border-left-color:#fe2c55}
ul{list-style:none;padding:0;margin:0}li{display:flex;align-items:center;justify-content:space-between;gap:8px;
padding:10px 0;border-bottom:1px solid #2a2a2a}small{color:#999}.off{opacity:.5}form.inline{display:inline}
.top{color:#fe2c55;font-size:12px;border:1px solid #fe2c55;border-radius:4px;padding:1px 4px}
</style></head><body>
<h1>Simply<span>Scores</span> channels</h1>
<p><small>Type TikTok usernames or paste links, one per line or separated by commas.
In the TikTok app: Share &rarr; Copy link on a video or profile, then paste it here.</small></p>
<form class="add" method="post" action="/add">
<textarea name="user" placeholder="kayfa1x_2&#10;https://vt.tiktok.com/...&#10;https://www.tiktok.com/@..." autocapitalize="none" autocorrect="off" spellcheck="false"></textarea>
<button type="submit">Add</button></form>
%(message)s%(anyway)s%(suggest)s
<h2>Your channels</h2>
<p><small>TOP = preferred: their videos come first in For You.</small></p>
<ul>%(rows)s</ul>
</body></html>"""


def _button(action, user, label, cls="minor", force=False):
    esc = html.escape
    return ('<form class="inline" method="post" action="%s"><input type="hidden" name="user" value="%s">%s'
            '<button class="%s">%s</button></form>' % (
                action, esc(user), '<input type="hidden" name="force" value="1">' if force else "",
                cls, esc(label)))


def lan_ip():
    """The receiver's address on the local network (no packet is sent)."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("10.255.255.255", 1))
        return s.getsockname()[0]
    except Exception:
        try:
            return socket.gethostbyname(socket.gethostname())
        except Exception:
            return "127.0.0.1"
    finally:
        s.close()


class _Server(ThreadingMixIn, HTTPServer):
    daemon_threads = True
    allow_reuse_address = True


class _Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.0"
    server_version = "SimplyScores"

    def log_message(self, fmt, *args):
        pass

    def _send(self, status, body=b"", ctype="text/html; charset=utf-8", headers=None):
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path.split("?")[0] != "/":
            return self._send(404, b"not found", "text/plain")
        self._send(200, self.server.page.render().encode("utf-8"))

    def do_POST(self):
        length = min(int(self.headers.get("Content-Length") or 0), 16384)
        form = parse_qs(self.rfile.read(length).decode("utf-8", "replace"))
        value = (form.get("user") or [""])[0]
        page = self.server.page
        if self.path == "/add":
            page.call(page.owner.web_add, value, (form.get("force") or [""])[0] == "1")
        elif self.path == "/remove":
            page.call(page.owner.web_remove, value)
        elif self.path == "/toggle":
            page.call(page.owner.web_toggle, value)
        elif self.path == "/prefer":
            page.call(page.owner.web_prefer, value)
        else:
            return self._send(404, b"not found", "text/plain")
        self._send(303, b"", headers={"Location": "/"})


class ChannelPage(object):
    """owner provides: channels(), suggestions(), web_status(), web_failed, checking,
    web_add(text, force), web_remove(username), web_toggle(username), web_prefer(username).
    call(fn, *args) runs fn on the Enigma2 main thread."""

    def __init__(self, owner, call):
        self.owner = owner
        self.call = call
        self.server = None
        for port in PORTS:
            try:
                self.server = _Server(("0.0.0.0", port), _Handler)
                break
            except OSError:
                continue
        if self.server is None:
            raise OSError("no free port for the channel page")
        self.server.page = self
        self.port = self.server.server_address[1]
        self.url = "http://%s:%d/" % (lan_ip(), self.port)
        t = threading.Thread(target=self.server.serve_forever, kwargs={"poll_interval": 0.5})
        t.daemon = True
        t.start()
        log("channel page on " + self.url)

    def render(self):
        esc = html.escape
        owner = self.owner
        rows = []
        for c in owner.channels():
            user = c["username"]
            top = c.get("preferred")
            rows.append('<li class="%s"><div>%s%s<br><small>@%s%s</small></div><div>%s %s %s</div></li>' % (
                "" if c["enabled"] else "off", '<b class="top">TOP</b> ' if top else "", esc(c["name"]),
                esc(user), "" if c["enabled"] else " (off)",
                _button("/prefer", user, "Unprefer" if top else "Prefer"),
                _button("/toggle", user, "Turn off" if c["enabled"] else "Turn on"),
                _button("/remove", user, "Remove")))
        status = owner.web_status()
        failed = list(owner.web_failed or [])
        message = ('<div class="msg%s">%s</div>' % (" warn" if failed else "", esc(status))) if status else ""
        anyway = "".join('<li><div>@%s<br><small>%s</small></div><div>%s</div></li>' % (
            esc(user), esc(reason.replace(" | ", "; ")[:160]), _button("/add", user, "Add @%s anyway" % user,
                                                                      force=True))
            for user, reason in failed)
        if anyway:
            anyway = "<ul>%s</ul>" % anyway
        suggest = ""
        fresh = owner.suggestions() if hasattr(owner, "suggestions") else []
        if fresh:
            items = "".join('<li><div>%s<br><small>@%s &middot; %s</small></div><div>%s</div></li>' % (
                esc(c["name"]), esc(c["username"]), esc(c["about"]), _button("/add", c["username"], "Add", "go"))
                for c in fresh)
            every = (_button("/add", ",".join(c["username"] for c in fresh),
                             "Add all %d" % len(fresh)) if len(fresh) > 1 else "")
            suggest = ('<h2>Suggested: match summaries and highlights</h2><ul>%s</ul><p>%s</p>' % (items, every))
        refresh = '<meta http-equiv="refresh" content="2">' if owner.checking else ""
        return PAGE % {"refresh": refresh, "message": message, "anyway": anyway, "suggest": suggest,
                       "rows": "".join(rows) or "<li>No channels yet.</li>"}

    def stop(self):
        server = self.server

        def shutdown():
            try:
                server.shutdown()
                server.server_close()
            except Exception:
                pass
        t = threading.Thread(target=shutdown)
        t.daemon = True
        t.start()
