"""End-to-end checks: a simulated Enigma2 session talking to a fake internet.

Usage: python3 tests/test_all.py [out_dir]      (FAKE_DESKTOP=1280 for the HD skin)
"""
import json
import os
import re
import sys
import time
import xml.etree.ElementTree as ET

import harness
from harness import FakeSession, fire, settle

OUT = sys.argv[1] if len(sys.argv) > 1 else harness.TMP
HD = os.environ.get("FAKE_DESKTOP") == "1280"
world = harness.install()

import requests  # noqa: E402
from enigma import iPlayableService, iServiceInformation  # noqa: E402
from SimplyScores import api_scores, core, diagnose, gui, net, src_tikwm, src_tiktok  # noqa: E402
from SimplyScores import VERSION, plugin  # noqa: E402  (defines config.plugins.simplyscores)
from SimplyScores.feed import FeedManager  # noqa: E402
from SimplyScores.proxy import StreamProxy  # noqa: E402
from SimplyScores.sources import Sources  # noqa: E402
from SimplyScores.ui_feed import SimplyScoresFeed  # noqa: E402
from SimplyScores.ui_manage import ChannelsScreen, DiagnoseScreen, LibraryScreen, SettingsScreen  # noqa: E402
import fake_net  # noqa: E402
import render_preview  # noqa: E402
import sample_data  # noqa: E402

passed = []


def check(cond, label):
    assert cond, "FAILED: " + label
    passed.append(label)


def expect_error(fn, *args):
    try:
        fn(*args)
    except net.SourceError as e:
        return e
    raise AssertionError("FAILED: expected SourceError from %s" % fn)


# --------------------------------------------------------------------------- skins
for name in ("FEED_SKIN", "CHANNELS_SKIN", "ADD_SKIN", "LIBRARY_SKIN", "SETTINGS_SKIN", "DIAG_SKIN"):
    root = ET.fromstring(getattr(gui, name))
    check(root.tag == "screen", "%s parses as XML" % name)
    for el in root.iter():
        for attr in ("position", "size"):
            v = el.get(attr)
            if v and v != "center,center":
                a, b = v.split(",")
                check(int(a) >= 0 and int(b) >= 0, "%s %s non-negative" % (name, attr))
    w = int(root.get("size").split(",")[0])
    check(w == (1280 if HD else 1920) or name != "FEED_SKIN", "%s sized for desktop" % name)
    for el in root.iter():
        p = el.get("pixmap")
        if p:
            check(os.path.exists(p), "icon exists: " + os.path.basename(p))

