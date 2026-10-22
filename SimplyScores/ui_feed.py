# -*- coding: utf-8 -*-
"""TikTok-style vertical feed: one clip at a time, newest first, with live scores."""
import threading
import time

from enigma import ePoint, eServiceReference, iPlayableService, iServiceInformation
from twisted.internet import reactor

from Components.ActionMap import ActionMap
from Components.Label import Label
from Components.Pixmap import Pixmap
from Components.ProgressBar import ProgressBar
from Components.ServiceEventTracker import ServiceEventTracker
from Components.config import config, configfile
from Screens.MessageBox import MessageBox
from Screens.Screen import Screen
from Tools.LoadPixmap import LoadPixmap

from . import api_scores, transcode
from .core import ChannelStore, fix_bidi, fmt_count, fmt_duration, is_rtl, log, playlog, time_ago
from .feed import ALL, FeedManager
from .proxy import StreamProxy
from .sources import LinkResolver, Sources, describe_stream
from .gui import (ACTION_WIDGETS, CENTER, FEED_SKIN, ICONS, LEFT, MCList, P, POST_WIDGETS,
                  RIGHT, RIGHT_WIDGETS, SCORE_WIDGETS, T, Timer, WRAP_LEFT, WRAP_RIGHT, s,
                  set_rtl)
from .images import HAVE_PIL, ImageCache

LABELS = ("card_scores", "score_tag", "score_title", "score_page", "card_post", "author", "meta",
          "badge", "caption", "tags", "music", "tab_cur", "tab_line", "tab_side", "pill",
          "center_msg", "likes", "comments", "shares", "views", "position", "card_next",
          "next_title", "status", "card_keys", "key_red_dot", "key_red", "key_green_dot",
          "key_green", "key_yellow_dot", "key_yellow", "key_blue_dot", "key_blue", "key_hint",
          "card_nav", "nav_up_txt", "nav_down_txt", "nav_side_txt")
PIXMAPS = ("cover", "avatar", "follow_icon", "like_icon", "comment_icon", "share_icon",
           "views_icon", "disc_icon", "music_icon", "pause_icon", "nav_up", "nav_down", "nav_left",
           "nav_right")
UPNEXT_ROWS = 2

SCORE_ROWS = 6
CAPTION_TOP, CAPTION_HEIGHT = 734, 166   # must match the skin
START_TIMEOUT = 25          # seconds before a clip that never starts counts as failed
LINK_TIMEOUT = 40           # seconds to wait for a clip's links from TikTok
PTS = 90000                 # player clock ticks per second
SOURCE_NAMES = {"tikwm": "TikWM", "tiktok": "TikTok direct"}


def short_problem(text, limit=150):
    """'TikWM: HTTP 403 Cloudflare challenge | TikTok: ...' -> one line per source."""
    lines = [part.strip() for part in (text or "").split(" | ") if part.strip()]
    out = "\n".join(line if len(line) <= 70 else line[:67] + "..." for line in lines[:2])
    return out[:limit]


def in_gui(fn, *args):
    """Run fn on the Enigma2 main thread (safe from worker threads)."""
    reactor.callFromThread(fn, *args)


