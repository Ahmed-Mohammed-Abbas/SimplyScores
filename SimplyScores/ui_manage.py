# -*- coding: utf-8 -*-
"""Channel manager, video list (jump) and settings screens."""
import re
import threading
import time

from twisted.internet import reactor

from Components.ActionMap import ActionMap
from Components.ConfigList import ConfigListScreen
from Components.Label import Label
from Components.ScrollLabel import ScrollLabel
from Components.config import config, configfile, getConfigListEntry
from Screens.MessageBox import MessageBox
from Screens.Screen import Screen
from Screens.VirtualKeyBoard import VirtualKeyBoard

from . import diagnose, transcode
from .core import (SUGGESTED_CHANNELS, fix_bidi, fmt_count, fmt_duration, is_rtl, log,
                   normalize_username, parse_channel_input, playlog, time_ago)
from .webpage import ChannelPage
from .gui import (ADD_SKIN, CENTER, CHANNELS_SKIN, DIAG_SKIN, LEFT, LIBRARY_SKIN, MCList, RIGHT,
                  SETTINGS_SKIN, T, WRAP_LEFT, WRAP_RIGHT)

SOURCE_NAMES = {"tikwm": "TikWM", "tiktok": "TikTok"}


def keyboard_text(value):
    """Text from a keyboard screen. Some images and keyboard plugins send back a
    list, bytes or another object instead of a plain string."""
    if value is None:
        return None
    if isinstance(value, bytes):
        return value.decode("utf-8", "replace")
    if isinstance(value, (list, tuple)):
        parts = [keyboard_text(v) for v in value]
        return " ".join(p for p in parts if p)
    return value if isinstance(value, str) else str(value)


def short_link(url):
    """'vt.tiktok.com/ZSabc123/' for messages."""
    text = re.sub(r"^https?://", "", url or "")
    return text if len(text) <= 48 else text[:45] + "..."


def _short_error(err):
    """The most telling part of a 'TikWM: ... | TikTok: ...' error."""
    parts = [p.split(": ", 1)[-1] for p in (err or "error").split(" | ")]
    return parts[-1][:60]


class AddChannelScreen(Screen):
    """GREEN in the channel manager: type a name or link, or pick a suggested channel."""

    def __init__(self, session, store, page_url=None):
        Screen.__init__(self, session)
        self.skin = ADD_SKIN
        self.skinName = "SimplyScoresAddChannel"
        self.store = store
        self["title"] = Label("Add TikTok channels")
        self["subtitle"] = Label("Match summaries and highlights like Kayfa1x." +
                                 ("   Phone or PC: %s" % page_url if page_url else ""))
        self["list"] = MCList((30, 22), 76)
        self["hint"] = Label("OK add   EXIT back   Every channel is checked on TikTok before it is added")
        self["actions"] = ActionMap(["OkCancelActions"], {"ok": self.choose, "cancel": self.cancel}, -1)
        self.onLayoutFinish.append(self.fill)

    def rows(self):
        """[(choice, tag, tag font, tag colour, name, detail, dimmed)]."""
        fresh = [c for c in SUGGESTED_CHANNELS if not self.store.get(c["username"])]
        have = [c for c in SUGGESTED_CHANNELS if self.store.get(c["username"])]
        rows = [(("type", None), "TYPE", 1, 0x25F4EE, "Type a username or paste a link",
                 "Several: separate with commas.  Share links from the TikTok app work too.", False)]
        if len(fresh) > 1:
            rows.append((("users", [c["username"] for c in fresh]), "ALL", 1, 0xFE2C55,
                         "Add all %d suggested channels" % len(fresh),
                         ", ".join("@" + c["username"] for c in fresh), False))
        for c in fresh:
            rows.append((("users", [c["username"]]), "+", 0, 0x25F4EE, c["name"],
                         "@%s  -  %s" % (c["username"], c["about"]), False))
        for c in have:
            rows.append((None, "ADDED", 1, 0x6A6A6A, c["name"],
                         "@%s  -  already in your list" % c["username"], True))
        return rows

    def fill(self):
        entries = []
        for choice, tag, font, color, name, detail, dim in self.rows():
            entries.append([choice,
                            T(10, 0, 100, 76, font, CENTER, tag, color),
                            T(130, 6, 1150, 38, 0, LEFT, name, 0x8A8A8A if dim else 0xFFFFFF),
                            T(130, 44, 1150, 28, 1, LEFT, detail, 0x6A6A6A if dim else 0xB0B0B0)])
        self["list"].setList(entries)

    def choose(self):
        cur = self["list"].getCurrent()
        if cur and cur[0]:
            self.close(cur[0])

    def cancel(self):
        self.close(None)


