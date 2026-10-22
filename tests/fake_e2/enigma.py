"""Minimal stand-in for Enigma2's C++ 'enigma' module (test harness only)."""
import os

RT_HALIGN_LEFT, RT_HALIGN_RIGHT, RT_HALIGN_CENTER = 0, 2, 4
RT_VALIGN_TOP, RT_VALIGN_CENTER, RT_VALIGN_BOTTOM = 0, 8, 16
RT_WRAP = 32

DESKTOP_WIDTH = int(os.environ.get("FAKE_DESKTOP", "1920"))
TIMERS = []


class eTimer(object):
    def __init__(self):
        self.callback = []
        self.active = False
        self.single = True
        self.interval = 0
        TIMERS.append(self)

    def start(self, ms, single=False):
        self.interval, self.single, self.active = ms, single, True

    def stop(self):
        self.active = False

    def isActive(self):
        return self.active

    def fire(self):
        if not self.active:
            return False
        if self.single:
            self.active = False
        for fn in list(self.callback):
            fn()
        return True


class _Size(object):
    def __init__(self, w, h):
        self._w, self._h = w, h

    def width(self):
        return self._w

    def height(self):
        return self._h


class _Desktop(object):
    def size(self):
        return _Size(DESKTOP_WIDTH, DESKTOP_WIDTH * 9 // 16)


def getDesktop(n):
    return _Desktop()


class eServiceReference(object):
    def __init__(self, stype, flags, path):
        self.type, self.flags, self.path, self.name = stype, flags, path, ""

    def setName(self, name):
        self.name = name

    def getName(self):
        return self.name

    def __repr__(self):
        return "<ref %s %s>" % (self.type, self.path[:60])


class iPlayableService(object):
    evStart, evEnd, evEOF, evUpdatedInfo, evVideoSizeChanged = 1, 2, 3, 4, 5
    evUser = 100


class iServiceInformation(object):
    sVideoWidth, sVideoHeight, sTagVideoCodec, sTagAudioCodec = 1, 2, 3, 4
    sUser = 1000


class eListboxPythonMultiContent(object):
    def __init__(self):
        self.fonts, self.item_height, self.list = {}, 0, []

    def setFont(self, i, font):
        self.fonts[i] = font

    def setItemHeight(self, h):
        self.item_height = h

    def setList(self, lst):
        self.list = lst


class eListboxPythonStringContent(eListboxPythonMultiContent):
    pass


def gFont(name, size):
    return (name, size)


class eLabel(object):
    alignLeft, alignCenter, alignRight, alignBlock = 0, 1, 2, 3
class ePoint(object):
    def __init__(self, x, y):
        self.x, self.y = x, y