if not HD:
    # ----------------------------------------------------------------------- store
    store = core.ChannelStore(os.path.join(harness.TMP, "store_test.json"))
    check(len(store.channels) == 5 and store.usernames()[0] == "kayfa1x_2", "default channels written")
    check(store.add("@Some.User") and not store.add("some.user"), "add + duplicate rejected")
    check(store.toggle("some.user") and "some.user" not in store.usernames(), "toggle off")
    check(store.move("some.user", -1) and store.index("some.user") == 4, "move up")
    check(store.rename("some.user", "Some 🔥 User") and store.get("some.user")["name"] == "Some User", "rename cleans emoji")
    check(store.set_sec_uid("some.user", fake_net.sec_uid("x")) and not store.set_sec_uid("some.user", "junk"),
          "secUid stored, junk rejected")
    check(core.ChannelStore(store.path).get("some.user")["sec_uid"] == fake_net.sec_uid("x"), "secUid survives reload")
    check(store.remove("some.user") and store.get("some.user") is None, "remove")
    legacy = os.path.join(harness.TMP, "legacy.json")
    with open(legacy, "w") as f:
        json.dump({"player_service_id": 5002, "tiktok_channels": [{"name": "K", "username": "@kayfa1x_2"}, "laliga", {"username": "bad name"}],
                   "score_leagues": [{"name": "UCL", "code": "uefa.champions"}]}, f)
    old = core.ChannelStore(legacy)
    check([c["username"] for c in old.channels] == ["kayfa1x_2", "laliga"], "plan-format JSON accepted")
    old.save()
    check(json.load(open(legacy))["player_service_id"] == 5002, "unknown keys preserved on save")
    with open(legacy, "w") as f:
        f.write("{broken")
    check(len(core.ChannelStore(legacy).channels) == 5 and os.path.exists(legacy + ".broken"), "broken JSON backed up")
    check(core.chrome_major(1792540800) == 151 and "Chrome/" in core.browser_ua() and ".0.0.0 " in core.browser_ua(),
          "User-Agent claims a current Chrome")

    # ----------------------------------------------------------------------- TikWM
    tikwm = src_tikwm.TikWM()
    e = expect_error(tikwm.user_posts, {"username": "kayfa1x_2"}, 20)
    check(e.blocked and "Cloudflare challenge" in str(e), "TikWM 403 recognised as a Cloudflare challenge")
    check(world.hits.get("tikwm_api") == 4, "all 4 TikWM request styles tried")
    world.tikwm, world.hits = "apex_get_only", {}
    vids, _ = tikwm.user_posts({"username": "kayfa1x_2"}, 20)
    check(len(vids) == 7 and tikwm.style == 2, "TikWM switches to the style that works (7 of 8 posts kept)")
    check(vids[0]["streams"][0][0].startswith(world.base + "/twa/video/media/play/"), "relative links made absolute on the working host")
    check([v["created"] for v in vids] == sorted([v["created"] for v in vids], reverse=True), "pinned post re-sorted by date")
    check(vids[0]["tags"] == ["#الكلاسيكو", "#ريال_مدريد", "#برشلونة"] and "🔥" not in vids[0]["title"], "caption split + emoji removed")
    world.hits = {}
    tikwm.user_posts({"username": "laliga"}, 20)
    check(world.hits.get("tikwm_api") == 1, "working TikWM style remembered")
    world.tikwm = "ok"
    e = expect_error(tikwm.user_posts, {"username": "ghost_user"}, 5)
    check(e.final and "parsing" in str(e), "unknown TikWM user is a final answer")

    # ----------------------------------------------------------------------- TikTok direct
    world.tiktok_page = "challenge"
    tt = src_tiktok.TikTokWeb()
    prof = tt.profile("kayfa1x_2")
    check(prof["sec_uid"] == fake_net.sec_uid("kayfa1x_2") and tt.solved == 1, "bot check solved, secUid read from the profile")
    check(tt.session().cookie("tt_chain_token") == fake_net.TOKEN, "TikTok session keeps its cookie")
    check(tt.session().cookie("_wafchallengeid") is None, "one-time challenge cookie removed")
    vids, found = tt.user_posts({"username": "kayfa1x_2", "sec_uid": ""}, 20)
    check(len(vids) == 7 and found == fake_net.sec_uid("kayfa1x_2"), "TikTok list: photo post skipped, secUid reported")
    check(vids[0]["title"].startswith("ملخص مباراة ريال مدريد") and vids[0]["likes"] == 98400, "TikTok post parsed")
    plan = [s[0] for s in src_tiktok.order_streams(vids[0]["streams"], False)]
    check("c=h264_720&" in plan[0] + "&" and "c=h264_720b" in plan[1] and "c=h264_540" in plan[2], "H.264 links first, best fitting size first")
    check("c=hevc" in plan[-2] and "c=dl" in plan[-1], "HEVC after H.264, watermarked link last")
    check(not any("www.tiktok.com" in u or "c=vvc" in u for u in plan), "broken and undecodable links dropped")
    world.no_sec_uid = {"laliga"}
    vids2, found2 = src_tiktok.TikTokWeb().user_posts({"username": "laliga"}, 10)
    check(found2 == fake_net.sec_uid("laliga") and len(vids2) == 3, "secUid found through the embed page when the profile lacks it")
    world.no_sec_uid = set()
    world.tiktok_api = "empty"
    e = expect_error(tt.item_list, "kayfa1x_2", fake_net.sec_uid("kayfa1x_2"), 5)
    check(e.blocked and "empty" in str(e), "empty TikTok reply reported as refused")
    world.tiktok_api = "ok"
    e = expect_error(tt.profile, "ghost_user")
    check(e.final and "not found" in str(e), "unknown TikTok account is a final answer")

    # ----------------------------------------------------------------------- source switching
    world.tikwm, world.hits = "blocked", {}
    src = Sources()
    videos, name, sec = src.fetch_channel({"username": "kayfa1x_2", "sec_uid": ""}, 20)
    check(name == "tiktok" and src.preferred == "tiktok" and sec == fake_net.sec_uid("kayfa1x_2"), "TikWM blocked -> TikTok direct used")
    check(src.skip_until.get("tikwm", 0) > time.time(), "blocked TikWM put on cooldown")
    world.hits = {}
    src.fetch_channel({"username": "laliga", "sec_uid": fake_net.sec_uid("laliga")}, 10)
    check(not world.hits.get("tikwm_api") and not world.hits.get("tiktok_page"), "cooldown + cached secUid: one API call only")
    world.hits = {}
    resp, err = src.open_stream(videos[0], False, "bytes=0-99")
    check(resp is not None and resp.status_code == 206 and resp.content[4:8] == b"ftyp"
          and videos[0]["links_from"] == "page", "video-list links refused -> clip-page links play")
    resp.close()
    check(world.hits.get("cdn_refused") == 2 and not world.hits.get("clip_page_refused"),
          "only 2 list links tried; clip page loaded with the User-Agent it accepts")
    check(src.tiktok.page_bare and not src.needs_links(videos[0]), "prepared clip needs no new links")
    a, b = videos[1], videos[2]
    check(src.needs_links(a) and src.prepare(a)[0] and src.prepare(b)[0], "links prepared ahead for two clips")
    world.hits = {}
    for clip in (a, b):
        resp, err = src.open_stream(clip, False, "bytes=0-99")
        check(resp is not None and resp.status_code == 206, "clip %s plays with its own session" % clip["id"])
        resp.close()
    check(world.hits.get("cdn") == 2 and not world.hits.get("clip_page"),
          "each prepared clip opens on the first try (tokens rotate per page load)")
    world.expired = {"c=h264_720&"}
    a.pop("good", None)
    resp, err = src.open_stream(a, False, "bytes=0-99")
    check(resp is not None and "c=h264_720b" in a["good"], "expired link skipped, next link used")
    resp.close()
    old_token = re.search(r"tk=(\w+)", a["streams"][0][0]).group(1)
    world.expired = {"tk=%s&" % old_token}
    a.pop("good", None)
    resp, err = src.open_stream(a, False, "bytes=0-99")
    check(resp is not None and old_token not in a["good"], "all links expired -> fresh links from the clip's page")
    resp.close()
    world.expired = set()
    hevc = videos[3]
    world.hevc_only = {hevc["id"]}
    check(src.prepare(hevc)[0] and all(s_[1] == "h265" for s_ in hevc["streams"]), "H.265-only clip prepared")
    resp, err = src.open_stream(hevc, False, "bytes=0-9")
    check(resp is not None and src.served[hevc["id"]][1] == "h265", "H.265 link used when a clip has nothing else")
    resp.close()
    src.h264_only = True
    resp, err = src.open_stream(hevc, False, "bytes=0-9")
    check(resp is None and "no H.264 link" in err, "H.264-only mode refuses H.265-only clips")
    src.h264_only = False
    world.hevc_only = set()
    world.list_links_work = True
    lst = src.fetch_channel({"username": "laliga", "sec_uid": fake_net.sec_uid("laliga")}, 10)[0]
    world.hits = {}
    resp, err = src.open_stream(lst[0], False, "bytes=0-9")
    check(resp is not None and lst[0]["links_from"] == "list" and not world.hits.get("clip_page"),
          "list links are used directly where TikTok accepts them")
    resp.close()
    world.list_links_work = False
    world.tiktok_page = "blocked"
    e = expect_error(Sources().fetch_channel, {"username": "premierleague", "sec_uid": ""}, 10)
    check("TikWM: HTTP 403 Cloudflare challenge" in str(e) and "TikTok: HTTP 403" in str(e), "both refusals reported: %s" % e)
    world.tiktok_page = "challenge"
    mode = {"value": "tikwm"}
    only = Sources(mode=lambda: mode["value"])
    e = expect_error(only.fetch_channel, {"username": "kayfa1x_2"}, 5)
    check("TikTok" not in str(e), "'TikWM only' setting never uses TikTok")

    # ----------------------------------------------------------------------- relay
    relay = StreamProxy(src)
    url = relay.url(videos[1], False)
    r = requests.get(url, headers={"Range": "bytes=10-109"})
    check(r.status_code == 206 and r.content == fake_net.MP4[10:110]
          and r.headers["Content-Range"] == "bytes 10-109/%d" % len(fake_net.MP4), "relay passes Range requests through")
    r = requests.get(url)
    check(r.status_code == 200 and r.content == fake_net.MP4, "relay streams the whole clip")
    check(requests.get("http://127.0.0.1:%d/play/nope.mp4" % relay.port).status_code == 404, "relay 404 for unknown clips")
    world.tikwm = "ok"
    tw = src_tikwm.TikWM().user_posts({"username": "laliga"}, 5)[0]
    r = requests.get(relay.url(tw[0], False), headers={"Range": "bytes=0-15"})
    check(r.status_code == 206 and tw[0]["src"] == "tikwm", "TikWM clip plays through its redirecting link")
    world.tikwm = "blocked"
    tw[0].pop("good", None)
    r = requests.get(relay.url(tw[0], False), headers={"Range": "bytes=0-15"})
    check(r.status_code == 206 and tw[0]["src"] == "tiktok", "TikWM clip rescued via TikTok when TikWM's links are blocked")
    world.tiktok_page = "blocked"
    gone = dict(videos[2], streams=[], good=None)
    r = requests.get(relay.url(gone, False))
    check(r.status_code == 502 and "HTTP 403" in relay.error(gone["id"]), "relay reports why a clip can't play")
    world.tiktok_page = "challenge"
    relay.stop()

    # ----------------------------------------------------------------------- connection test
    lines = diagnose.run(src, "kayfa1x_2", "uefa.champions", lambda line: None, "test")
    text = "\n".join(lines)
    check("[FAIL] TikWM, POST www.tikwm.com" in text and "Cloudflare challenge" in text, "test shows TikWM refusals")
    check("[ OK ] ESPN scores" in text and "[ OK ] TikTok profile" in text and "[ OK ] TikTok video list: 7 videos" in text and "1.5M followers" in text,
          "test shows TikTok working")
    check("[ OK ] Video stream: HTTP 206" in text and "TikTok direct works" in text, "test streams a clip and gives a verdict")
    check("[INFO] Link from the video list: HTTP 403" in text and "[ OK ] Clip page links: h264 720p" in text,
          "test compares list links with clip-page links")
    check("Activity log (latest):" in text and "ready in" in text, "test includes the activity log")
    check(os.path.exists(diagnose.report_path()) and "Request log:" in open(diagnose.report_path()).read(), "report saved")

    league, matches = api_scores.parse_scoreboard(sample_data.espn(""))
    check(league == "UEFA Champions League" and matches[0]["state"] == "in", "live match sorted first")
    rm = [m for m in matches if m["home"] == "Real Madrid"][0]
    check(api_scores.scorers_text(rm) == ("Mbappé 23', Vinícius Jr. 78'", "Vlahović 40'"), "scorers grouped by side")

    fm = FeedManager(os.path.join(harness.TMP, "fm"))
    v, err, meta = fm.fetch({"username": "kayfa1x_2", "sec_uid": ""}, 20, src)
    fm.apply("kayfa1x_2", v, err, meta)
    fm2 = FeedManager(os.path.join(harness.TMP, "fm"))
    fm2.load_cache(["kayfa1x_2"])
    check(len(fm2.videos["kayfa1x_2"]) == 7 and fm2.source["kayfa1x_2"] == "tiktok", "cache keeps videos and source")

