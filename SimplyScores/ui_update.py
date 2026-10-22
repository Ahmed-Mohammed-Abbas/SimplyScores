# -*- coding: utf-8 -*-
"""MENU in the feed (settings, update, connection test) and the GitHub update flow."""
import os
import threading

from twisted.internet import reactor

from Components.ActionMap import ActionMap
from Components.Label import Label
from Screens.MessageBox import MessageBox
from Screens.Screen import Screen

from . import updater
from .core import log
from .gui import ADD_SKIN, CENTER, LEFT, MCList, T


class PluginMenu(Screen):
    """MENU in the feed. Closes with the key of the chosen row."""

    def __init__(self, session, version, update=None):
        Screen.__init__(self, session)
        self.skin = ADD_SKIN
        self.skinName = "SimplyScoresAddChannel"
        self.version = version
        self.update = update
        self["title"] = Label("SimplyScores %s" % version)
        self["subtitle"] = Label("Football summaries from TikTok, newest first.   By reali22")
        self["list"] = MCList((30, 22), 76)
        self["hint"] = Label("OK open   EXIT back")
        self["actions"] = ActionMap(["OkCancelActions"], {"ok": self.choose, "cancel": self.cancel}, -1)
        self.onLayoutFinish.append(self.fill)

    def rows(self):
        if self.update:
            upd = ("Update plugin to %s" % self.update, "A new version is on GitHub. OK downloads and installs it.")
        else:
            upd = ("Update plugin", "Checks GitHub for a newer version and installs it")
        return [("settings", "SET", 0x25F4EE, "Settings", "Video source, player, codec, sound, time range..."),
                ("update", "NEW" if self.update else "UPD", 0xFE2C55, upd[0], upd[1]),
                ("test", "TEST", 0x25F4EE, "Connection test", "What every server answers this box"),
                ("about", "INFO", 0x9A9A9A, "About and telnet update",
                 "Version, GitHub page and the telnet install command")]

    def fill(self):
        self["list"].setList([[key, T(10, 0, 100, 76, 1, CENTER, tag, color),
                               T(130, 6, 1150, 38, 0, LEFT, name, 0xFFFFFF),
                               T(130, 44, 1150, 28, 1, LEFT, detail, 0xB0B0B0)]
                              for key, tag, color, name, detail in self.rows()])

    def choose(self):
        cur = self["list"].getCurrent()
        self.close(cur[0] if cur else None)

    def cancel(self):
        self.close(None)


class UpdateFlow(object):
    """Check GitHub, ask, download the package, install it with opkg, offer a GUI restart.

    say(text) shows progress (status line of the feed); done() is called when it ends."""

    def __init__(self, session, version, say=None, done=None):
        self.session = session
        self.version = version
        self.say = say or (lambda text: None)
        self.done = done or (lambda: None)
        self.busy = False
        self.path = None

    def _thread(self, fn, *args):
        t = threading.Thread(target=fn, args=args)
        t.daemon = True
        t.start()

    # -- check
    def start(self, latest=None, notes=""):
        if self.busy:
            return
        self.busy = True
        if latest:
            self._checked(latest, notes, None)
            return
        self.say("Checking GitHub for updates...")
        self._thread(self._check)

    def _check(self):
        try:
            latest, notes = updater.check()
            err = None
        except Exception as e:
            latest, notes, err = None, "", str(e) or "error"
        reactor.callFromThread(self._checked, latest, notes, err)

    def _checked(self, latest, notes, err):
        if err:
            self._fail("Couldn't check for updates:\n%s" % err)
            return
        if not updater.is_newer(latest, self.version):
            self.say("SimplyScores %s is the latest version" % self.version)
            self.session.open(MessageBox, "You have the latest version (%s)." % self.version,
                              MessageBox.TYPE_INFO, timeout=8)
            self._end()
            return
        text = "SimplyScores %s is available (you have %s)." % (latest, self.version)
        if notes:
            text += "\n\n" + notes[:600]
        self.session.openWithCallback(lambda yes: self._confirmed(yes, latest), MessageBox,
                                      text + "\n\nDownload and install it now?", MessageBox.TYPE_YESNO)

    # -- download + install
    def _confirmed(self, yes, latest):
        if not yes:
            self._end()
            return
        self.say("Downloading SimplyScores %s..." % latest)
        self._thread(self._download, latest)

    def _download(self, latest):
        try:
            path, err = updater.download(latest), None
        except Exception as e:
            path, err = None, str(e) or "error"
        reactor.callFromThread(self._downloaded, latest, path, err)

    def _downloaded(self, latest, path, err):
        if err:
            self._fail("Couldn't download the update:\n%s" % err)
            return
        self.path = path
        from Screens.Console import Console
        self.session.openWithCallback(lambda *a: self._installed(latest), Console,
                                      title="Installing SimplyScores %s" % latest,
                                      cmdlist=[updater.install_command(path)])

    def _installed(self, latest):
        try:
            if self.path and os.path.exists(self.path):
                os.remove(self.path)
        except OSError:
            pass
        self.say("SimplyScores %s installed - restart the GUI to use it" % latest)
        self.session.openWithCallback(self._restart, MessageBox,
                                      "SimplyScores %s is installed.\nRestart the GUI now to start using it?"
                                      % latest, MessageBox.TYPE_YESNO)

    def _restart(self, yes):
        self._end()
        if yes:
            from Screens.Standby import TryQuitMainloop
            self.session.open(TryQuitMainloop, 3)

    def _fail(self, text):
        log(text.replace("\n", " "))
        self.say(text.split("\n")[0])
        self.session.open(MessageBox, text + "\n\nYou can also update by telnet:\n" + updater.telnet_command(),
                          MessageBox.TYPE_ERROR)
        self._end()

    def _end(self):
        self.busy = False
        self.done()


def about_text(version):
    return ("SimplyScores %s by reali22\nTikTok football summaries and live scores for Enigma2.\n\n"
            "GitHub: https://github.com/%s\n\nInstall or update by telnet/SSH:\n%s"
            % (version, updater.REPO, updater.telnet_command()))
