# -*- coding: utf-8 -*-
"""Skins (designed at 1920x1080, scaled for 1280x720), timers and list helpers."""
import os
import re

from enigma import (eListboxPythonMultiContent, eTimer, gFont, getDesktop,
                    RT_HALIGN_CENTER, RT_HALIGN_LEFT, RT_HALIGN_RIGHT,
                    RT_VALIGN_CENTER, RT_VALIGN_TOP, RT_WRAP)
from Components.MenuList import MenuList
from Components.MultiContent import MultiContentEntryPixmapAlphaBlend, MultiContentEntryText
from Tools.LoadPixmap import LoadPixmap

from .core import PLUGIN_DIR


def _desktop_width():
    try:
        return getDesktop(0).size().width()
    except Exception:
        return 1280


FHD = _desktop_width() >= 1920
SCALE = 1.0 if FHD else 2.0 / 3.0
ICONS = os.path.join(PLUGIN_DIR, "icons", "fhd" if FHD else "hd")

LEFT = RT_HALIGN_LEFT | RT_VALIGN_CENTER
RIGHT = RT_HALIGN_RIGHT | RT_VALIGN_CENTER
CENTER = RT_HALIGN_CENTER | RT_VALIGN_CENTER
WRAP_LEFT = RT_HALIGN_LEFT | RT_VALIGN_TOP | RT_WRAP
WRAP_RIGHT = RT_HALIGN_RIGHT | RT_VALIGN_TOP | RT_WRAP


def s(value):
    """Scale an FHD pixel value to the current desktop."""
    return int(round(value * SCALE))


def scale_skin(xml):
    xml = xml.replace("{icons}", ICONS)
    if SCALE == 1.0:
        return xml

    def pair(m):
        return '%s="%d,%d"' % (m.group(1), s(int(m.group(2))), s(int(m.group(3))))

    xml = re.sub(r'\b(position|size|shadowOffset)="(-?\d+),(-?\d+)"', pair, xml)
    xml = re.sub(r'font="([^";]+);(\d+)"',
                 lambda m: 'font="%s;%d"' % (m.group(1), s(int(m.group(2)))), xml)
    xml = re.sub(r'\b(itemHeight|borderWidth)="(\d+)"',
                 lambda m: '%s="%d"' % (m.group(1), s(int(m.group(2)))), xml)
    return xml


class Timer(object):
    """eTimer wrapper that works with both callback styles."""

    def __init__(self, fn):
        self.timer = eTimer()
        self.conn = None
        try:
            self.timer.callback.append(fn)
        except AttributeError:
            self.conn = self.timer.timeout.connect(fn)

    def start(self, ms, single=True):
        self.timer.start(int(ms), single)

    def stop(self):
        self.timer.stop()


class MCList(MenuList):
    """MultiContent list; fonts and item height are given in FHD pixels."""

    def __init__(self, fonts, item_height):
        MenuList.__init__(self, [], False, eListboxPythonMultiContent)
        for i, size in enumerate(fonts):
            self.l.setFont(i, gFont("Regular", s(size)))
        self.l.setItemHeight(s(item_height))


def T(x, y, w, h, font, flags, text, color=0xFFFFFF):
    """Text cell, coordinates in FHD pixels."""
    return MultiContentEntryText(pos=(s(x), s(y)), size=(s(w), s(h)), font=font, flags=flags,
                                 text=text, color=color, color_sel=color)


def P(x, y, w, h, path):
    """Pixmap cell, or None when the file cannot be loaded."""
    if not path:
        return None
    try:
        ptr = LoadPixmap(path, cached=False)
    except Exception:
        ptr = None
    if not ptr:
        return None
    return MultiContentEntryPixmapAlphaBlend(pos=(s(x), s(y)), size=(s(w), s(h)), png=ptr)