# --------------------------------------------------------------------------- plugin + feed UI
world.reset()                       # TikWM blocked by "Cloudflare", TikTok shows its bot check
descs = plugin.Plugins()
icon = "plugin.png" if HD else "plugin_fhd.png"
check(len(descs) == 2 and descs[0].icon == icon, "plugin descriptors, %s for this skin" % icon)
from PIL import Image  # noqa: E402
check(Image.open(os.path.join(core.PLUGIN_DIR, icon)).size == ((100, 40) if HD else (150, 60)),
      "menu icon fits the plugin browser's icon box")
cfg = plugin.config.plugins.simplyscores
session = FakeSession()
scr = session.open(SimplyScoresFeed)
check(scr.unskinned == [], "every feed component is in the skin")
check(scr["center_msg"].visible and "Loading" in scr["center_msg"].getText(), "first run shows loading message")
settle(lambda: not scr.refreshing and not scr.score_loading, 60)
check(len(scr.clips) == 5 + 3 + 2 + 2 + 1, "For You merges all channels (age-filtered)")
check(scr.clips[0]["user"] == "kayfa1x_2" and scr.index == 0, "newest clip first")
check("via TikTok direct" in scr["status"].getText(), "status names the source in use")
check(scr.store.get("laliga")["sec_uid"] == fake_net.sec_uid("laliga"), "secUid cached in the channel list")
check(fire(scr.playTimer), "play scheduled")
check(scr.pending_links == scr.clips[0]["id"] and session.nav.ref is None, "player waits for the clip's links")
settle(lambda: scr.pending_links is None, 30)
ref = session.nav.ref
check(ref.type == 4097 and ref.path == "http://127.0.0.1:%d/play/%s.mp4" % (scr.proxy.port, scr.clips[0]["id"]),
      "player gets the local relay link")