class ChannelsScreen(Screen):
    """Add, remove, rename, reorder and switch TikTok channels on/off.

    While it is open, a web page on the receiver lets a phone or PC on the
    same network add and remove channels too (easier than typing with the remote).
    """

    def __init__(self, session, store, feed, sources):
        Screen.__init__(self, session)
        self.skin = CHANNELS_SKIN
        self.skinName = "SimplyScoresChannels"
        self.store = store
        self.feed = feed
        self.sources = sources
        self.changed = False
        self.checking = False
        self.alive = True
        self.batch = None             # channels being checked: results so far
        self.pending_add = []         # TV: unverified channels to add if the user says yes
        self.web_failed = []          # phone page: [(username, reason)] offered as "add anyway"
        self.from_web = False
        self.last_status = ""
        self.page = None

        self["title"] = Label("TikTok channels")
        self["subtitle"] = Label("OK switches a channel on/off. Enabled channels become tabs "
                                 "(LEFT/RIGHT) and feed 'For You'.")
        self["list"] = MCList((30, 22), 76)
        self["status"] = Label("")
        self["key_red"] = Label("Remove")
        self["key_green"] = Label("Add channels")
        self["key_yellow"] = Label("Rename")
        self["key_blue"] = Label("Move up")
        self["actions"] = ActionMap(["OkCancelActions", "ColorActions", "MenuActions"], {
            "ok": self.toggle,
            "menu": self.togglePreferred,
            "cancel": self.exit,
            "red": self.remove,
            "green": self.add,
            "yellow": self.rename,
            "blue": self.moveUp,
        }, -1)
        self.onLayoutFinish.append(self.start)
        self.onClose.append(self._closed)

    def start(self):
        self.fill()
        try:
            self.page = ChannelPage(self, reactor.callFromThread)
            self["subtitle"].setText("OK on/off   MENU preferred (first in For You)   Phone/PC: %s"
                                     % self.page.url)
        except Exception as e:
            log("channel web page unavailable:", e)

    def _closed(self):
        self.alive = False
        if self.page:
            self.page.stop()

    def say(self, text):
        self.last_status = text
        self["status"].setText(text.split("\n")[0])

    def tell(self, text, from_web, kind):
        if from_web:
            self.say(text.replace("\n", " "))
        else:
            self.session.open(MessageBox, text, kind, timeout=15)

    def entry(self, c):
        user = c["username"]
        on = c["enabled"]
        count, newest = self.feed.summary(user)
        if user in self.feed.errors:
            info, color = "update failed: " + self.feed.errors[user][:40], 0xFE6A6A
        elif count:
            via = SOURCE_NAMES.get(self.feed.source.get(user))
            info, color = "%d videos   newest %s%s" % (count, time_ago(newest),
                                                       ("   via " + via) if via else ""), 0x9A9A9A
        else:
            info, color = "not loaded yet", 0x9A9A9A
        top = c.get("preferred")
        return [user,
                T(16, 0 if not top else 4, 100, 76 if not top else 36, 1, LEFT, "ON" if on else "OFF",
                  0x25F4EE if on else 0x6A6A6A),
                T(16, 38, 100, 32, 1, LEFT, "TOP" if top else "", 0xFE2C55 if on else 0x6A6A6A),
                T(120, 6, 640, 38, 0, LEFT, c["name"], 0xFFFFFF if on else 0x8A8A8A),
                T(120, 44, 640, 28, 1, LEFT, "@" + user, 0xB0B0B0),
                T(780, 0, 520, 76, 1, RIGHT, info, color)]

    def fill(self, select=None):
        lst = self["list"]
        old = lst.getSelectionIndex() if lst.instance else 0
        lst.setList([self.entry(c) for c in self.store.channels])
        if select is not None:
            idx = self.store.index(select)
            if idx >= 0:
                lst.moveToIndex(idx)
        elif self.store.channels:
            lst.moveToIndex(min(old or 0, len(self.store.channels) - 1))
        enabled = len(self.store.usernames())
        self["title"].setText("TikTok channels  (%d of %d on)" % (enabled, len(self.store.channels)))

    def selected(self):
        cur = self["list"].getCurrent()
        return cur[0] if cur else None

    def toggle(self):
        user = self.selected()
        if user and self.store.toggle(user):
            self.changed = True
            self.fill(select=user)

    def togglePreferred(self):
        user = self.selected()
        if user and self.store.toggle_preferred(user):
            self.changed = True
            self.say(("@%s is preferred: its videos come first in For You" if self.store.get(user)["preferred"]
                      else "@%s is no longer preferred") % user)
            self.fill(select=user)

    def moveUp(self):
        user = self.selected()
        if user and self.store.move(user, -1):
            self.changed = True
            self.fill(select=user)

    def remove(self):
        user = self.selected()
        if user:
            self.session.openWithCallback(lambda yes: self._removeConfirmed(yes, user), MessageBox,
                                          "Remove @%s from SimplyScores?" % user, MessageBox.TYPE_YESNO)

    def _removeConfirmed(self, yes, user):
        if yes and self.store.remove(user):
            self.feed.forget(user)
            self.changed = True
            self.say("Removed @%s" % user)
            self.fill()

    def rename(self):
        user = self.selected()
        c = user and self.store.get(user)
        if c:
            self.session.openWithCallback(lambda text: self._renamed(user, text), VirtualKeyBoard,
                                          title="Display name for @%s" % user, text=c["name"])

    def _renamed(self, user, value):
        text = keyboard_text(value)
        if text and self.store.rename(user, text):
            self.changed = True
            self.fill(select=user)

    # -- the web page (its calls arrive on the GUI thread)
    def channels(self):
        return [dict(c) for c in self.store.channels]

    def suggestions(self):
        """Suggested channels that are not in the list yet."""
        return [dict(c) for c in SUGGESTED_CHANNELS if not self.store.get(c["username"])]

    def web_status(self):
        return self.last_status

    def web_add(self, text, force=False):
        if not self.alive:
            return
        if not force:
            self._entered(text, from_web=True)
            return
        user = normalize_username(text)
        self.web_failed = [f for f in self.web_failed if f[0] != user]
        if user and self.store.add(user):
            self.changed = True
            self.say("Added @%s" % user)
            self.fill(select=user)

    def web_remove(self, user):
        if self.alive and self.store.remove(user):
            self.feed.forget(user)
            self.changed = True
            self.say("Removed @%s" % user)
            self.fill()

    def web_prefer(self, user):
        if self.alive and self.store.toggle_preferred(user):
            self.changed = True
            self.fill(select=user)

    def web_toggle(self, user):
        if self.alive and self.store.toggle(user):
            self.changed = True
            self.fill(select=user)

    # -- adding: pick a suggestion, type names or paste links, then verify each on TikTok
    def add(self):
        if self.checking:
            self.say("Still checking channels, one moment...")
            return
        self.session.openWithCallback(self._addChosen, AddChannelScreen, self.store,
                                      self.page.url if self.page else None)

    def _addChosen(self, choice):
        if not choice:
            return
        kind, value = choice
        if kind == "type":
            self.session.openWithCallback(self._entered, VirtualKeyBoard,
                                          title="TikTok username or link (several: separate with commas)",
                                          text="")
        elif kind == "users" and value:
            self._addText(",".join(value), False)

    def _entered(self, value, from_web=False):
        """Answer of the keyboard, or text sent from the phone page."""
        text = keyboard_text(value)
        if text is None:
            return
        if not from_web:
            playlog("keyboard returned %r" % (value,))
        self._addText(text, from_web)

    def _addText(self, text, from_web):
        text = text.strip()
        hint = ("\n\nYou can also add channels from your phone or PC:\n%s" % self.page.url) if self.page else ""
        if not text:
            self.tell("The keyboard sent back no text." + hint, from_web, MessageBox.TYPE_INFO)
            return
        entries, rejected = parse_channel_input(text)
        if not entries:
            self.tell("'%s' is not a valid TikTok username or link." % text[:60] + hint, from_web,
                      MessageBox.TYPE_ERROR)
            return
        known = [v for k, v in entries if k == "user" and self.store.get(v)]
        todo = [(k, v) for k, v in entries if not (k == "user" and self.store.get(v))]
        if not todo:
            self.tell("@%s is already in your list." % known[0] if len(known) == 1 else
                      "All %d channels are already in your list." % len(known), from_web, MessageBox.TYPE_INFO)
            return
        if self.checking:
            self.tell("Still checking other channels, try again in a moment.", from_web, MessageBox.TYPE_INFO)
            return
        self.checking = True
        self.from_web = from_web
        if from_web:
            self.web_failed = []
        self.batch = {"size": len(entries) + len(rejected), "added": [], "known": known, "failed": [],
                      "unread": [], "rejected": rejected}
        self.say("Checking %s on TikTok..." % (("@" + todo[0][1]) if todo[0][0] == "user" and len(todo) == 1
                                               else "%d channels" % len(todo)))
        have = set(c["username"] for c in self.store.channels)
        worker = threading.Thread(target=self._checkAll, args=(todo, have))
        worker.daemon = True
        worker.start()

    def _checkAll(self, todo, have):
        """Worker thread: read each link, then check each channel on TikTok, one at a time."""
        total = len(todo)
        for n, (kind, value) in enumerate(todo, 1):
            if not self.alive:
                return
            step = ("%d of %d: " % (n, total)) if total > 1 else ""
            user, info, err = (value if kind == "user" else None), None, None
            if kind == "link":
                reactor.callFromThread(self._progress, "Checking %sreading %s..." % (step, short_link(value)))
                try:
                    user = self.sources.link_owner(value)
                except Exception as e:
                    err = str(e) or "error"
            already = bool(user) and user in have
            if user and not already:
                have.add(user)
                reactor.callFromThread(self._progress, "Checking %s@%s on TikTok..." % (step, user))
                try:
                    info = self.sources.channel_info(user)
                except Exception as e:
                    err = str(e) or "error"
            reactor.callFromThread(self._checked, value, user, info, err, already)
        reactor.callFromThread(self._finished)

    def _progress(self, text):
        if self.alive and self.batch is not None:
            self.say(text)

    def _checked(self, value, user, info, err, already):
        b = self.batch
        if not self.alive or b is None:
            return
        if already:
            b["known"].append(user)
        elif user and info:
            if self.store.add(user, info["name"], info.get("sec_uid")):
                self.changed = True
                b["added"].append((user, info))
                self.fill(select=user)
            else:
                b["known"].append(user)
        elif user:
            b["failed"].append((user, err or "error"))
        else:
            b["unread"].append((value, err or "error"))

    def _finished(self):
        self.checking = False
        b, self.batch = self.batch, None
        if not self.alive or b is None:
            return
        from_web = self.from_web
        if b["size"] == 1:
            self._finishedOne(b, from_web)
            return
        lines = []
        if b["added"]:
            lines.append("Added %d: %s" % (len(b["added"]), ", ".join("@" + u for u, _ in b["added"])))
        if b["known"]:
            lines.append("Already in your list: " + ", ".join("@" + u for u in b["known"]))
        if b["failed"]:
            lines.append("Couldn't verify: " + ", ".join("@%s (%s)" % (u, _short_error(e)) for u, e in b["failed"]))
        if b["unread"]:
            lines.append("Couldn't read: " + ", ".join("%s (%s)" % (short_link(link), _short_error(e))
                                                      for link, e in b["unread"]))
        if b["rejected"]:
            lines.append("Not a username or link: " + ", ".join("'%s'" % r[:30] for r in b["rejected"]))
        summary = "\n".join(lines)
        if from_web:
            self.web_failed = list(b["failed"])
            self.say(summary)
            return
        self.say(lines[0] if lines else "")
        if b["failed"]:
            self.pending_add = [u for u, _ in b["failed"]]
            self.session.openWithCallback(self._addAnyway, MessageBox, summary +
                                          "\n\nAdd the channels that couldn't be verified anyway?",
                                          MessageBox.TYPE_YESNO)
        else:
            self.session.open(MessageBox, summary, MessageBox.TYPE_INFO, timeout=15)

    def _finishedOne(self, b, from_web):
        if b["added"]:
            user, info = b["added"][0]
            note = "  (private account: videos may not load)" if info.get("private") else ""
            self.say("Added @%s - %s, %s followers (checked via %s)%s" % (
                user, info["name"], fmt_count(info.get("followers") or 0),
                SOURCE_NAMES.get(info.get("source"), "?"), note))
        elif b["known"]:
            self.say("")
            self.tell("@%s is already in your list." % b["known"][0], from_web, MessageBox.TYPE_INFO)
        elif b["failed"]:
            user, err = b["failed"][0]
            if from_web:
                self.web_failed = [(user, err)]
                self.say("Couldn't verify @%s: %s" % (user, err.replace(" | ", "; ")))
                return
            self.say("")
            self.pending_add = [user]
            self.session.openWithCallback(self._addAnyway, MessageBox,
                                          "Couldn't verify @%s:\n%s\n\nAdd it anyway?"
                                          % (user, err.replace(" | ", "\n")), MessageBox.TYPE_YESNO)
        elif b["unread"]:
            link, err = b["unread"][0]
            self.say("")
            self.tell("Couldn't find the channel behind %s:\n%s" % (short_link(link), err.replace(" | ", "\n")),
                      from_web, MessageBox.TYPE_ERROR)

    def _addAnyway(self, yes):
        users, self.pending_add = self.pending_add, []
        added = [u for u in users if yes and self.store.add(u)]
        if added:
            self.changed = True
            self.say("Added " + ", ".join("@" + u for u in added))
            self.fill(select=added[-1])

    def exit(self):
        self.close(self.changed)