def set_rtl(component, rtl):
    """Right-align Arabic text (no-op where the API is missing)."""
    inst = getattr(component, "instance", None)
    if inst is None:
        return
    try:
        from enigma import eLabel
        inst.setHAlign(eLabel.alignRight if rtl else eLabel.alignLeft)
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Feed screen: the vertical clip plays full screen and the receiver pillarboxes
# it into the centre column (x 656-1264). Panels live in the black side bars.
# ---------------------------------------------------------------------------
_CARD = "#40161616"
_TXT = 'transparent="1" backgroundColor="%s" zPosition="3"' % _CARD
_SHADOW = 'transparent="1" backgroundColor="#ff000000" shadowColor="#000000" shadowOffset="-2,-2"'

FEED_SKIN = scale_skin("""
<screen name="SimplyScoresFeed" position="0,0" size="1920,1080" flags="wfNoBorder" backgroundColor="#ff000000">
	<widget name="cover" position="656,0" size="608,1080" zPosition="1" alphatest="off" scale="1" />

	<widget name="card_scores" position="24,24" size="608,540" backgroundColor="%(card)s" zPosition="1" />
	<widget name="score_tag" position="48,44" size="118,38" font="Regular;22" halign="center" valign="center" foregroundColor="#ffffff" backgroundColor="#fe2c55" zPosition="3" />
	<widget name="score_title" position="180,38" size="430,50" font="Regular;30" valign="center" noWrap="1" foregroundColor="#ffffff" %(txt)s />
	<widget name="score_list" position="40,98" size="576,432" scrollbarMode="showNever" backgroundColor="%(card)s" backgroundColorSelected="%(card)s" transparent="1" zPosition="3" />
	<widget name="score_page" position="40,528" size="576,30" font="Regular;22" halign="right" foregroundColor="#8a8a8a" %(txt)s />

	<widget name="card_post" position="24,584" size="608,472" backgroundColor="%(card)s" zPosition="1" />
	<widget name="author" position="48,600" size="560,48" font="Regular;34" noWrap="1" foregroundColor="#ffffff" %(txt)s />
	<widget name="meta" position="48,650" size="560,34" font="Regular;24" noWrap="1" foregroundColor="#b0b0b0" %(txt)s />
	<widget name="badge" position="48,692" size="86,32" font="Regular;20" halign="center" valign="center" foregroundColor="#ffffff" backgroundColor="#fe2c55" zPosition="3" />
	<widget name="caption" position="48,734" size="560,166" font="Regular;32" foregroundColor="#ffffff" %(txt)s />
	<widget name="tags" position="48,908" size="560,62" font="Regular;24" foregroundColor="#25f4ee" %(txt)s />
	<widget name="music_icon" pixmap="{icons}/music.png" position="48,1014" size="30,30" alphatest="blend" zPosition="3" />
	<widget name="music" position="88,1008" size="520,40" font="Regular;24" valign="center" noWrap="1" foregroundColor="#d0d0d0" %(txt)s />

	<widget name="tab_cur" position="656,18" size="608,54" font="Regular;34" halign="center" valign="center" noWrap="1" foregroundColor="#ffffff" zPosition="4" %(shadow)s />
	<widget name="tab_line" position="930,74" size="60,5" backgroundColor="#ffffff" zPosition="4" />
	<widget name="tab_side" position="656,84" size="608,32" font="Regular;22" halign="center" valign="center" noWrap="1" foregroundColor="#d8d8d8" zPosition="4" %(shadow)s />
	<widget name="pill" position="860,126" size="200,40" font="Regular;22" halign="center" valign="center" foregroundColor="#ffffff" backgroundColor="#fe2c55" zPosition="4" />
	<widget name="center_msg" position="680,430" size="560,220" font="Regular;26" halign="center" valign="center" foregroundColor="#ffffff" backgroundColor="#50000000" zPosition="5" />
	<widget name="pause_icon" pixmap="{icons}/play_big.png" position="900,480" size="120,120" alphatest="blend" zPosition="5" />
	<widget name="progress" position="656,1068" size="608,8" foregroundColor="#ffffff" backgroundColor="#b0ffffff" borderWidth="0" zPosition="4" />

	<widget name="avatar" position="1302,300" size="100,100" alphatest="blend" scale="1" zPosition="3" />
	<widget name="follow_icon" pixmap="{icons}/follow.png" position="1334,382" size="36,36" alphatest="blend" zPosition="4" />
	<widget name="like_icon" pixmap="{icons}/like.png" position="1322,446" size="60,60" alphatest="blend" zPosition="3" />
	<widget name="likes" position="1282,508" size="140,34" font="Regular;24" halign="center" noWrap="1" foregroundColor="#ffffff" zPosition="3" %(shadow)s />
	<widget name="comment_icon" pixmap="{icons}/comment.png" position="1322,560" size="60,60" alphatest="blend" zPosition="3" />
	<widget name="comments" position="1282,622" size="140,34" font="Regular;24" halign="center" noWrap="1" foregroundColor="#ffffff" zPosition="3" %(shadow)s />
	<widget name="share_icon" pixmap="{icons}/share.png" position="1322,674" size="60,60" alphatest="blend" zPosition="3" />
	<widget name="shares" position="1282,736" size="140,34" font="Regular;24" halign="center" noWrap="1" foregroundColor="#ffffff" zPosition="3" %(shadow)s />
	<widget name="views_icon" pixmap="{icons}/views.png" position="1322,788" size="60,60" alphatest="blend" zPosition="3" />
	<widget name="views" position="1282,850" size="140,34" font="Regular;24" halign="center" noWrap="1" foregroundColor="#ffffff" zPosition="3" %(shadow)s />
	<widget name="disc_icon" pixmap="{icons}/disc.png" position="1317,912" size="70,70" alphatest="blend" zPosition="3" />

	<widget name="position" position="1440,30" size="220,40" font="Regular;24" valign="center" noWrap="1" foregroundColor="#b0b0b0" transparent="1" backgroundColor="#ff000000" zPosition="3" />
	<widget source="global.CurrentTime" render="Label" position="1660,24" size="220,52" font="Regular;40" halign="right" valign="center" foregroundColor="#ffffff" transparent="1" backgroundColor="#ff000000" zPosition="3">
		<convert type="ClockToText">Default</convert>
	</widget>
	<widget name="card_next" position="1428,96" size="468,464" backgroundColor="%(card)s" zPosition="1" />
	<widget name="next_title" position="1448,108" size="428,40" font="Regular;26" valign="center" foregroundColor="#ffffff" %(txt)s />
	<widget name="upnext" position="1448,156" size="428,384" scrollbarMode="showNever" backgroundColor="%(card)s" backgroundColorSelected="%(card)s" transparent="1" zPosition="3" />

	<widget name="card_nav" position="1428,572" size="468,180" backgroundColor="%(card)s" zPosition="1" />
	<widget name="nav_up" pixmap="{icons}/nav_up.png" position="1448,586" size="40,40" alphatest="blend" zPosition="3" />
	<widget name="nav_up_txt" position="1556,586" size="320,40" font="Regular;24" valign="center" noWrap="1" foregroundColor="#e0e0e0" %(txt)s />
	<widget name="nav_down" pixmap="{icons}/nav_down.png" position="1448,638" size="40,40" alphatest="blend" zPosition="3" />
	<widget name="nav_down_txt" position="1556,638" size="320,40" font="Regular;24" valign="center" noWrap="1" foregroundColor="#e0e0e0" %(txt)s />
	<widget name="nav_left" pixmap="{icons}/nav_left.png" position="1448,690" size="40,40" alphatest="blend" zPosition="3" />
	<widget name="nav_right" pixmap="{icons}/nav_right.png" position="1498,690" size="40,40" alphatest="blend" zPosition="3" />
	<widget name="nav_side_txt" position="1556,690" size="320,40" font="Regular;24" valign="center" noWrap="1" foregroundColor="#e0e0e0" %(txt)s />
	<widget name="status" position="1440,760" size="440,64" font="Regular;22" foregroundColor="#9a9a9a" transparent="1" backgroundColor="#ff000000" zPosition="3" />
	<widget name="card_keys" position="1428,832" size="468,224" backgroundColor="%(card)s" zPosition="1" />
	<widget name="key_red_dot" position="1452,858" size="22,22" backgroundColor="#f23d3d" zPosition="3" />
	<widget name="key_red" position="1486,848" size="390,40" font="Regular;24" valign="center" noWrap="1" foregroundColor="#e0e0e0" %(txt)s />
	<widget name="key_green_dot" position="1452,900" size="22,22" backgroundColor="#3cc35a" zPosition="3" />
	<widget name="key_green" position="1486,890" size="390,40" font="Regular;24" valign="center" noWrap="1" foregroundColor="#e0e0e0" %(txt)s />
	<widget name="key_yellow_dot" position="1452,942" size="22,22" backgroundColor="#e6c229" zPosition="3" />
	<widget name="key_yellow" position="1486,932" size="390,40" font="Regular;24" valign="center" noWrap="1" foregroundColor="#e0e0e0" %(txt)s />
	<widget name="key_blue_dot" position="1452,984" size="22,22" backgroundColor="#2f7bf0" zPosition="3" />
	<widget name="key_blue" position="1486,974" size="390,40" font="Regular;24" valign="center" noWrap="1" foregroundColor="#e0e0e0" %(txt)s />
	<widget name="key_hint" position="1452,1016" size="424,32" font="Regular;20" valign="center" noWrap="1" foregroundColor="#9a9a9a" %(txt)s />
</screen>""" % {"card": _CARD, "txt": _TXT, "shadow": _SHADOW})