r = requests.get(ref.path, headers={"Range": "bytes=0-63"})
check(r.status_code == 206 and b"ftyp" in r.content, "relay link plays like the player would fetch it")
session.nav.service.pos = 90000
fire(scr.tickTimer)
check(not scr.waiting and not scr["cover"].visible and scr["progress"].value > 0, "playback detected, cover hidden")
check(scr["caption"].instance.halign == 2, "Arabic caption right-aligned")
settle(lambda: not scr.images.pending, 20)
fire(scr.imageTimer)
check(len(scr["upnext"].list) == 2 and any(c[0] == "pix" for c in scr["upnext"].list[0][1:]), "up-next list with thumbnails")
check(scr["avatar"].instance.pixmap and "/img/" in scr["avatar"].instance.pixmap[1], "channel avatar loaded")
check(len(scr["score_list"].list) == 6 and "page 1/2" in scr["score_page"].getText(), "scores panel paged")
size = (1280, 720) if HD else (1920, 1080)
render_preview.render(scr, os.path.join(OUT, "preview_%s.png" % ("hd" if HD else "fhd")), size=size)
frame = os.path.join(harness.TMP, "frame.jpg")
open(frame, "wb").write(sample_data.image_bytes("https://www.tikwm.com/video/cover/x.webp"))
render_preview.render(scr, os.path.join(OUT, "preview_%s_video.png" % ("hd" if HD else "fhd")), video=frame, size=size)

