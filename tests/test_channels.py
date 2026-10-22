"""Channel suggestions, TikTok share links and adding several channels at once.

Usage: python3 tests/test_channels.py
"""
import os
import re

import harness
from harness import FakeSession, settle

world = harness.install()

import requests  # noqa: E402
from SimplyScores import core, net  # noqa: E402
from SimplyScores import plugin  # noqa: E402,F401  (defines config.plugins.simplyscores)
assert plugin
from SimplyScores.feed import FeedManager  # noqa: E402
from SimplyScores.sources import Sources  # noqa: E402
from SimplyScores.ui_manage import AddChannelScreen, ChannelsScreen  # noqa: E402
import sample_data  # noqa: E402

passed = []


def check(cond, label):
    assert cond, "FAILED: " + label
    passed.append(label)


def fails(fn, *args):
    try:
        fn(*args)
    except net.SourceError:
        return True
    return False


def manager(name, keep):
    """A channel manager whose list holds only the channels in keep."""
    store = core.ChannelStore(os.path.join(harness.TMP, name + ".json"))
    for user in [c["username"] for c in store.channels]:
        if user not in keep:
            store.remove(user)
    session = FakeSession()
    ch = session.open(ChannelsScreen, store, FeedManager(os.path.join(harness.TMP, "fm_" + name)), Sources())
    return session, store, ch


# --------------------------------------------------------------------------- typed / pasted text
P = core.parse_channel_input
check(P("kayfa1x_2") == ([("user", "kayfa1x_2")], []), "one username")
check(P("spl, qsl\n433;@brfootball")[0] == [("user", "spl"), ("user", "qsl"), ("user", "433"), ("user", "brfootball")],
      "names separated by commas, new lines or semicolons")
check(P("@spl @qsl")[0] == [("user", "spl"), ("user", "qsl")], "'@name @name' on one line")
check(P("Check out Kayfa's video! #TikTok https://vt.tiktok.com/ZSabc123/.") ==
      ([("link", "https://vt.tiktok.com/ZSabc123/")], []), "text shared from the app counts only for its link")
check(P("https://www.tiktok.com/@SPL?_t=ZS-8xyz&_r=1")[0] == [("user", "spl")], "profile link read directly")
check(P("https://www.tiktok.com/@laliga/video/7412345678901234567?is_from_webapp=1")[0] == [("user", "laliga")],
      "video link read directly")
check(P("www.tiktok.com/t/ZTabc/")[0] == [("link", "https://www.tiktok.com/t/ZTabc/")], "tiktok.com/t/ link kept to look up")
check(P("Premier League") == ([], ["Premier League"]), "a display name is not split into two usernames")
check(P("spl, spl, @SPL")[0] == [("user", "spl")], "repeats dropped")
check(P("https://youtube.com/@x") == ([], ["https://youtube.com/@x"]), "links to other sites rejected")
check(len(P(",".join("user%02d" % i for i in range(50)))[0]) == 30, "at most 30 channels at a time")
check(all(core.normalize_username(c["username"]) == c["username"] and c["name"] and c["about"]
          for c in core.SUGGESTED_CHANNELS), "suggested channels are well-formed")
check(len(set(c["username"] for c in core.SUGGESTED_CHANNELS)) == len(core.SUGGESTED_CHANNELS),
      "no suggested channel listed twice")

# --------------------------------------------------------------------------- share links
src = Sources()
tt = src.tiktok
check(tt.link_owner("https://vt.tiktok.com/ZSspl01/") == "spl", "vt.tiktok.com share link -> channel")
check(world.hits.get("short_link") == 1, "one request for a share link (HEAD as a link-preview robot)")
check(tt.link_owner("https://vm.tiktok.com/ZMold433/") == "433", "old vm.tiktok.com link -> clip page -> channel")
check(tt.link_owner("https://www.tiktok.com/t/ZTbr/") == "brfootball", "tiktok.com/t/ link whose server refuses HEAD")
check(tt.link_owner("https://www.tiktok.com/@_/video/%s" % sample_data._vid("spl", 1)) == "spl",
      "video link without a username -> clip page -> channel")
check(tt.link_owner("vt.tiktok.com/ZSchain") == "spl", "share link that redirects to another share link")
check(fails(tt.link_owner, "https://vt.tiktok.com/ZSnope/"), "unknown share code reported")
check(fails(tt.link_owner, "https://vt.tiktok.com/ZShome/"), "share link to TikTok's home page reported")
world.tiktok_page = "blocked"
world.tikwm = "ok"
check(src.link_owner("https://vm.tiktok.com/ZMold433/") == "433", "TikWM looks the link up when TikTok's pages refuse the box")
world.reset()

# --------------------------------------------------------------------------- TV: GREEN = add screen
session, store, ch = manager("tv", ["kayfa1x_2", "laliga", "championsleague"])
ch["actions"].actions["green"]()
add = session.dialogs[-1]
check(isinstance(add, AddChannelScreen) and add.unskinned == [], "GREEN opens the add screen")
rows = add["list"].list
tags = [r[1][1]["text"] for r in rows]
names = [r[2][1]["text"] for r in rows]
fresh = [c["username"] for c in core.SUGGESTED_CHANNELS if not store.get(c["username"])]
check(tags[0] == "TYPE" and rows[0][0] == ("type", None), "first row: type a name or paste a link")
check(tags[1] == "ALL" and rows[1][0] == ("users", fresh) and names[1] == "Add all %d suggested channels" % len(fresh),
      "second row adds every suggestion not in the list")