# Widgets grouped for clean view / landscape clips / scores on-off.
SCORE_WIDGETS = ("card_scores", "score_tag", "score_title", "score_list", "score_page")
POST_WIDGETS = ("card_post", "author", "meta", "caption", "tags", "music_icon", "music")
ACTION_WIDGETS = ("avatar", "follow_icon", "like_icon", "likes", "comment_icon", "comments",
                  "share_icon", "shares", "views_icon", "views", "disc_icon")
NAV_WIDGETS = ("card_nav", "nav_up", "nav_up_txt", "nav_down", "nav_down_txt", "nav_left", "nav_right",
               "nav_side_txt")
RIGHT_WIDGETS = NAV_WIDGETS + ("position", "card_next", "next_title", "upnext", "status", "card_keys",
                 "key_red_dot", "key_red", "key_green_dot", "key_green", "key_yellow_dot",
                 "key_yellow", "key_blue_dot", "key_blue", "key_hint")

# ---------------------------------------------------------------------------
# Dialog screens
# ---------------------------------------------------------------------------
_BG = "#0c101010"
_DLG_TXT = 'transparent="1" backgroundColor="%s"' % _BG
_KEYS = """
	<eLabel position="40,812" size="22,22" backgroundColor="#f23d3d" />
	<widget name="key_red" position="72,802" size="280,42" font="Regular;26" valign="center" noWrap="1" foregroundColor="#e0e0e0" %(t)s />
	<eLabel position="370,812" size="22,22" backgroundColor="#3cc35a" />
	<widget name="key_green" position="402,802" size="280,42" font="Regular;26" valign="center" noWrap="1" foregroundColor="#e0e0e0" %(t)s />
	<eLabel position="700,812" size="22,22" backgroundColor="#e6c229" />
	<widget name="key_yellow" position="732,802" size="280,42" font="Regular;26" valign="center" noWrap="1" foregroundColor="#e0e0e0" %(t)s />
	<eLabel position="1030,812" size="22,22" backgroundColor="#2f7bf0" />
	<widget name="key_blue" position="1062,802" size="300,42" font="Regular;26" valign="center" noWrap="1" foregroundColor="#e0e0e0" %(t)s />
""" % {"t": _DLG_TXT}

