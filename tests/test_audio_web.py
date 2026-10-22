"""Sound fix, ffmpeg conversion, channel web page and keyboard handling.

Usage: python3 tests/test_audio_web.py
"""
import os
import subprocess

import harness
from harness import FakeSession, settle

world = harness.install()

import requests  # noqa: E402
from SimplyScores import audiofix, core, diagnose, transcode  # noqa: E402
from SimplyScores import plugin  # noqa: E402,F401  (defines config.plugins.simplyscores)
assert plugin
from SimplyScores.feed import FeedManager  # noqa: E402
from SimplyScores.proxy import StreamProxy  # noqa: E402
from SimplyScores.sources import Sources  # noqa: E402
from SimplyScores.ui_manage import ChannelsScreen, keyboard_text  # noqa: E402

passed = []


def check(cond, label):
    assert cond, "FAILED: " + label
    passed.append(label)


# --------------------------------------------------------------------------- test media
work = os.path.join(harness.TMP, "media")
os.makedirs(work, exist_ok=True)
fast, slow = os.path.join(work, "fast.mp4"), os.path.join(work, "slow.mp4")
subprocess.check_call(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc=size=576x1024:rate=25:duration=3",
                       "-f", "lavfi", "-i", "sine=frequency=440:duration=3", "-c:v", "libx264", "-preset", "ultrafast",
                       "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "64k", "-movflags", "+faststart", fast])
subprocess.check_call(["ffmpeg", "-v", "error", "-y", "-i", fast, "-c", "copy", slow])
HE_V2 = bytes.fromhex("eb8a0800")        # AOT 29 (HE-AACv2), core 22050 Hz mono, SBR to 44100 Hz


def he_aac(path):
    """The file with its audio header turned into explicit HE-AACv2 (same length)."""
    data = bytearray(open(path, "rb").read())
    info = audiofix.probe(lambda a, b: bytes(data[a:b + 1]))
    offset, asc = info["audio"]["dsi"]
    new = HE_V2 + b"\x00" * (len(asc) - len(HE_V2))
    data[offset:offset + len(asc)] = new
    return bytes(data), offset, len(asc)


plain_fast = open(fast, "rb").read()
he_fast, he_off, he_len = he_aac(fast)
he_slow, he_off_slow, _ = he_aac(slow)
world.media.update({"fast.mp4": plain_fast, "he_fast.mp4": he_fast, "he_slow.mp4": he_slow})
LC = bytes.fromhex("1388") + b"\x00" * (he_len - 2)

# --------------------------------------------------------------------------- parsing
info = audiofix.probe(lambda a, b: plain_fast[a:b + 1])
check(info["video"] == {"codec": "avc1", "width": 576, "height": 1024}, "video track read from the MP4 header")
check(info["audio"]["aot"] == 2 and info["audio"]["rate"] == 44100, "AAC-LC sound read from the MP4 header")
info = audiofix.probe(lambda a, b: he_slow[a:b + 1])
check(info and info["audio"]["aot"] == 29 and info["audio"]["out_rate"] == 44100 and info["audio"]["ps"],
      "HE-AACv2 found when the header sits at the end of the file")
check(audiofix.describe_audio(info["audio"]) == "HE-AACv2 (mp4a.40.29), 22050 Hz -> 44100 Hz, mono + PS (stereo)",
      "sound described for the report")
new = audiofix.lc_header(HE_V2)
check(new == bytes.fromhex("13880000"), "HE-AACv2 header rewritten to AAC-LC at the core rate")
h = new
check((((h[0] & 0xC) >> 2) + 1, ((h[0] & 3) << 1) | (h[1] >> 7), (h[1] & 0x78) >> 3) == (1, 7, 1),
      "OpenPLi audio sink now writes an AAC-LC ADTS header (profile 1, 22050 Hz, 1 channel)")
check(((h[0] >> 3) - 1) == 1, "multibox audio sink now writes AAC-LC too")
check(audiofix.lc_header(bytes.fromhex("1210")) is None, "plain AAC-LC is left alone")


def chunks(data, size=7001):
    return [data[i:i + size] for i in range(0, len(data), size)]


fx = audiofix.StreamFixer()
out = b"".join(fx.wrap(chunks(he_fast), 0))
check(len(out) == len(he_fast) and out[he_off:he_off + he_len] == LC
      and out[:he_off] == he_fast[:he_off] and out[he_off + he_len:] == he_fast[he_off + he_len:],
      "streamed clip: only the audio header bytes change")
fx = audiofix.StreamFixer()
out = b"".join(fx.wrap(chunks(he_slow), 0))
check(out[he_off_slow:he_off_slow + he_len] == LC, "header at the end of the file fixed in the same pass")
moov_at = max(b for b in fx.boundaries if b < len(he_slow))
fx2 = audiofix.StreamFixer()
list(fx2.wrap(chunks(he_slow[:moov_at]), 0))                        # player reads the start...
out = b"".join(fx2.wrap(chunks(he_slow[moov_at:]), moov_at))        # ...then asks for the header
check(out[he_off_slow - moov_at:he_off_slow - moov_at + he_len] == LC, "header fixed when fetched with a Range request")
fx3 = audiofix.StreamFixer()
out = b"".join(fx3.wrap(chunks(plain_fast), 0))
check(out == plain_fast and fx3.patch is None, "AAC-LC clips pass through untouched")
check(b"".join(audiofix.StreamFixer().wrap(chunks(b"\x00\x00\x00\x01junk" * 50), 0)) == b"\x00\x00\x00\x01junk" * 50,
      "garbage passes through without errors")

# --------------------------------------------------------------------------- relay
mode = {"value": "fix"}
src = Sources()
relay = StreamProxy(src, audio_mode=lambda: mode["value"])


def clip(vid, name):
    return {"id": vid, "user": "test", "src": "tikwm", "links_from": "tikwm",
            "streams": [[world.base + "/media/" + name, "h264", 576, 1024, 0, ""]]}


v1 = clip("9001", "he_fast.mp4")
body = requests.get(relay.url(v1)).content
check(body[he_off:he_off + he_len] == LC and len(body) == len(he_fast), "relay fixes the header while streaming")
check(relay.media["9001"]["audio"]["aot"] == 29, "relay remembers the clip's sound type")
check(any("audio header fixed" in line for line in core.playlog_tail(20)), "fix written to the activity log")
r = requests.get(relay.url(v1), headers={"Range": "bytes=%d-" % (he_off - 10)})
check(r.status_code == 206 and r.content[10:10 + he_len] == LC, "fix also applied to later Range requests")
mode["value"] = "original"
v2 = clip("9002", "he_fast.mp4")
check(requests.get(relay.url(v2)).content == he_fast, "'Sound: leave as it is' streams the original bytes")
mode["value"] = "fix"

v3 = clip("9003", "fast.mp4")
r = requests.get(relay.url(v3, convert=True), stream=True, timeout=30)
ts = b"".join(r.iter_content(65536))
check(r.status_code == 200 and r.headers["Content-Type"] == "video/mp2t" and ts[:1] == b"\x47"
      and all(ts[i] == 0x47 for i in range(0, 188 * 20, 188)), "ffmpeg conversion streams MPEG-TS")
probe = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "stream=codec_name", "-of", "csv=p=0", "-"],
                       input=ts, stdout=subprocess.PIPE).stdout.decode().split()
