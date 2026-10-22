"""Simulated Enigma2 session: fake nav/player, skin layout checks, reactor pumping."""
import os
import sys
import tempfile
import time
import xml.etree.ElementTree as ET

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(HERE, "fake_e2"))
sys.path.insert(1, ROOT)

from twisted.internet import reactor  # noqa: E402  (the fake one)
from Components.GUIComponent import FakeInstance, GUIComponent  # noqa: E402


TMP = tempfile.mkdtemp(prefix="simplyscores_test_")


def install():
    """Point the plugin at temp paths and the fake internet (see fake_net.py)."""
    import fake_net
    from SimplyScores import api_scores, core, diagnose, feed, images, src_tikwm, src_tiktok, updater
    world = fake_net.start()
    core.CONFIG_PATH = os.path.join(TMP, "simplyscores.json")
    core.PREFERRED_SEED = 0          # the suites use the plain default list; test_channels.py turns it on
    cache = os.path.join(TMP, "cache")
    feed.CACHE_DIR = images.CACHE_DIR = diagnose.CACHE_DIR = core.CACHE_DIR = cache
    src_tikwm.HOSTS[:] = [world.base + "/tw", world.base + "/twa"]
    src_tikwm.MIN_GAP = 0.0
    src_tiktok.BASE = world.base + "/tt"
    updater.RAW = world.base + "/gh"
    src_tiktok.SHORT_HOSTS.update({"vm.tiktok.com": world.base + "/vm", "vt.tiktok.com": world.base + "/vt"})
    api_scores.URL = world.base + "/espn/%s/scoreboard"
    diagnose.DNS_HOSTS = ("localhost",)
    return world


class FakeService(object):
    def __init__(self, ref):
        self.ref, self.pos, self.length, self.paused = ref, 0, 58 * 90000, False
        self.w, self.h = 576, 1024
        self.strings = {}

    def seek(self):
        svc = self

        class Seek(object):
            def getLength(self):
                return (0, svc.length)

            def getPlayPosition(self):
                return (0, svc.pos)

            def isCurrentlySeekable(self):
                return 1

            def seekRelative(self, direction, pts):
                svc.pos = max(0, svc.pos + direction * pts)
        return Seek()

    def pause(self):
        svc = self

        class Pause(object):
            def pause(self):
                svc.paused = True

            def unpause(self):
                svc.paused = False
        return Pause()

    def info(self):
        svc = self

        class Info(object):
            def getInfo(self, what):
                return svc.w if what == 1 else svc.h

            def getInfoString(self, what):
                return svc.strings.get(what, "")
        return Info()


class FakeNav(object):
    def __init__(self):
        self.ref, self.service, self.log = "LIVE-TV", None, []

    def getCurrentlyPlayingServiceOrGroup(self):
        return self.ref

    def stopService(self):
        self.ref, self.service = None, None
        self.log.append("stop")

    def playService(self, ref):
        self.ref, self.service = ref, FakeService(ref)
        self.log.append(ref)

    def getCurrentService(self):
        return self.service


class FakeSession(object):
    def __init__(self):
        self.nav = FakeNav()
        self.dialogs = []

    def open(self, cls, *args, **kw):
        return self.openWithCallback(None, cls, *args, **kw)

    def openWithCallback(self, cb, cls, *args, **kw):
        screen = cls(self, *args, **kw)
        screen.callback = cb
        self.dialogs.append(screen)
        if isinstance(screen, dict):
            layout(screen)
        return screen


def layout(screen):
    """Mimic skin application: every skin widget must exist on the screen."""
    root = ET.fromstring(screen.skin)
    names = set()
    for el in root.iter("widget"):
        name = el.get("name")
        if name:
            assert name in screen, "skin widget %r has no component in %s" % (name, type(screen).__name__)
            names.add(name)
    fonts = dict((el.get("name"), el) for el in root.iter("widget") if el.get("name"))
    for key, comp in screen.items():
        if isinstance(comp, GUIComponent) and key in names:
            comp.instance = FakeInstance()
            el = fonts[key]
            if el.get("font"):
                comp.instance.calculateSize = _size_fn(comp, el)
    screen.unskinned = [k for k, c in screen.items() if isinstance(c, GUIComponent) and k not in names]
    for fn in screen.onLayoutFinish:
        fn()


class _Size(object):
    def __init__(self, w, h):
        self._w, self._h = w, h

    def width(self):
        return self._w

    def height(self):
        return self._h


def _size_fn(comp, el):
    """Emulate eLabel.calculateSize() with the preview renderer's font metrics."""
    def calc():
        import render_preview
        size = int(el.get("font").split(";")[1])
        width = int(el.get("size").split(",")[0])
        lines = render_preview.wrap(comp.getText(), render_preview.font(size), width)
        return _Size(width, int(len([l for l in lines if l]) * size * 1.22))
    return calc


def settle(cond=lambda: True, timeout=10.0):
    """Pump queued main-thread calls until cond() holds and the queue is idle."""
    end = time.time() + timeout
    while time.time() < end:
        reactor.pump()
        if cond() and not reactor.queue:
            time.sleep(0.05)
            if not reactor.queue:
                return True
        time.sleep(0.02)
    raise AssertionError("timed out waiting for background work")


def fire(timer):
    return timer.timer.fire()
