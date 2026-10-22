"""Preferred channels (first in For You), the one-time preferred list and the arrow-key helper.

Usage: python3 tests/test_preferred.py
"""
import json
import os

import harness
from harness import FakeSession, fire, settle

world = harness.install()

import requests  # noqa: E402
from SimplyScores import core, gui  # noqa: E402
from SimplyScores import plugin  # noqa: E402,F401  (defines config.plugins.simplyscores)
assert plugin
from SimplyScores.feed import FeedManager  # noqa: E402
from SimplyScores.ui_feed import SimplyScoresFeed  # noqa: E402
from SimplyScores.ui_manage import ChannelsScreen  # noqa: E402

passed = []


def check(cond, label):
    assert cond, "FAILED: " + label
    passed.append(label)


# --------------------------------------------------------------------------- the user's list, once
path = os.path.join(harness.TMP, "seed.json")
json.dump({"tiktok_channels": core.DEFAULT_CHANNELS}, open(path, "w"))    # a 1.4.0 list
core.PREFERRED_SEED = 1
store = core.ChannelStore(path)
names = [c["username"] for c in store.channels]
check(names[:8] == core.PREFERRED_CHANNELS and all(store.get(u)["preferred"] for u in names[:8]),
      "preferred channels put at the top of an existing list")
check(names[8:] == ["championsleague", "laliga", "premierleague", "cbssportsgolazo"]
      and not any(store.get(u)["preferred"] for u in names[8:]), "the other channels kept after them")
check(store.get("kayfa1x_2")["name"] == "Kayfa1x Summaries", "existing channel keeps its name")
check(store.extra["pending_links"] == ["https://vt.tiktok.com/ZSgyS93uw/"], "share link waits to be read on the box")
store.remove("zzcombs3")
store.toggle_preferred("ligue1")
again = core.ChannelStore(path)
check(again.get("zzcombs3") is None and not again.get("ligue1")["preferred"], "the list is added once, edits stay")
check(again.add("newchan", preferred=True) and [c["username"] for c in again.channels].index("newchan") == 7,
      "a new preferred channel goes after the other preferred ones")

# --------------------------------------------------------------------------- For You order
fm = FeedManager(os.path.join(harness.TMP, "fm_pref"))
fm.videos = {"a": [{"id": "1", "user": "a", "created": 100}, {"id": "2", "user": "a", "created": 300}],
             "b": [{"id": "3", "user": "b", "created": 500}, {"id": "4", "user": "b", "created": 50}]}
check([v["id"] for v in fm.merged(["a", "b"], 0, now=1000)] == ["3", "2", "1", "4"], "without preference: newest first")
check([v["id"] for v in fm.merged(["a", "b"], 0, now=1000, preferred={"a"})] == ["2", "1", "3", "4"],
      "preferred channel's videos first, each group newest first")

# --------------------------------------------------------------------------- feed screen
core.PREFERRED_CHANNELS = ["laliga", "brfootball"]
core.PREFERRED_LINKS = ["https://vt.tiktok.com/ZSspl01/"]
if os.path.exists(core.CONFIG_PATH):
    os.remove(core.CONFIG_PATH)
session = FakeSession()
scr = session.open(SimplyScoresFeed)
check(scr.unskinned == [], "every feed component is in the skin")
settle(lambda: not scr.refreshing and scr.store.get("spl") is not None, 60)
settle(lambda: not scr.refreshing, 60)
pref = scr.store.preferred()
check(pref == {"laliga", "brfootball", "spl"}, "share link from the list read on the box and added as preferred")
check(scr.store.extra["pending_links"] == [], "link not read again next time")
check(scr.store.get("brfootball")["name"] == "B/R Football", "real channel name filled in from TikTok")
users = [v["user"] for v in scr.clips]
first_other = next(i for i, u in enumerate(users) if u not in pref)
check(first_other > 0 and all(u not in pref for u in users[first_other:]),
      "For You opens with the preferred channels' videos")
check(scr.tabs[0][1] == "For You" and scr.index == 0 and users[0] in pref, "plugin opens on For You, preferred first")
scr.nextTab()
check(scr.clips and all(v["user"] == scr.tabs[1][0] for v in scr.clips), "a channel tab shows only that channel")
scr.prevTab()

# the image's own seek / PVR-state pop-up (Egami shows it in the middle of the screen)
from Screens.InfoBar import InfoBar  # noqa: E402


class _Dialog(object):
    def __init__(self, cls):
        self.shown = True
        self.__class__ = type(cls, (_Dialog,), {})

    def hide(self):
        self.shown = False


class _Bar(object):
    pass


bar = _Bar()
bar.pvrStateDialog = _Dialog("PVRState")
bar.seekPopup = _Dialog("InfoBarSeekPopup")
bar.secondInfoBarScreen = _Dialog("SecondInfoBar")
InfoBar.instance = bar
fire(scr.tickTimer)
check(not bar.pvrStateDialog.shown and not bar.seekPopup.shown, "image's seek bar hidden over the feed")
check(bar.secondInfoBarScreen.shown, "other InfoBar screens left alone")
InfoBar.instance = None

# arrow-key helper
check(scr["nav_up_txt"].getText() == "Previous video (newer)" and scr["nav_down_txt"].getText() == "Next video (older)"
      and scr["nav_side_txt"].getText() == "Switch channel tab", "arrow-key helper labels")
for name in ("nav_up", "nav_down", "nav_left", "nav_right"):
    check(os.path.exists(os.path.join(gui.ICONS, name + ".png")), "arrow icon %s exists" % name)
check(all(scr[n].visible for n in gui.NAV_WIDGETS), "helper visible")
scr["actions"].actions["info"]()
check(not any(scr[n].visible for n in gui.NAV_WIDGETS), "helper hidden in clean view")
scr["actions"].actions["info"]()

# channel manager: MENU toggles preferred
scr["actions"].actions["blue"]()
ch = session.dialogs[-1]
check(isinstance(ch, ChannelsScreen) and "MENU preferred" in ch["subtitle"].getText(), "manager explains MENU")
row = ch["list"].list[ch.store.index("laliga")]
check(any(c[1].get("text") == "TOP" for c in row[1:]), "preferred channel marked TOP")
ch["list"].moveToIndex(ch.store.index("laliga"))
ch["actions"].actions["menu"]()
check(not ch.store.get("laliga")["preferred"] and "no longer preferred" in ch["status"].getText(), "MENU unprefers")
base = "http://127.0.0.1:%d" % ch.page.port
check("Prefer</button>" in requests.get(base + "/").text, "phone page has Prefer buttons")
requests.post(base + "/prefer", data={"user": "laliga"})
settle(lambda: ch.store.get("laliga")["preferred"])
check(ch.store.get("laliga")["preferred"], "Prefer from the phone")
ch["actions"].actions["cancel"]()
settle(lambda: not scr.refreshing, 30)
fire(scr.playTimer)
scr["actions"].actions["cancel"]()

print("All %d preferred-channel checks passed." % len(passed))