if HD:
    scr["actions"].actions["cancel"]()
    print("HD checks passed:", len(passed))
    sys.exit(0)

acts = scr["actions"].actions
ev = scr._eventmap


def play():
    """Fire the play timer and wait until the clip is handed to the player."""
    fire(scr.playTimer)
    settle(lambda: scr.pending_links is None, 30)


settle(lambda: not scr.resolver.queue and scr.resolver.active is None, 30)
check(not scr.sources.needs_links(scr.clips[1]) and not scr.sources.needs_links(scr.clips[2]),
      "the next two clips got their links in the background")
acts["down"]()
check(scr.index == 1 and scr.playTimer.timer.active and session.nav.ref is None, "DOWN = next clip (old stopped)")
fire(scr.playTimer)
check(scr.pending_links is None and session.nav.ref.path.endswith("/play/%s.mp4" % scr.clips[1]["id"]),
      "prefetched clip starts at once")
acts["up"]()
play()
check(scr.index == 0, "UP = previous clip")
acts["up"]()
check("Checking" in scr["center_msg"].getText(), "UP at the top checks for new videos")
settle(lambda: not scr.refreshing)
acts["right"]()
check(scr.tabs[scr.tab][0] == "kayfa1x_2" and all(v["user"] == "kayfa1x_2" for v in scr.clips), "RIGHT = channel tab")
acts["left"]()
check(scr.tab == 0, "LEFT = back to For You")
play()
session.nav.service.pos = 90000
fire(scr.tickTimer)
acts["info"]()
check(not scr["card_post"].visible and not scr["like_icon"].visible and scr["progress"].visible, "INFO = clean view")
acts["info"]()
check(scr["card_post"].visible, "INFO again restores panels")
acts["ok"]()
check(session.nav.service.paused and scr["pause_icon"].visible, "OK pauses")
acts["ok"]()
check(not session.nav.service.paused and not scr["pause_icon"].visible, "OK resumes")
acts["seekFwd"]()
check(session.nav.service.pos == 90000 + 10 * 90000, "FF seeks +10 s")
session.nav.service.w, session.nav.service.h = 1920, 1080
ev[iPlayableService.evVideoSizeChanged]()
check(not scr["card_post"].visible and not scr["avatar"].visible, "landscape clip hides side panels")
scr.started -= 5
i0 = scr.index
ev[iPlayableService.evEOF]()
check(scr.index == i0 + 1 and scr["card_post"].visible, "EOF auto-advances, panels back")
play()
playing = scr.playing
scr.proxy.errors[playing] = "cdn.example: HTTP 403; fresh link: HTTP 403"
ev[iPlayableService.evUser + 12]()
check(scr.skipTimer.timer.active and "skipping" in scr["center_msg"].getText(), "play error schedules a skip")
check("Can't play: cdn.example: HTTP 403" in scr["status"].getText(), "play error shows the link problem")
fire(scr.skipTimer)
check(scr.index == i0 + 2, "skipped to the following clip")
play()
session.nav.service.strings = {iServiceInformation.sUser + 12: "Internal data stream error"}
ev[iPlayableService.evUser + 12]()
check("Can't play: Internal data stream error" in scr["status"].getText(), "player's own error message shown")
fire(scr.skipTimer)
play()
vid = scr.playing
scr.sources.served[vid] = ["http://cdn.example/x.mp4", "h265", 1080, 1920, 0, ""]
session.nav.service.strings = {iServiceInformation.sTagVideoCodec: "H.265/HEVC"}
idx = scr.index
ev[iPlayableService.evUser + 11]()
check(scr.sources.h264_only and scr.index == idx and scr.playTimer.timer.active,
      "H.265 decode error -> H.264 links only, same clip retried")