class SimplyScoresFeed(Screen):
    def __init__(self, session):
        Screen.__init__(self, session)
        self.skin = FEED_SKIN
        self.skinName = "SimplyScoresFeed"
        self.cfg = config.plugins.simplyscores
        self.store = ChannelStore()
        self.feed = FeedManager()
        self.images = ImageCache(self._imageReadyThread)
        self.sources = Sources(self.store.extra.get("net"), mode=lambda: self.cfg.source.value,
                               codec=lambda: self.cfg.codec.value)
        self.resolver = LinkResolver(self.sources, self._linksReadyThread)
        self.proxy = None
        self.used_sources = set()
        self.pending_links = None     # id of the clip waiting for its links
        self.links_started = 0.0
        self.converting = False       # current clip goes through ffmpeg
        self.ffmpeg_hint_shown = False
        self.alive = True

        self.tabs = []
        self.tab = 0
        self.clips = []
        self.index = 0
        self.playing = None          # id of the clip handed to the player
        self.waiting = False         # clip requested but no picture yet
        self.paused = False
        self.finished = False
        self.landscape = False
        self.clean = False
        self.started = 0.0
        self.refreshing = False
        self.jump_top = True         # jump to the newest clip when the first update lands
        self.seen_top = 0            # newest upload time the viewer has reached
        self.prev_visit = self.store.last_visit
        self.opened = time.time()
        self.pix = {}
        self.matches = []
        self.score_page = 0
        self.score_loading = False
        self.score_error = None
        self.player_at_open = None
        self.update_available = None   # newer version found on GitHub
        self.updater = None

        for name in LABELS:
            self[name] = Label("")
        for name in PIXMAPS:
            self[name] = Pixmap()
        self["score_list"] = MCList((26, 22), 72)
        self["upnext"] = MCList((24, 22), 192)
        self["progress"] = ProgressBar()

        self["actions"] = ActionMap(
            ["OkCancelActions", "DirectionActions", "ColorActions", "MenuActions",
             "EPGSelectActions", "InfobarSeekActions"],
            {
                "ok": self.togglePause,
                "cancel": self.close,
                "up": self.prevVideo,
                "down": self.nextVideo,
                "nextBouquet": self.prevVideo,
                "prevBouquet": self.nextVideo,
                "left": self.prevTab,
                "right": self.nextTab,
                "red": self.keyRefresh,
                "green": self.nextLeague,
                "yellow": self.openLibrary,
                "blue": self.openChannels,
                "menu": self.openMenu,
                "info": self.toggleClean,
                "playpauseService": self.togglePause,
                "seekFwd": lambda: self.seekBy(10),
                "seekBack": lambda: self.seekBy(-10),
            }, -1)

        self.tracker = ServiceEventTracker(screen=self, eventmap={
            iPlayableService.evEOF: self.onEOF,
            iPlayableService.evVideoSizeChanged: self.onVideoInfo,
            iPlayableService.evUpdatedInfo: self.onVideoInfo,
            iPlayableService.evUser + 10: self.onAudioError,
            iPlayableService.evUser + 11: self.onVideoCodecError,
            iPlayableService.evUser + 12: self.onPlayerError,
        })

        self.playTimer = Timer(self.playCurrent)
        self.tickTimer = Timer(self.onTick)
        self.scoreTimer = Timer(self.loadScores)
        self.pageTimer = Timer(self.nextScorePage)
        self.refreshTimer = Timer(self.autoRefresh)
        self.msgTimer = Timer(self.hideMessage)
        self.imageTimer = Timer(self.applyImages)
        self.skipTimer = Timer(self.autoSkip)
        self.timers = (self.playTimer, self.tickTimer, self.scoreTimer, self.pageTimer,
                       self.refreshTimer, self.msgTimer, self.imageTimer, self.skipTimer)

        self.lastservice = self._currentService()
        self.onLayoutFinish.append(self.start)
        self.onClose.append(self.cleanup)

    # ------------------------------------------------------------------ setup
    def _currentService(self):
        nav = self.session.nav
        for name in ("getCurrentlyPlayingServiceOrGroup", "getCurrentlyPlayingServiceReference"):
            fn = getattr(nav, name, None)
            if fn:
                try:
                    return fn()
                except Exception:
                    pass
        return None

    def start(self):
        for name in ("score_list", "upnext"):
            inst = self[name].instance
            if inst is None:
                continue
            for call in (lambda: inst.setSelectionEnable(False), lambda: inst.allowNativeKeys(False)):
                try:
                    call()
                except Exception:
                    pass
        for name in ("pause_icon", "pill", "center_msg", "badge", "cover"):
            self[name].hide()
        self["score_tag"].setText("SCORES")
        self["next_title"].setText("Up next")
        self["key_red"].setText("Refresh / newest")
        self["key_green"].setText("Next league")
        self["key_yellow"].setText("Video list")
        self["key_blue"].setText("Channels")
        self["key_hint"].setText("OK pause    INFO clean    MENU setup")
        self["nav_up_txt"].setText("Previous video (newer)")
        self["nav_down_txt"].setText("Next video (older)")
        self["nav_side_txt"].setText("Switch channel tab")
        self.setPixmap("avatar", ICONS + "/avatar.png")
        self.applyVisibility()
        self.session.nav.stopService()
        try:
            self.proxy = StreamProxy(self.sources, audio_mode=lambda: self.cfg.audio.value)
        except Exception as e:
            log("stream relay unavailable, the player gets direct links:", e)
        self.buildTabs()
        self.feed.load_cache(self.store.usernames())
        self.rebuild(reset=True)
        if self.clips:
            self.schedulePlay(200)
        elif self.store.usernames():
            self.showMessage("Loading the latest videos...", 0)
        self.startRefresh()
        self.resolvePendingLinks()
        self.autoUpdateCheck()
        self.tickTimer.start(500, False)
        self.loadScores()

    def cleanup(self):
        self.alive = False
        for t in self.timers:
            t.stop()
        self.images.stop()
        self.resolver.stop()
        self.store.last_visit = int(time.time())
        self.store.extra["net"] = self.sources.state()
        self.store.save()
        try:
            self.cfg.league_index.save()
            configfile.save()
        except Exception:
            pass
        self.session.nav.stopService()
        if self.proxy:
            self.proxy.stop()
        if self.lastservice:
            self.session.nav.playService(self.lastservice)

    # ------------------------------------------------------------------ tabs & feed
    def buildTabs(self):
        key = self.tabs[self.tab][0] if self.tabs else ALL
        self.tabs = [(ALL, "For You")] + [(c["username"], c["name"])
                                         for c in self.store.channels if c["enabled"]]
        keys = [t[0] for t in self.tabs]
        self.tab = keys.index(key) if key in keys else 0
        self.updateTabs()

    def updateTabs(self):
        n = len(self.tabs)
        self["tab_cur"].setText(self.tabs[self.tab][1])
        if n > 1:
            prev = self.tabs[(self.tab - 1) % n][1]
            nxt = self.tabs[(self.tab + 1) % n][1]
            self["tab_side"].setText("<  %s        %s  >" % (prev[:18], nxt[:18]))
        else:
            self["tab_side"].setText("BLUE: add TikTok channels")

    def tabUsers(self):
        key = self.tabs[self.tab][0] if self.tabs else ALL
        return self.store.usernames() if key == ALL else [key]

    def current(self):
        if 0 <= self.index < len(self.clips):
            return self.clips[self.index]
        return None

    def isNew(self, video):
        return video.get("created", 0) > (self.prev_visit or time.time() - 86400)

    def rebuild(self, reset=False):
        cur = self.current()
        key = self.tabs[self.tab][0] if self.tabs else ALL
        self.clips = self.feed.merged(self.tabUsers(), int(self.cfg.max_age.value),
                                      preferred=self.store.preferred() if key == ALL else ())
        replay = False
        if reset or cur is None:
            self.index = 0
        else:
            ids = [v["id"] for v in self.clips]
            if cur["id"] in ids:
                self.index = ids.index(cur["id"])
            else:
                self.index = min(self.index, max(0, len(self.clips) - 1))
                replay = bool(self.clips)
        self.updateAll()
        if replay:
            self.schedulePlay()

    def updateAll(self):
        self.updatePost()
        self.updatePosition()
        self.updatePill()
        self.applyImages()

    # ------------------------------------------------------------------ overlay
    def setText(self, name, text):
        rtl = is_rtl(text)
        if self.cfg.arabic_fix.value:
            text = fix_bidi(text)
        self[name].setText(text)
        set_rtl(self[name], rtl)

    def setPixmap(self, name, path):
        inst = self[name].instance
        if inst is None or not path or self.pix.get(name) == path:
            return
        try:
            ptr = LoadPixmap(path, cached=False)
        except Exception:
            ptr = None
        if ptr:
            inst.setPixmap(ptr)
            self.pix[name] = path

    def updatePost(self):
        v = self.current()
        if v is None:
            for name in ("author", "meta", "caption", "tags", "music", "likes", "comments",
                         "shares", "views"):
                self[name].setText("")
            self["badge"].hide()
            return
        ch = self.store.get(v["user"]) or {}
        self["author"].setText("@" + v["user"])
        meta = [v.get("author") or ch.get("name") or "", time_ago(v.get("created")),
                fmt_duration(v.get("duration"))]
        if v.get("pinned"):
            meta.append("pinned")
        self.setText("meta", "  ·  ".join(m for m in meta if m))
        self.setText("caption", v.get("title") or "Match video")
        tags = " ".join(v.get("tags") or [])[:160] if self.cfg.show_hashtags.value else ""
        self.setText("tags", tags)
        self.flowTags()
        self.setText("music", v.get("music") or "original sound")
        self["likes"].setText(fmt_count(v.get("likes")))
        self["comments"].setText(fmt_count(v.get("comments")))
        self["shares"].setText(fmt_count(v.get("shares")))
        self["views"].setText(fmt_count(v.get("plays")))
        self.updateBadge()

    def flowTags(self):
        """Put the hashtags right under the caption (TikTok style) when the box allows."""
        try:
            height = self["caption"].instance.calculateSize().height()
            top = s(CAPTION_TOP) + min(max(height, 0), s(CAPTION_HEIGHT)) + s(8)
            self["tags"].instance.move(ePoint(s(48), top))
        except Exception:
            pass

    def updateBadge(self):
        v = self.current()
        if v and self.isNew(v) and not self.panelsHidden():
            self["badge"].setText("NEW")
            self["badge"].show()
        else:
            self["badge"].hide()

    def updatePosition(self):
        if not self.clips:
            self["position"].setText("")
            return
        new = sum(1 for v in self.clips if self.isNew(v))
        text = "%d / %d" % (self.index + 1, len(self.clips))
        if new:
            text += "   %d new" % new
        self["position"].setText(text)

    def updatePill(self):
        newer = sum(1 for v in self.clips[:self.index] if v.get("created", 0) > self.seen_top)
        if newer and self.seen_top and not self.clean:
            self["pill"].setText("%d new  - press UP" % newer if newer > 1 else "1 new  - press UP")
            self["pill"].show()
        else:
            self["pill"].hide()

    def upnextEntry(self, v):
        entry = [v["id"]]
        thumb = self.images.get(v.get("cover"), s(96), s(170), "fill") if HAVE_PIL else None
        pix = P(0, 11, 96, 170, thumb)
        if pix:
            entry.append(pix)
        x = 112 if pix else 0
        w = 428 - x
        title = v.get("title") or " ".join(v.get("tags") or []) or "Match video"
        if self.cfg.arabic_fix.value:
            title = fix_bidi(title)
        info = "@%s  ·  %s" % (v["user"], time_ago(v.get("created"), short=True))
        entry.append(T(x, 10, w, 32, 1, LEFT, info, 0x25F4EE if self.isNew(v) else 0xA8A8A8))
        entry.append(T(x, 46, w, 136, 0, WRAP_RIGHT if is_rtl(title) else WRAP_LEFT, title))
        return entry

    def applyImages(self):
        if not self.alive:
            return
        v = self.current()
        avatar = v and self.images.get(v.get("avatar"), s(100), s(100), "circle")
        self.setPixmap("avatar", avatar or ICONS + "/avatar.png")
        if self.waiting and v:
            cover = self.images.get(v.get("cover"), s(608), s(1080), "cover")
            if cover:
                self.setPixmap("cover", cover)
                self["cover"].show()
                if self["center_msg"].getText().startswith("Loading"):
                    self.hideMessage()
        self["upnext"].setList([self.upnextEntry(n) for n in self.clips[self.index + 1:self.index + 1 + UPNEXT_ROWS]])
        self["next_title"].setText("Up next" if self.index + 1 < len(self.clips) else "Up next: end of feed")
        for n in self.clips[self.index + 1:self.index + 3]:        # warm the cache for swipes
            self.images.get(n.get("cover"), s(608), s(1080), "cover")
            self.images.get(n.get("avatar"), s(100), s(100), "circle")

    def _imageReadyThread(self, path):
        in_gui(self._imageReady, path)

    def _imageReady(self, path):
        if self.alive:
            self.imageTimer.start(150, True)

    def panelsHidden(self):
        return self.clean or (self.landscape and self.cfg.landscape_clean.value)

    def applyVisibility(self):
        hidden = self.panelsHidden()
        scores = not hidden and self.cfg.show_scores.value
        for name in SCORE_WIDGETS:
            self.setVisible(name, scores)
        for name in POST_WIDGETS + ACTION_WIDGETS + RIGHT_WIDGETS:
            self.setVisible(name, not hidden)
        self.updateBadge()
        self.updatePill()

    def setVisible(self, name, flag):
        if flag:
            self[name].show()
        else:
            self[name].hide()

    def toggleClean(self):
        self.clean = not self.clean
        self.applyVisibility()

    def showMessage(self, text, timeout=3000):
        self["center_msg"].setText(text)
        self["center_msg"].show()
        if timeout:
            self.msgTimer.start(timeout, True)
        else:
            self.msgTimer.stop()

    def hideMessage(self):
        self["center_msg"].hide()
        self["center_msg"].setText("")

    def setStatus(self, text):
        self["status"].setText(text)

    # ------------------------------------------------------------------ playback
    def schedulePlay(self, delay=350):
        """Stop the old clip now, start the new one after a short debounce."""
        self.skipTimer.stop()
        self.session.nav.stopService()
        self.playing = None
        self.pending_links = None
        self.waiting = True
        self.paused = False
        self.finished = False
        self.landscape = False
        self["pause_icon"].hide()
        self["progress"].setValue(0)
        self.applyVisibility()
        self["cover"].hide()
        self.applyImages()
        if self.current() and not self["cover"].visible:
            self.showMessage("Loading video...", 0)
        self.playTimer.start(delay, True)

    def neighbors(self):
        """The current clip and the next two: the ones worth having links for."""
        return [self.clips[i] for i in range(self.index, self.index + 3) if 0 <= i < len(self.clips)]

    def playCurrent(self):
        v = self.current()
        if v is None or not self.alive:
            return
        self.resolver.want(self.neighbors())
        if self.sources.needs_links(v):
            # Links come from the clip's TikTok page first; the player starts when
            # they are ready, so it never waits on TikTok and times out.
            self.pending_links = v["id"]
            self.links_started = time.time()
            return
        self._startPlayer(v)

    def _linksReadyThread(self, video, ok, error):
        in_gui(self._linksReady, video, ok, error)

    def _linksReady(self, video, ok, error):
        if not self.alive or self.pending_links != video["id"]:
            return                      # links fetched ahead of time for a later clip
        v = self.current()
        if v is None or v["id"] != video["id"]:
            return
        self.pending_links = None
        if ok:
            self._startPlayer(v)
        else:
            self.linkFailed(error)

    def linkFailed(self, error):
        self.waiting = False
        self.setStatus("Video link failed: " + (error or "?")[:90])
        if self.cfg.on_end.value == "next" and self.index + 1 < len(self.clips):
            self.showMessage("Can't get this clip - skipping", 0)
            self.skipTimer.start(2500, True)
        else:
            self.showMessage("Can't get this clip:\n%s" % short_problem(error, 110), 0)

    def wantConvert(self):
        """Use ffmpeg's MP2 conversion for this clip? (MENU -> Audio)"""
        if self.cfg.audio.value != "convert" or not self.proxy or self.proxy.convert_failed:
            return False
        if not transcode.ffmpeg_path():
            if not self.ffmpeg_hint_shown:
                self.ffmpeg_hint_shown = True
                self.setStatus("Audio conversion needs ffmpeg: MENU, then BLUE installs it")
            return False
        return True

    def _startPlayer(self, v):
        hd = self.cfg.hd.value
        self.converting = self.wantConvert()
        if self.proxy:
            url = self.proxy.url(v, hd, self.converting)
        else:
            url = self.sources.direct_url(v, hd)
        if not url:
            self.playing = v["id"]
            self.onPlayError("no video link")
            return
        ref = eServiceReference(int(self.cfg.player.value), 0, url)
        ref.setName((v.get("title") or "@" + v["user"])[:80])
        self.playing = v["id"]
        self.started = time.time()
        self.waiting = True
        self.session.nav.playService(ref)
        self.seen_top = max(self.seen_top, v.get("created", 0))
        self.updatePill()

    def onTick(self):
        if not self.alive:
            return
        if self.pending_links and time.time() - self.links_started > LINK_TIMEOUT:
            self.pending_links = None
            self.linkFailed("TikTok didn't send the clip's links within %d s" % LINK_TIMEOUT)
            return
        if not self.playing:
            return
        service = self.session.nav.getCurrentService()
        seek = service and service.seek()
        if seek is None:
            if self.waiting and time.time() - self.started > START_TIMEOUT:
                self.onPlayError()
            return
        try:
            length = seek.getLength()
            pos = seek.getPlayPosition()
        except Exception:
            return
        length = length[1] if length and not length[0] else 0
        pos = pos[1] if pos and not pos[0] else 0
        v = self.current()
        if length <= 0 and v and v.get("duration"):
            length = int(v["duration"]) * PTS
        if length > 0:
            self["progress"].setValue(max(0, min(100, int(pos * 100 / length))))
        if self.waiting:
            if pos > PTS * 3 // 10:
                self.waiting = False
                self["cover"].hide()
                if self["center_msg"].getText().startswith("Loading"):
                    self.hideMessage()
                playlog("player %s: playing after %.1fs (%s)" % (
                    self.playing, time.time() - self.started,
                    describe_stream(self.sources.served.get(self.playing))))
            elif time.time() - self.started > START_TIMEOUT:
                self.onPlayError("no picture within %d s" % START_TIMEOUT)

    def onVideoInfo(self):
        service = self.session.nav.getCurrentService()
        info = service and service.info()
        if not info:
            return
        w = info.getInfo(iServiceInformation.sVideoWidth)
        h = info.getInfo(iServiceInformation.sVideoHeight)
        if w > 0 and h > 0 and (w > h) != self.landscape:
            self.landscape = w > h
            self.applyVisibility()

    def onEOF(self):
        if not self.playing or time.time() - self.started < 1.5:
            return
        mode = self.cfg.on_end.value
        if mode == "loop":
            self.schedulePlay(0)
        elif mode == "next" and self.index + 1 < len(self.clips):
            self.index += 1
            self.updateAll()
            self.schedulePlay(50)
        else:
            self.finished = True
            self["pause_icon"].show()
            if self.index + 1 >= len(self.clips):
                self.showMessage("You're all caught up. OK replays, RED refreshes", 0)

    def onAudioError(self):
        codec = self.serviceString(iServiceInformation.sTagAudioCodec)
        playlog("player %s: the receiver can't decode the audio (%s)" % (self.playing, codec or "?"))
        self.setStatus("The receiver can't decode this audio (%s): try MENU > Audio" % (codec or "?"))

    def serviceString(self, what):
        service = self.session.nav.getCurrentService()
        info = service and service.info()
        try:
            return (info.getInfoString(what) or "").strip() if info else ""
        except Exception:
            return ""

    def onVideoCodecError(self):
        codec = self.serviceString(iServiceInformation.sTagVideoCodec)
        self.onPlayError("this receiver can't decode %s video" % (codec or "this"), codec_error=True)

    def onPlayerError(self):
        self.onPlayError(self.serviceString(iServiceInformation.sUser + 12) or "player error")

    def onPlayError(self, reason=None, codec_error=False):
        if not self.playing:
            return
        vid = self.playing
        self.playing = None
        self.waiting = False
        self["cover"].hide()
        if self.converting and self.proxy and self.proxy.convert_failed:
            # ffmpeg didn't work on this box: play with the header fix instead
            playlog("player %s: %s - playing without conversion" % (vid, self.proxy.convert_failed))
            self.setStatus("Audio conversion failed (%s); playing without it" % self.proxy.convert_failed[:60])
            self.schedulePlay(100)
            return
        served = self.sources.served.get(vid)
        if codec_error and served and served[1] != "h264" and not self.sources.h264_wanted():
            # The box can't decode H.265: use H.264 links from now on and retry this clip.
            self.sources.h264_only = True
            playlog("player %s: %s (%s) - using H.264 links only" % (vid, reason, describe_stream(served)))
            self.setStatus("This receiver can't play H.265, using H.264 links only")
            v = self.current()
            if v and v["id"] == vid and any(s[1] == "h264" for s in v.get("streams") or []):
                self.schedulePlay(100)
                return
        relay = self.proxy.error(vid) if self.proxy else None
        reason = relay or reason or "player error"
        playlog("player %s: can't play: %s%s" % (vid, reason, (" (%s)" % describe_stream(served)) if served else ""))
        self.setStatus("Can't play: " + reason[:90])
        if self.cfg.on_end.value == "next" and self.index + 1 < len(self.clips):
            self.showMessage("Can't play this clip - skipping", 0)
            self.skipTimer.start(2500, True)
        else:
            self.showMessage("Can't play this clip:\n%s" % short_problem(reason, 110), 0)

    def autoSkip(self):
        if self.alive and self.index + 1 < len(self.clips):
            self.index += 1
            self.updateAll()
            self.schedulePlay(50)

    def togglePause(self):
        if self.finished:
            self.schedulePlay(0)
            return
        service = self.session.nav.getCurrentService()
        pauseable = service and service.pause()
        if not pauseable:
            return
        if self.paused:
            pauseable.unpause()
            self.paused = False
            self["pause_icon"].hide()
        else:
            pauseable.pause()
            self.paused = True
            self["pause_icon"].show()

    def seekBy(self, seconds):
        service = self.session.nav.getCurrentService()
        seek = service and service.seek()
        if seek is None:
            return
        try:
            if not seek.isCurrentlySeekable():
                return
        except Exception:
            pass
        seek.seekRelative(1 if seconds > 0 else -1, abs(seconds) * PTS)

    # ------------------------------------------------------------------ navigation
    def move(self, delta):
        if not self.clips:
            return
        new = self.index + delta
        if new >= len(self.clips):
            self.showMessage("That's everything for now. RED checks for new videos", 3000)
            return
        self.jump_top = False
        self.index = new
        self.updateAll()
        self.schedulePlay()

    def nextVideo(self):
        self.move(1)

    def prevVideo(self):
        if self.index == 0:         # like pulling down at the top of TikTok
            self.showMessage("Checking for new videos...", 2500)
            self.startRefresh(max_age=60, jump_top=True)
            return
        self.move(-1)

    def switchTab(self, delta):
        if len(self.tabs) < 2:
            return
        self.jump_top = False
        self.tab = (self.tab + delta) % len(self.tabs)
        self.updateTabs()
        self.rebuild(reset=True)
        if self.clips:
            self.schedulePlay(500)
        else:
            self.playTimer.stop()
            self.session.nav.stopService()
            self.playing = None
            self.waiting = False
            self["cover"].hide()
            self["progress"].setValue(0)
            user = self.tabs[self.tab][0]
            err = self.feed.errors.get(user)
            self.showMessage(("@%s: %s" % (user, err)) if err else "No recent videos here", 0)

    def nextTab(self):
        self.switchTab(1)

    def prevTab(self):
        self.switchTab(-1)

    # ------------------------------------------------------------------ refresh
    def keyRefresh(self):
        self.showMessage("Refreshing...", 2000)
        self.startRefresh(force=True, jump_top=True)
        self.loadScores()

    def autoRefresh(self):
        self.startRefresh()

    def startRefresh(self, force=False, max_age=None, jump_top=False):
        if jump_top:
            self.jump_top = True
        if self.refreshing:
            return
        users = self.store.usernames()
        if not users:
            self.setStatus("No channels yet. Press BLUE to add one")
            self.showMessage("No TikTok channels. Press BLUE to add some", 0)
            return
        if force:
            ttl = 0
        elif max_age is not None:
            ttl = max_age
        else:
            ttl = int(self.cfg.cache_minutes.value) * 60
        todo = self.feed.stale(users, ttl)
        if not todo:
            self.finishRefresh()
            return
        visible, preferred = self.tabUsers(), self.store.preferred()
        todo.sort(key=lambda u: (u not in visible, u not in preferred))  # visible tab, preferred first
        channels = [dict(self.store.get(u)) for u in todo if self.store.get(u)]
        self.refreshing = True
        self.used_sources = set()
        self.setStatus("Updating %d channel%s..." % (len(todo), "s" if len(todo) > 1 else ""))
        worker = threading.Thread(target=self._refreshWorker,
                                  args=(channels, int(self.cfg.per_channel.value)))
        worker.daemon = True
        worker.start()

    def resolvePendingLinks(self):
        """Share links in the preferred list: find their channel, add it as preferred."""
        links = list(self.store.extra.get("pending_links") or [])
        if not links:
            return

        def work():
            for url in links:
                try:
                    user, err = self.sources.link_owner(url), None
                except Exception as e:
                    user, err = None, str(e)
                in_gui(self._linkResolved, url, user, err)
        t = threading.Thread(target=work)
        t.daemon = True
        t.start()

    def _linkResolved(self, url, user, err):
        if not self.alive:
            return
        if not user:
            playlog("preferred link %s: %s (tried again next time)" % (url, err))
            return
        self.store.drop_pending_link(url)
        c = self.store.get(user)
        if c:
            if not c.get("preferred"):
                self.store.toggle_preferred(user)
            if not c["enabled"]:
                self.store.toggle(user)
        else:
            self.store.add(user, preferred=True)
        log("preferred link %s -> @%s" % (url, user))
        self.buildTabs()
        self.startRefresh()

    def _refreshWorker(self, channels, count):
        for i, channel in enumerate(channels):
            if not self.alive:
                return
            videos, err, meta = self.feed.fetch(channel, count, self.sources)
            in_gui(self._channelDone, channel["username"], videos, err, meta, i + 1, len(channels))
        in_gui(self._refreshDone)

    def _channelDone(self, user, videos, err, meta, i, total):
        if not self.alive:
            return
        self.feed.apply(user, videos, err, meta)
        if meta.get("sec_uid"):
            self.store.set_sec_uid(user, meta["sec_uid"])
        c = self.store.get(user)
        author = next((v.get("author") for v in videos or [] if v.get("author")), "")
        if c and author and c["name"] == user:
            # added without a check (preferred list, share link): use the channel's real name
            self.store.rename(user, author)
            self.buildTabs()
        if err:
            self.setStatus("@%s: %s  (%d/%d)" % (user, err[:60], i, total))
        else:
            self.used_sources.add(meta.get("source"))
            self.setStatus("@%s: %d videos via %s  (%d/%d)" % (
                user, len(videos), SOURCE_NAMES.get(meta.get("source"), "?"), i, total))
        if user in self.tabUsers():
            was_empty = not self.clips
            self.rebuild()
            if was_empty and self.clips:
                self.hideMessage()
                self.schedulePlay(100)

    def _refreshDone(self):
        if not self.alive:
            return
        self.refreshing = False
        self.finishRefresh()

    def finishRefresh(self):
        if self.jump_top and self.clips and self.index != 0:
            self.index = 0
            self.updateAll()
            self.schedulePlay(100)
        self.jump_top = False
        users = self.store.usernames()
        failed = [u for u in users if u in self.feed.errors]
        self.store.extra["net"] = self.sources.state()
        text = "Updated %s   %d videos" % (time.strftime("%H:%M"), len(self.clips))
        used = sorted(SOURCE_NAMES.get(name, name) for name in self.used_sources if name)
        if used:
            text += "\nvia " + " + ".join(used)
        if failed:
            text += "   %d channel%s failed" % (len(failed), "s" if len(failed) > 1 else "")
        self.setStatus(text)
        if not self.clips and users:
            if failed and len(failed) == len(self.tabUsers()):
                self.showMessage("Couldn't load videos\n%s\nMENU, then YELLOW: connection test"
                                 % short_problem(self.feed.errors[failed[0]]), 0)
            else:
                self.showMessage("No videos in this time range. Change it in MENU", 0)
        self.refreshTimer.start(int(self.cfg.cache_minutes.value) * 60000, True)

    # ------------------------------------------------------------------ scores
    def league(self):
        if not self.store.leagues:
            return None
        return self.store.leagues[self.cfg.league_index.value % len(self.store.leagues)]

    def loadScores(self):
        lg = self.league()
        if not self.alive or not self.cfg.show_scores.value or lg is None or self.score_loading:
            return
        self.score_loading = True
        self["score_title"].setText(lg["name"])
        worker = threading.Thread(target=self._scoresWorker, args=(lg["code"],))
        worker.daemon = True
        worker.start()

    def _scoresWorker(self, code):
        try:
            matches = api_scores.scoreboard(code)[1]
            err = None
        except Exception as e:
            matches, err = [], str(e) or "error"
        in_gui(self._scoresDone, code, matches, err)

    def _scoresDone(self, code, matches, err):
        self.score_loading = False
        if not self.alive:
            return
        lg = self.league()
        if lg is None or lg["code"] != code:      # league changed while loading
            self.loadScores()
            return
        self.matches = matches
        self.score_error = err
        self.score_page = 0
        self.renderScores()
        live = any(m["state"] == "in" for m in matches)
        self.scoreTimer.start((60 if live else 300) * 1000, True)
        if len(matches) > SCORE_ROWS:
            self.pageTimer.start(8000, True)

    def scoreEntry(self, m):
        pre = m["state"] == "pre"
        live = m["state"] == "in"
        status = api_scores.status_text(m)
        entry = [m["id"],
                 T(0, 4, 184, 36, 0, RIGHT, m["home"]),
                 T(190, 4, 72, 36, 0, CENTER, "vs" if pre else "%s - %s" % (m["hs"], m["as"]),
                   0x8A8A8A if pre else 0xFFFFFF),
                 T(268, 4, 184, 36, 0, LEFT, m["away"]),
                 T(456, 4, 120, 36, 1, RIGHT, status,
                   0xFE2C55 if live else (0xFFFFFF if pre else 0x8A8A8A))]
        home, away = api_scores.scorers_text(m, 15, 26)
        if home:
            entry.append(T(0, 40, 184, 28, 1, RIGHT, home, 0x9A9A9A))
        if away:
            entry.append(T(268, 40, 308, 28, 1, LEFT, away, 0x9A9A9A))
        return entry

    def renderScores(self):
        pages = max(1, (len(self.matches) + SCORE_ROWS - 1) // SCORE_ROWS)
        self.score_page %= pages
        chunk = self.matches[self.score_page * SCORE_ROWS:(self.score_page + 1) * SCORE_ROWS]
        if self.score_error:
            rows = [[None, T(0, 0, 576, 72, 1, WRAP_LEFT, "Scores unavailable: " + self.score_error[:60], 0x9A9A9A)]]
        elif not chunk:
            rows = [[None, T(0, 0, 576, 72, 1, LEFT, "No matches in this round", 0x9A9A9A)]]
        else:
            rows = [self.scoreEntry(m) for m in chunk]
        self["score_list"].setList(rows)
        hint = "GREEN next league"
        if pages > 1:
            hint += "   page %d/%d" % (self.score_page + 1, pages)
        self["score_page"].setText(hint)

    def nextScorePage(self):
        if not self.alive or len(self.matches) <= SCORE_ROWS:
            return
        self.score_page += 1
        self.renderScores()
        self.pageTimer.start(8000, True)

    def nextLeague(self):
        if not self.cfg.show_scores.value:
            self.showMessage("Scores are switched off. Turn them on in MENU", 2500)
            return
        if not self.store.leagues:
            return
        self.cfg.league_index.value = (self.cfg.league_index.value + 1) % len(self.store.leagues)
        self.scoreTimer.stop()
        self.pageTimer.stop()
        self.matches = []
        self.score_error = None
        self["score_title"].setText(self.league()["name"])
        self["score_list"].setList([[None, T(0, 0, 576, 72, 1, LEFT, "Loading...", 0x9A9A9A)]])
        self.loadScores()

    # ------------------------------------------------------------------ dialogs
    def openLibrary(self):
        if not self.clips:
            return
        from .ui_manage import LibraryScreen
        self.session.openWithCallback(self.libraryClosed, LibraryScreen, self.clips, self.index,
                                      self.tabs[self.tab][1], self.prev_visit)

    def libraryClosed(self, index=None):
        if not self.alive or index is None or not 0 <= index < len(self.clips):
            return
        if index != self.index:
            self.jump_top = False
            self.index = index
            self.updateAll()
            self.schedulePlay(50)

    def openChannels(self):
        from .ui_manage import ChannelsScreen
        self.session.openWithCallback(self.channelsClosed, ChannelsScreen, self.store, self.feed,
                                      self.sources)

    def channelsClosed(self, changed=False):
        if not self.alive or not changed:
            return
        self.buildTabs()
        self.rebuild()
        if self.clips and self.playing is None and not self.waiting:
            self.schedulePlay()
        elif not self.clips:
            self.session.nav.stopService()
            self.playing = None
        self.startRefresh()

    # ------------------------------------------------------------------ menu & updates
    def openMenu(self):
        from . import VERSION
        from .ui_update import PluginMenu
        self.session.openWithCallback(self.menuChosen, PluginMenu, VERSION, self.update_available)

    def menuChosen(self, key):
        if not self.alive or not key:
            return
        if key == "settings":
            self.openSettings()
        elif key == "update":
            self.startUpdate(self.update_available)
        elif key == "test":
            from .ui_manage import DiagnoseScreen
            v = self.current()
            league = self.league()
            self.session.open(DiagnoseScreen, self.sources, v["user"] if v else "kayfa1x_2",
                              league["code"] if league else "eng.1")
        elif key == "about":
            from . import VERSION
            from .ui_update import about_text
            self.session.open(MessageBox, about_text(VERSION), MessageBox.TYPE_INFO)

    def startUpdate(self, latest=None):
        from . import VERSION
        from .ui_update import UpdateFlow
        if self.updater is None:
            self.updater = UpdateFlow(self.session, VERSION, say=self._updateSay)
        notes = self.store.extra.get("update_notes", "") if latest else ""
        self.updater.start(latest, notes)

    def _updateSay(self, text):
        if self.alive:
            self.setStatus(text)

    def autoUpdateCheck(self):
        """Once a day, in the background: is there a newer version on GitHub?"""
        from . import VERSION, updater
        if not self.cfg.update_check.value:
            return
        last = self.store.extra.get("update_checked") or 0
        known = self.store.extra.get("update_latest")
        if known and updater.is_newer(known, VERSION):
            self._updateFound(known)
        if time.time() - last < updater.CHECK_EVERY:
            return

        def work():
            try:
                latest, notes = updater.check()
            except Exception as e:
                log("update check failed:", e)
                return
            in_gui(self._updateChecked, latest, notes)
        t = threading.Thread(target=work)
        t.daemon = True
        t.start()

    def _updateChecked(self, latest, notes):
        from . import VERSION, updater
        self.store.extra.update({"update_checked": int(time.time()), "update_latest": latest,
                                 "update_notes": notes})
        self.store.save()
        if self.alive and updater.is_newer(latest, VERSION):
            self._updateFound(latest)

    def _updateFound(self, latest):
        if not self.alive:
            return
        self.update_available = latest
        self.setStatus("Update %s available: MENU > Update plugin" % latest)
        self["key_hint"].setText("OK pause   MENU: update %s available" % latest)
        self.showMessage("SimplyScores %s is available\nMENU > Update plugin" % latest, 6000)

    def openSettings(self):
        from .ui_manage import SettingsScreen
        self.player_at_open = (self.cfg.player.value, self.cfg.hd.value, self.cfg.source.value,
                               self.cfg.codec.value, self.cfg.audio.value)
        v = self.current()
        users = self.store.usernames()
        test_user = v["user"] if v else (users[0] if users else "kayfa1x_2")
        league = self.league()
        self.session.openWithCallback(self.settingsClosed, SettingsScreen, self.sources, test_user,
                                      league["code"] if league else "eng.1")

    def settingsClosed(self, saved=False):
        if not self.alive or not saved:
            return
        self.applyVisibility()
        if self.cfg.source.value != self.player_at_open[2]:
            self.sources.skip_until.clear()
            self.showMessage("Video source changed, reloading...", 2500)
            self.startRefresh(force=True, jump_top=True)
        self.rebuild()
        if self.cfg.show_scores.value:
            if not self.matches:
                self.loadScores()
        else:
            self.scoreTimer.stop()
            self.pageTimer.stop()
        if self.cfg.codec.value != self.player_at_open[3]:
            self.sources.h264_only = False          # the user decides again
        if ((self.cfg.player.value, self.cfg.hd.value) != self.player_at_open[:2]
                or self.cfg.codec.value != self.player_at_open[3]
                or self.cfg.audio.value != self.player_at_open[4]) and self.clips:
            self.schedulePlay(100)
        self.refreshTimer.start(int(self.cfg.cache_minutes.value) * 60000, True)