class LibraryScreen(Screen):
    """Every clip in the current tab, newest first; OK jumps to it."""

    def __init__(self, session, items, index, tab_name, prev_visit):
        Screen.__init__(self, session)
        self.skin = LIBRARY_SKIN
        self.skinName = "SimplyScoresLibrary"
        self.clips = items
        self.index = index
        self.prev_visit = prev_visit
        self.arabic_fix = config.plugins.simplyscores.arabic_fix.value
        self["title"] = Label("%s - %d videos" % (tab_name, len(items)))
        self["subtitle"] = Label("Newest first. Highlighted times are new since your last visit.")
        self["list"] = MCList((28, 22), 84)
        self["hint"] = Label("OK play   UP/DOWN move   LEFT/RIGHT page   EXIT back")
        self["actions"] = ActionMap(["OkCancelActions"], {"ok": self.choose, "cancel": self.cancel}, -1)
        self.onLayoutFinish.append(self.fill)

    def entry(self, i, v):
        new = v.get("created", 0) > (self.prev_visit or time.time() - 86400)
        title = v.get("title") or " ".join(v.get("tags") or []) or "Match video"
        rtl = is_rtl(title)
        if self.arabic_fix:
            title = fix_bidi(title)
        return [i,
                T(16, 6, 150, 36, 1, LEFT, time_ago(v.get("created"), short=True),
                  0xFE2C55 if new else 0xB0B0B0),
                T(16, 44, 150, 32, 1, LEFT, fmt_duration(v.get("duration")), 0x7A7A7A),
                T(170, 0, 260, 84, 1, LEFT, "@" + v["user"], 0x25F4EE),
                T(440, 4, 870, 76, 0, WRAP_RIGHT if rtl else WRAP_LEFT, title)]

    def fill(self):
        self["list"].setList([self.entry(i, v) for i, v in enumerate(self.clips)])
        self["list"].moveToIndex(self.index)

    def choose(self):
        cur = self["list"].getCurrent()
        self.close(cur[0] if cur else None)

    def cancel(self):
        self.close(None)