check("H.264" in scr["status"].getText(), "status explains the codec switch")
play()
check(session.nav.ref.path.endswith("/play/%s.mp4" % vid), "clip replayed")
scr.sources.h264_only = False

acts["green"]()
settle(lambda: not scr.score_loading)
check(cfg.league_index.value == 1 and scr["score_title"].getText() == "UEFA Europa League", "GREEN = next league")
check(scr["credit"].getText() == "SimplyScores v%s · by reali22" % VERSION, "version and author before the clock")
fire(scr.pageTimer)

acts["yellow"]()
lib = session.dialogs[-1]
check(isinstance(lib, LibraryScreen) and len(lib["list"].list) == len(scr.clips), "YELLOW = video list")
lib["list"].moveToIndex(4)
lib["actions"].actions["ok"]()
check(scr.index == 4 and scr.playTimer.timer.active, "jump from video list")
play()

acts["blue"]()
ch = session.dialogs[-1]
check(isinstance(ch, ChannelsScreen) and len(ch["list"].list) == 5, "BLUE = channel manager")
check("via TikTok" in ch["list"].list[0][-1][1]["text"], "channel rows show the source")
ch._entered("bad name!")
check(type(session.dialogs[-1]).__name__ == "MessageBox", "invalid username rejected")
ch._entered("https://www.tiktok.com/@NewChan?lang=en")
settle(lambda: not ch.checking)
check(ch.store.get("newchan") and ch.store.get("newchan")["name"] == "New Channel", "channel verified and added while TikWM is blocked")
check(ch.store.get("newchan")["sec_uid"] == fake_net.sec_uid("newchan"), "new channel's secUid stored")
check("1.5M followers (checked via TikTok)" in ch["status"].getText(), "status shows followers and source")
ch._entered("ghost_user")
settle(lambda: not ch.checking)
box = session.dialogs[-1]
check("Couldn't verify" in box.text and "not found" in box.text, "unknown channel asks before adding")
box.callback(False)
check(ch.store.get("ghost_user") is None, "declined unknown channel not added")
ch["list"].moveToIndex(ch.store.index("newchan"))
ch["actions"].actions["blue"]()
check(ch.store.index("newchan") == 4, "BLUE moves channel up")
ch._renamed("newchan", "Fresh Goals")
render_preview.render(ch, os.path.join(OUT, "preview_channels.png"), backdrop=(30, 30, 30, 255))
ch["list"].moveToIndex(ch.store.index("cbssportsgolazo"))
ch["actions"].actions["ok"]()
check(not ch.store.get("cbssportsgolazo")["enabled"], "OK switches a channel off")
ch._removeConfirmed(True, "premierleague")
check(ch.store.get("premierleague") is None, "channel removed")
ch["actions"].actions["cancel"]()
check("Fresh Goals" in [t[1] for t in scr.tabs] and "Premier League" not in [t[1] for t in scr.tabs], "tabs rebuilt after edits")
settle(lambda: not scr.refreshing)
check(any(v["user"] == "newchan" for v in scr.clips), "new channel's videos in For You")
check(not any(v["user"] in ("premierleague", "cbssportsgolazo") for v in scr.clips), "removed/disabled channels gone")
saved = json.load(open(core.CONFIG_PATH))
check([c["username"] for c in saved["tiktok_channels"]][-1] == "cbssportsgolazo", "channel list saved to JSON")