check(tags.count("+") == len(fresh) and tags.count("ADDED") == 3 and rows[-1][0] is None,
      "suggestions first, the ones already in the list last")
check(ch.page.url in add["subtitle"].getText(), "phone page address on the add screen")
add["list"].moveToIndex(len(rows) - 1)
add["actions"].actions["ok"]()
check(not add.closed, "a channel already in the list can't be picked")
add["list"].moveToIndex(fresh.index("spl") + 2)
add["actions"].actions["ok"]()
settle(lambda: store.get("spl") is not None and not ch.checking, 20)
check(store.get("spl")["name"] == "دوري روشن السعودي" and store.get("spl")["sec_uid"],
      "suggestion verified on TikTok and added with its real name")
check(ch["status"].getText().startswith("Added @spl - "), "TV status confirms the new channel")

ch["actions"].actions["green"]()
add = session.dialogs[-1]
check([r[0] for r in add["list"].list].count(("users", ["spl"])) == 0, "added suggestion moves to the end")
add["list"].moveToIndex(0)
add["actions"].actions["ok"]()
kb = session.dialogs[-1]
check(type(kb).__name__ == "VirtualKeyBoard" and "separate with commas" in kb.title, "TYPE opens the keyboard")
kb.callback("https://vm.tiktok.com/ZMold433/")
settle(lambda: not ch.checking, 20)
check(store.get("433") is not None and "Added @433" in ch["status"].getText(), "share link typed on the TV adds its channel")

ch._entered("brfootball, ghost_user, https://vt.tiktok.com/ZSnope/, Premier League, laliga")
check(ch.checking and "Checking 3 channels" in ch.last_status, "several channels checked one after another")
settle(lambda: not ch.checking, 30)
box = session.dialogs[-1]
check(type(box).__name__ == "MessageBox" and box.type == box.TYPE_YESNO, "one summary for several channels")
for part in ("Added 1: @brfootball", "Already in your list: @laliga", "Couldn't verify: @ghost_user",
             "Couldn't read: vt.tiktok.com/ZSnope/", "Not a username or link: 'Premier League'",
             "Add the channels that couldn't be verified anyway?"):
    check(part in box.text, "summary: " + part)
box.callback(True)
check(store.get("ghost_user") is not None and store.get("brfootball")["name"] == "B/R Football",
      "YES adds the unverified channel too")
ch._entered("https://vt.tiktok.com/ZShome/")
settle(lambda: not ch.checking, 20)
check("Couldn't find the channel behind vt.tiktok.com/ZShome/" in session.dialogs[-1].text, "unreadable link explained")
ch["actions"].actions["cancel"]()

# --------------------------------------------------------------------------- phone page
session, store, ch = manager("web", ["kayfa1x_2"])
base = "http://127.0.0.1:%d" % ch.page.port
page = requests.get(base + "/").text
suggested = [c["username"] for c in core.SUGGESTED_CHANNELS if c["username"] != "kayfa1x_2"]
check("Suggested: match summaries and highlights" in page and "<textarea" in page, "page offers suggestions and a text box")
m = re.search(r'name="user" value="([^"]+)"><button class="minor">Add all (\d+)</button>', page)
check(m and m.group(1).split(",") == suggested and m.group(2) == str(len(suggested)), "'Add all' sends every suggestion")
requests.post(base + "/add", data={"user": m.group(1)})
settle(lambda: not ch.checking, 60)
page = requests.get(base + "/").text
check(all(store.get(u) for u in suggested if u != "fifaworldcup") and store.get("fifaworldcup") is None,
      "suggested channels verified and added from the phone")
check("Added %d: @spl" % (len(suggested) - 1) in page and "Couldn&#x27;t verify: @fifaworldcup" in page
      and "Add @fifaworldcup anyway" in page, "page summary with 'add anyway' for the one that failed")
check("Suggested: match summaries" in page and page.count('class="go">Add</button>') == 1,
      "only the unverified suggestion is still offered")
requests.post(base + "/add", data={"user": "fifaworldcup", "force": "1"})
settle(lambda: store.get("fifaworldcup") is not None)
page = requests.get(base + "/").text
check("Suggested:" not in page and "anyway" not in page, "nothing left to suggest")

store.remove("433")
store.remove("brfootball")
pasted = ("Check out this goal! #TikTok https://vt.tiktok.com/ZSspl01/\n"
          "https://www.tiktok.com/t/ZTbr/\n433, ghost_two\nthat was fun")
requests.post(base + "/add", data={"user": pasted})
settle(lambda: not ch.checking, 30)
page = requests.get(base + "/").text
check(store.get("433") and store.get("brfootball") and store.get("ghost_two") is None, "pasted links and names added")
check("Added 2: @brfootball, @433" in page and "Already in your list: @spl" in page
      and "Add @ghost_two anyway" in page and "Not a username or link: &#x27;that was fun&#x27;" in page,
      "pasted text summarised on the page")
check(ch.changed, "feed reloads after the manager closes")
ch["actions"].actions["cancel"]()

print("All %d channel checks passed." % len(passed))