_HEAD = """
	<eLabel position="0,0" size="1400,6" backgroundColor="#fe2c55" />
	<widget name="title" position="40,24" size="1320,56" font="Regular;40" valign="center" noWrap="1" foregroundColor="#ffffff" %(t)s />
	<widget name="subtitle" position="40,82" size="1320,36" font="Regular;24" valign="center" noWrap="1" foregroundColor="#9a9a9a" %(t)s />
""" % {"t": _DLG_TXT}

CHANNELS_SKIN = scale_skin("""
<screen name="SimplyScoresChannels" position="center,center" size="1400,860" flags="wfNoBorder" backgroundColor="%(bg)s">%(head)s
	<widget name="list" position="40,132" size="1320,608" scrollbarMode="showOnDemand" backgroundColor="%(bg)s" backgroundColorSelected="#2e2e2e" transparent="1" />
	<widget name="status" position="40,748" size="1320,40" font="Regular;24" valign="center" foregroundColor="#25f4ee" %(t)s />%(keys)s
</screen>""" % {"bg": _BG, "head": _HEAD, "keys": _KEYS, "t": _DLG_TXT})

LIBRARY_SKIN = scale_skin("""
<screen name="SimplyScoresLibrary" position="center,center" size="1400,860" flags="wfNoBorder" backgroundColor="%(bg)s">%(head)s
	<widget name="list" position="40,132" size="1320,672" scrollbarMode="showOnDemand" backgroundColor="%(bg)s" backgroundColorSelected="#2e2e2e" transparent="1" />
	<widget name="hint" position="40,812" size="1320,36" font="Regular;24" valign="center" noWrap="1" foregroundColor="#9a9a9a" %(t)s />
</screen>""" % {"bg": _BG, "head": _HEAD, "t": _DLG_TXT})

