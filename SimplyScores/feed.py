# -*- coding: utf-8 -*-
"""Per-channel video lists, a RAM cache in /tmp and the merged newest-first feed."""
import json
import os
import time

from .core import CACHE_DIR, ensure_dir, log

ALL = "__all__"     # key of the "For You" tab (all enabled channels merged)
LINK_KEYS = ("src", "streams", "links_from", "linked_at", "page", "good")


class FeedManager(object):
    def __init__(self, cache_dir=None):
        self.dir = os.path.join(cache_dir or CACHE_DIR, "feeds")
        ensure_dir(self.dir)
        self.videos = {}     # username -> [video, ...] newest first
        self.fetched = {}    # username -> time of last successful fetch
        self.errors = {}     # username -> last error message
        self.source = {}     # username -> "tikwm" / "tiktok"

    def _path(self, username):
        return os.path.join(self.dir, username + ".json")

    def load_cache(self, usernames):
        for user in usernames:
            try:
                with open(self._path(user), "r", encoding="utf-8") as f:
                    data = json.load(f)
                self.videos[user] = data.get("videos") or []
                self.fetched[user] = float(data.get("fetched") or 0)
                self.source[user] = data.get("source") or ""
            except Exception:
                pass

    def stale(self, usernames, max_age_seconds, now=None):
        now = now or time.time()
        return [u for u in usernames if now - self.fetched.get(u, 0) > max_age_seconds]

    def fetch(self, channel, count, sources):
        """Network fetch + cache write. Runs in a worker thread.

        Returns (videos, error, meta) where meta has 'source' and 'sec_uid'.
        """
        username = channel["username"]
        try:
            videos, source, sec_uid = sources.fetch_channel(channel, count)
        except Exception as e:
            log("@%s failed: %s" % (username, e))
            return None, str(e) or e.__class__.__name__, {}
        tmp = self._path(username) + ".tmp"
        try:
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump({"fetched": time.time(), "source": source, "videos": videos}, f,
                          ensure_ascii=False)
            os.replace(tmp, self._path(username))
        except Exception as e:
            log("cache write failed:", e)
        return videos, None, {"source": source, "sec_uid": sec_uid}

    def apply(self, username, videos, error, meta=None):
        """Store a fetch result. Call from the GUI thread."""
        if videos is not None:
            # keep playable links already fetched for clips that are still listed
            old = dict((v["id"], v) for v in self.videos.get(username) or [])
            for v in videos:
                o = old.get(v["id"])
                if o is not None and o.get("links_from") == "page":
                    v.update((k, o[k]) for k in LINK_KEYS if k in o)
            self.videos[username] = videos
            self.fetched[username] = time.time()
            self.errors.pop(username, None)
            self.source[username] = (meta or {}).get("source") or ""
        else:
            self.errors[username] = error or "error"

    def forget(self, username):
        self.videos.pop(username, None)
        self.fetched.pop(username, None)
        self.errors.pop(username, None)
        self.source.pop(username, None)
        try:
            os.remove(self._path(username))
        except OSError:
            pass

    def merged(self, usernames, max_age_days=0, now=None, preferred=()):
        """All videos of the given channels, newest first, without duplicates.
        Videos of preferred channels come first (each group newest first)."""
        now = now or time.time()
        cutoff = now - int(max_age_days) * 86400 if max_age_days else 0
        out, seen = [], set()
        for user in usernames:
            for v in self.videos.get(user) or []:
                if v["id"] in seen or v.get("created", 0) < cutoff:
                    continue
                seen.add(v["id"])
                out.append(v)
        out.sort(key=lambda v: (v.get("user") in preferred, v.get("created", 0), v["id"]), reverse=True)
        return out

    def summary(self, username):
        videos = self.videos.get(username) or []
        newest = max([v.get("created", 0) for v in videos] or [0])
        return len(videos), newest
