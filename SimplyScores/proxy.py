# -*- coding: utf-8 -*-
"""Local stream relay on 127.0.0.1 for the receiver's player.

The player asks for http://127.0.0.1:<port>/play/<id>.mp4. The relay fetches
the clip with the session, cookies and Referer the CDN expects, forwards Range
requests (seeking), tries the next link (or a fresh one) when a link fails,
and fixes the HE-AAC audio header the receivers' audio sink can't handle
(see audiofix.py). /play/<id>.ts is the same clip converted by ffmpeg.
"""
import re
import socket
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from socketserver import ThreadingMixIn

from . import audiofix, transcode
from .core import log, playlog

_PATH_RE = re.compile(r"^/play/([A-Za-z0-9_-]{1,40})\.(mp4|ts)")
_RANGE_RE = re.compile(r"bytes\s+(\d+)-")
_PASS_HEADERS = ("Content-Type", "Content-Length", "Content-Range", "Accept-Ranges",
                 "Last-Modified", "ETag")


class _Server(ThreadingMixIn, HTTPServer):
    daemon_threads = True
    allow_reuse_address = True


class _Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.0"
    server_version = "SimplyScores"

    def log_message(self, fmt, *args):
        pass

    def do_HEAD(self):
        self._serve(head=True)

    def do_GET(self):
        self._serve(head=False)

    def _serve(self, head):
        relay = self.server.relay
        m = _PATH_RE.match(self.path)
        entry = relay.entries.get(m.group(1)) if m else None
        if entry is None:
            self.send_error(404)
            return
        if m.group(2) == "ts":
            self._serve_converted(relay, entry[0])
        else:
            self._serve_clip(relay, entry[0], entry[1], head)

    def _serve_clip(self, relay, video, hd, head):
        vid = video["id"]
        t0 = time.time()
        resp, error = relay.sources.open_stream(video, hd, self.headers.get("Range"))
        if resp is None:
            relay.errors[vid] = error
            playlog("relay %s: no working link (%s)" % (vid, error))
            try:
                self.send_error(502)
            except Exception:
                pass
            return
        relay.errors.pop(vid, None)
        if vid not in relay.logged:
            relay.logged.add(vid)
            from .sources import describe_stream
            playlog("relay %s: HTTP %d, %s, first answer after %.1fs" % (
                vid, resp.status_code, describe_stream(relay.sources.served.get(vid)), time.time() - t0))
        try:
            self.send_response(resp.status_code)
            for name in _PASS_HEADERS:
                value = resp.headers.get(name)
                if value:
                    self.send_header(name, value)
            if not resp.headers.get("Content-Type"):
                self.send_header("Content-Type", "video/mp4")
            self.end_headers()
            if head:
                return
            chunks = resp.iter_content(65536)
            if relay.fix_audio():
                fixer = relay.fixer(video.get("good") or "")
                had_media = fixer.media is not None
                m = _RANGE_RE.match(resp.headers.get("Content-Range") or "")
                chunks = fixer.wrap(chunks, int(m.group(1)) if m and resp.status_code == 206 else 0)
            else:
                fixer, had_media = None, True
            for chunk in chunks:
                if fixer is not None and not had_media and fixer.media is not None:
                    had_media = True
                    relay.note_media(vid, fixer)
                self.wfile.write(chunk)
        except (socket.error, OSError, ValueError):
            pass                        # the player stopped or seeked: normal
        except Exception as e:
            log("relay error:", e)
        finally:
            resp.close()

    def _serve_converted(self, relay, video):
        vid = video["id"]
        try:
            conv = transcode.Converter("http://127.0.0.1:%d/play/%s.mp4" % (relay.port, vid))
        except Exception as e:
            relay.convert_failed = "ffmpeg: %s" % e
            relay.errors[vid] = relay.convert_failed
            self.send_error(502)
            return
        try:
            first = conv.read(timeout=25)
            if not first:
                relay.convert_failed = "ffmpeg: " + (conv.error() if first == b"" else "no output within 25 s")
                relay.errors[vid] = relay.convert_failed
                playlog("relay %s: audio conversion failed: %s" % (vid, relay.convert_failed))
                self.send_error(502)
                return
            if vid not in relay.converted:
                relay.converted.add(vid)
                playlog("relay %s: converting the audio to MP2 with ffmpeg" % vid)
            self.send_response(200)
            self.send_header("Content-Type", "video/mp2t")
            self.end_headers()
            self.wfile.write(first)
            while True:
                chunk = conv.read()
                if not chunk:
                    break
                self.wfile.write(chunk)
        except (socket.error, OSError, ValueError):
            pass
        except Exception as e:
            log("conversion error:", e)
        finally:
            conv.stop()


class StreamProxy(object):
    def __init__(self, sources, audio_mode=None):
        self.sources = sources
        self.audio_mode = audio_mode or (lambda: "fix")
        self.entries = {}
        self.errors = {}
        self.logged = set()
        self.converted = set()
        self.convert_failed = None
        self.media = {}                 # clip id -> parse_moov() result (tracks, audio type)
        self._fixers = {}
        self._lock = threading.Lock()
        self.server = _Server(("127.0.0.1", 0), _Handler)
        self.server.relay = self
        self.port = self.server.server_address[1]
        self.thread = threading.Thread(target=self.server.serve_forever, kwargs={"poll_interval": 0.5})
        self.thread.daemon = True
        self.thread.start()
        log("stream relay on 127.0.0.1:%d" % self.port)

    def fix_audio(self):
        return self.audio_mode() in ("fix", "convert")

    def fixer(self, url):
        with self._lock:
            fixer = self._fixers.get(url)
            if fixer is None:
                fixer = self._fixers[url] = audiofix.StreamFixer()
                if len(self._fixers) > 40:
                    self._fixers.pop(next(iter(self._fixers)))
            return fixer

    def note_media(self, vid, fixer):
        self.media[vid] = fixer.media
        playlog("relay %s: %s, %s%s" % (
            vid, audiofix.describe_video(fixer.media.get("video")),
            audiofix.describe_audio(fixer.media.get("audio")),
            " -> audio header fixed for the receiver" if fixer.patch else ""))

    def url(self, video, hd=False, convert=False):
        self.entries[video["id"]] = (video, hd)
        return "http://127.0.0.1:%d/play/%s.%s" % (self.port, video["id"], "ts" if convert else "mp4")

    def error(self, video_id):
        return self.errors.get(video_id)

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