ADD_SKIN = scale_skin("""
<screen name="SimplyScoresAddChannel" position="center,center" size="1400,860" flags="wfNoBorder" backgroundColor="%(bg)s">%(head)s
	<widget name="list" position="40,132" size="1320,672" scrollbarMode="showOnDemand" backgroundColor="%(bg)s" backgroundColorSelected="#2e2e2e" transparent="1" />
	<widget name="hint" position="40,812" size="1320,36" font="Regular;24" valign="center" noWrap="1" foregroundColor="#9a9a9a" %(t)s />
</screen>""" % {"bg": _BG, "head": _HEAD, "t": _DLG_TXT})

SETTINGS_SKIN = scale_skin("""
<screen name="SimplyScoresSettings" position="center,center" size="1400,860" flags="wfNoBorder" backgroundColor="%(bg)s">%(head)s
	<widget name="config" position="40,132" size="1320,600" scrollbarMode="showOnDemand" backgroundColor="%(bg)s" />
	<widget name="hint" position="40,748" size="1320,40" font="Regular;24" valign="center" noWrap="1" foregroundColor="#9a9a9a" %(t)s />%(keys)s
</screen>""" % {"bg": _BG, "head": _HEAD, "keys": _KEYS, "t": _DLG_TXT})

DIAG_SKIN = scale_skin("""
<screen name="SimplyScoresDiagnose" position="center,center" size="1400,860" flags="wfNoBorder" backgroundColor="%(bg)s">%(head)s
	<widget name="text" position="40,132" size="1320,608" font="Regular;24" foregroundColor="#e0e0e0" backgroundColor="%(bg)s" />
	<widget name="hint" position="40,748" size="1320,40" font="Regular;24" valign="center" noWrap="1" foregroundColor="#25f4ee" %(t)s />%(keys)s
</screen>""" % {"bg": _BG, "head": _HEAD, "keys": _KEYS, "t": _DLG_TXT})