class SettingsScreen(ConfigListScreen, Screen):
    def __init__(self, session, sources=None, test_user="kayfa1x_2", league="eng.1"):
        Screen.__init__(self, session)
        self.skin = SETTINGS_SKIN
        self.skinName = "SimplyScoresSettings"
        self.sources = sources
        self.test_user = test_user
        self.league = league
        cfg = config.plugins.simplyscores
        entries = [
            getConfigListEntry("Video source", cfg.source),
            getConfigListEntry("Video player", cfg.player),
            getConfigListEntry("Video codec", cfg.codec),
            getConfigListEntry("Sound", cfg.audio),
            getConfigListEntry("Prefer HD streams", cfg.hd),
            getConfigListEntry("When a video ends", cfg.on_end),
            getConfigListEntry("Show videos from", cfg.max_age),
            getConfigListEntry("Videos fetched per channel", cfg.per_channel),
            getConfigListEntry("Check channels for new videos every", cfg.cache_minutes),
            getConfigListEntry("Live scores panel", cfg.show_scores),
            getConfigListEntry("Show hashtags", cfg.show_hashtags),
            getConfigListEntry("Hide side panels for landscape videos", cfg.landscape_clean),
            getConfigListEntry("Fix Arabic text (only if letters look broken)", cfg.arabic_fix),
            getConfigListEntry("Check GitHub for plugin updates once a day", cfg.update_check),
        ]
        ConfigListScreen.__init__(self, entries, session=session)
        self["title"] = Label("SimplyScores settings")
        self["subtitle"] = Label("LEFT/RIGHT change a value. Players 5001/5002 need ServiceApp.")
        self["hint"] = Label("Channels: BLUE in the feed.  Leagues: /etc/enigma2/simplyscores.json")
        self["key_red"] = Label("Cancel")
        self["key_green"] = Label("Save")
        self["key_yellow"] = Label("Connection test" if sources else "")
        self["key_blue"] = Label("" if transcode.ffmpeg_path() else "Install ffmpeg")
        self["setup_actions"] = ActionMap(["OkCancelActions", "ColorActions"], {
            "ok": self.save,
            "green": self.save,
            "cancel": self.cancel,
            "red": self.cancel,
            "yellow": self.test,
            "blue": self.installFfmpeg,
        }, -2)

    def test(self):
        if self.sources:
            self.session.open(DiagnoseScreen, self.sources, self.test_user, self.league)

    def installFfmpeg(self):
        """ffmpeg is only needed for 'Sound: Convert with ffmpeg'."""
        if transcode.ffmpeg_path():
            return
        from Screens.Console import Console
        self.session.openWithCallback(self._ffmpegDone, Console, title="Installing ffmpeg",
                                      cmdlist=["opkg update", "opkg install ffmpeg"])

    def _ffmpegDone(self, *args):
        transcode.reset()
        self["key_blue"].setText("" if transcode.ffmpeg_path() else "Install ffmpeg")

    def save(self):
        for entry in self["config"].list:
            entry[1].save()
        configfile.save()
        self.close(True)

    def cancel(self):
        for entry in self["config"].list:
            entry[1].cancel()
        self.close(False)