acts["menu"]()
menu = session.dialogs[-1]
check(type(menu).__name__ == "PluginMenu" and [r[0] for r in menu["list"].list] == ["settings", "update", "test", "about"],
      "MENU = plugin menu: settings, update, connection test, about")
menu["list"].moveToIndex(0)
menu["actions"].actions["ok"]()
st = session.dialogs[-1]
check(isinstance(st, SettingsScreen) and len(st["config"].list) == 14 and st["config"].list[0][1] is cfg.source,
      "menu > settings, video source first")
st["setup_actions"].actions["yellow"]()
diag = session.dialogs[-1]
check(isinstance(diag, DiagnoseScreen) and diag.unskinned == [], "YELLOW opens the connection test")
settle(lambda: not diag.running, 60)
check("Result: TikWM refuses this box, but TikTok direct works" in diag["text"].getText(), "connection test verdict on screen")
check(diagnose.report_path() in diag["hint"].getText(), "report location shown")
render_preview.render(diag, os.path.join(OUT, "preview_diagnose.png"), backdrop=(30, 30, 30, 255))
diag["actions"].actions["cancel"]()
cfg.max_age.value = "1"
cfg.player.value = "5002"
cfg.source.value = "tiktok"
st["setup_actions"].actions["green"]()
check(all(time.time() - v["created"] < 86400 for v in scr.clips), "age setting applied")
check(scr.refreshing and "source changed" in scr["center_msg"].getText(), "changing the source reloads the feed")
settle(lambda: not scr.refreshing)
play()
check(session.nav.ref.type == 5002, "player setting applied (exteplayer3)")
check(session.nav.ref.path.endswith(".mp4") and cfg.audio.value == "fix", "default: sound fixed inside the relay")
cfg.audio.value = "convert"
scr.schedulePlay(0)
play()
check(session.nav.ref.path.endswith(".ts") and scr.converting, "'Sound: convert with ffmpeg' plays the converted stream")
scr.proxy.convert_failed = "ffmpeg: Unknown encoder 'mp2'"
ev[iPlayableService.evUser + 12]()
check("Audio conversion failed" in scr["status"].getText() and scr.playTimer.timer.active,
      "failed conversion reported, clip retried")
play()
check(session.nav.ref.path.endswith(".mp4") and not scr.converting, "retried without conversion")
cfg.audio.value = "fix"
check(any("ready in" in line for line in core.playlog_tail(80)) and any("playing after" in line for line in core.playlog_tail(80)),
      "playback log records links and playback")

acts["cancel"]()
check(scr.closed and session.nav.ref == "LIVE-TV", "EXIT restores live TV")
saved = json.load(open(core.CONFIG_PATH))
check(saved["last_visit"] > 0 and saved["net"]["source"] == "tiktok", "last visit and working source stored")

# second visit: instant start from cache, nothing is NEW any more
session2 = FakeSession()
cfg.max_age.value = "7"
cfg.source.value = "auto"
scr2 = session2.open(SimplyScoresFeed)
check(len(scr2.clips) > 0 and not scr2.refreshing, "second visit loads from cache instantly")
check(scr2.sources.preferred == "tiktok", "second visit starts with the source that worked")
check(not scr2["badge"].visible and "new" not in scr2["position"].getText(), "no NEW badges for seen uploads")
scr2["actions"].actions["cancel"]()

print("All %d checks passed." % len(passed))