check(sorted(set(probe)) == ["h264", "mp2"], "converted stream: H.264 video copied, MP2 sound (%s)" % probe)
saved = transcode._cache.get("path")
transcode._cache["path"] = "/bin/false"
v4 = clip("9004", "fast.mp4")
r = requests.get(relay.url(v4, convert=True), timeout=30)
check(r.status_code == 502 and relay.convert_failed and "ffmpeg" in relay.convert_failed,
      "a broken ffmpeg is reported, not hung on")
transcode._cache["path"] = saved
relay.convert_failed = None
relay.stop()

# --------------------------------------------------------------------------- connection test sound lines
world.clip_bytes = he_fast
lines = diagnose.run(Sources(), "kayfa1x_2", "eng.1", lambda line: None, "test", sound=lambda: "fix")
text = "\n".join(lines)
check("[INFO] Clip format: avc1 576x1024, HE-AACv2 (mp4a.40.29)" in text, "report names the clip's sound type")
check("'Sound: Fix' rewrites its header" in text and "Sound setting: fix TikTok's HE-AAC" in text,
      "report explains the sound fix")
check("[INFO] ffmpeg: ffmpeg version" in text and "[ OK ] Sound conversion with ffmpeg" in text,
      "report tests the ffmpeg conversion")

# --------------------------------------------------------------------------- keyboard + web page
check(keyboard_text(None) is None and keyboard_text([]) == "" and keyboard_text(b"laliga") == "laliga"
      and keyboard_text(["kayfa1x_2"]) == "kayfa1x_2" and keyboard_text(("a", None, "b")) == "a b",
      "keyboard answers of any shape turned into text")