class DiagnoseScreen(Screen):
    """Runs the connection test and shows the report as it comes in."""

    def __init__(self, session, sources, username, league):
        Screen.__init__(self, session)
        self.skin = DIAG_SKIN
        self.skinName = "SimplyScoresDiagnose"
        self.sources = sources
        self.username = username
        self.league = league
        self.lines = []
        self.running = False
        self.alive = True
        self["title"] = Label("Connection test")
        self["subtitle"] = Label("What each server answers this box (test channel @%s)" % username)
        self["text"] = ScrollLabel("")
        self["hint"] = Label("")
        self["key_red"] = Label("Close")
        self["key_green"] = Label("Run again")
        self["key_yellow"] = Label("")
        self["key_blue"] = Label("")
        self["actions"] = ActionMap(["OkCancelActions", "ColorActions", "DirectionActions"], {
            "ok": self.close,
            "cancel": self.close,
            "red": self.close,
            "green": self.run,
            "up": self["text"].pageUp,
            "down": self["text"].pageDown,
            "left": self["text"].pageUp,
            "right": self["text"].pageDown,
        }, -1)
        self.onLayoutFinish.append(self.run)
        self.onClose.append(self._closed)

    def _closed(self):
        self.alive = False

    def run(self):
        if self.running:
            return
        self.running = True
        self.lines = []
        self["text"].setText("Testing, this can take a minute...")
        self["hint"].setText("Running...")
        worker = threading.Thread(target=self._work)
        worker.daemon = True
        worker.start()

    def _work(self):
        from . import VERSION
        try:
            diagnose.run(self.sources, self.username, self.league,
                         lambda line: reactor.callFromThread(self._line, line), VERSION,
                         sound=lambda: config.plugins.simplyscores.audio.value)
        except Exception as e:
            reactor.callFromThread(self._line, "The test stopped with an error: %s" % e)
        reactor.callFromThread(self._done)

    def _line(self, line):
        if self.alive:
            self.lines.append(line)
            self["text"].setText("\n".join(self.lines))

    def _done(self):
        self.running = False
        if self.alive:
            self["hint"].setText("UP/DOWN scroll.  Report saved as " + diagnose.report_path())