store = core.ChannelStore()
session = FakeSession()
ch = session.open(ChannelsScreen, store, FeedManager(os.path.join(harness.TMP, "fm_web")), Sources())
check(ch.unskinned == [] and ch.page is not None and ch.page.url.endswith(":%d/" % ch.page.port),
      "channel manager starts the phone/PC page")
check(ch.page.url in ch["subtitle"].getText(), "page address shown on the TV")
ch._entered([])
box = session.dialogs[-1]
check("sent back no text" in box.text and ch.page.url in box.text, "empty keyboard answer explained, page offered")
ch._entered(b"@laliga")
check("already in your list" in session.dialogs[-1].text, "bytes from the keyboard accepted")
base = "http://127.0.0.1:%d" % ch.page.port
page = requests.get(base + "/").text
check("kayfa1x_2" in page and "Kayfa1x Summaries" in page and 'action="/add"' in page, "page lists the channels")
r = requests.post(base + "/add", data={"user": "https://www.tiktok.com/@NewChan?lang=en"}, allow_redirects=False)
check(r.status_code == 303, "add from the page redirects back")
settle(lambda: store.get("newchan") is not None and not ch.checking, 20)
check(store.get("newchan")["name"] == "New Channel" and "Added @newchan" in requests.get(base + "/").text,
      "channel added from the phone, verified on TikTok")
requests.post(base + "/toggle", data={"user": "newchan"})
settle(lambda: not store.get("newchan")["enabled"])
check(not store.get("newchan")["enabled"], "channel switched off from the phone")
requests.post(base + "/remove", data={"user": "newchan"})
settle(lambda: store.get("newchan") is None)
check(store.get("newchan") is None and ch.changed, "channel removed from the phone")
requests.post(base + "/add", data={"user": "not a name!"})
settle(lambda: "not a valid" in ch.last_status)
check("not a valid TikTok username" in requests.get(base + "/").text, "bad name explained on the page")
requests.post(base + "/add", data={"user": "ghost_user"})
settle(lambda: [u for u, _ in ch.web_failed] == ["ghost_user"] and not ch.checking, 20)
page = requests.get(base + "/").text
check("Couldn&#x27;t verify @ghost_user" in page and "Add @ghost_user anyway" in page, "failed check offers 'add anyway'")
check(not any(type(d).__name__ == "MessageBox" and "ghost_user" in d.text for d in session.dialogs),
      "no TV pop-up for checks started on the phone")
requests.post(base + "/add", data={"user": "ghost_user", "force": "1"})
settle(lambda: store.get("ghost_user") is not None)
check(store.get("ghost_user") is not None and ch.web_failed == [], "'add anyway' adds it")
port = ch.page.port
ch["actions"].actions["cancel"]()
settle(lambda: True)
try:
    requests.get("http://127.0.0.1:%d/" % port, timeout=2)
    stopped = False
except requests.RequestException:
    stopped = True
check(stopped, "page stops when the channel manager closes")

print("All %d audio/web checks passed." % len(passed))
