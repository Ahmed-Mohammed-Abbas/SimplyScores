# -*- coding: utf-8 -*-
"""Connection test: shows what every server answers this box.

The report is also written to /tmp/simplyscores/diagnose.txt so it can be
copied off the receiver (FTP) and shared when something doesn't work.
"""
import os
import socket
import sys
import time

from . import api_scores, audiofix, net, src_tikwm, transcode
from .core import CACHE_DIR, ensure_dir, fmt_count, playlog_tail
from .net import NetError, SourceError, host_of, note
from .sources import describe_stream, stream_kinds
from .src_tiktok import parse_item

DNS_HOSTS = ("www.tikwm.com", "www.tiktok.com", "site.api.espn.com")


def report_path():
    return os.path.join(CACHE_DIR, "diagnose.txt")


def _versions():
    parts = ["Python %s" % sys.version.split()[0]]
    try:
        import requests
        parts.append("requests %s" % requests.__version__)
    except Exception:
        parts.append("requests MISSING (install python3-requests)")
    from .images import HAVE_PIL
    parts.append("Pillow %s" % ("yes" if HAVE_PIL else "no"))
    return ", ".join(parts)


def _mark(ok):
    return "[ OK ]" if ok else "[FAIL]"


def _fetch(session, url, headers, start, end):
    h = dict(headers)
    h.update({"Range": "bytes=%d-%d" % (start, end), "Accept-Encoding": "identity"})
    resp = session.open(url, headers=h)
    try:
        if resp.status_code not in (200, 206):
            return b""
        data = b""
        for chunk in resp.iter_content(65536):
            data += chunk
            if len(data) > end - start:
                break
        return data[:end - start + 1]
    finally:
        resp.close()


def _media_report(sources, video, say, trace):
    """Tracks of the clip that played and what the Sound setting does with them."""
    good = video.get("good")
    plan = [p for p in sources.stream_plan(video) if p[0] == good]
    if not plan:
        return
    url, session, headers, _ = plan[0]
    try:
        media = audiofix.probe(lambda a, b: _fetch(session, url, headers, a, b))
    except Exception as e:
        note(trace, "media probe failed: %s" % e)
        media = None
    if not media:
        say("[INFO] Clip format: couldn't read the MP4 header")
        return
    audio = media.get("audio") or {}
    say("[INFO] Clip format: %s, %s" % (audiofix.describe_video(media.get("video")),
                                       audiofix.describe_audio(audio)))
    if audio.get("dsi") and audiofix.lc_header(audio["dsi"][1]):
        say("       Receivers' audio sink mislabels this HE-AAC sound; 'Sound: Fix' rewrites its header")


def _conversion_report(sources, video, say):
    version = transcode.ffmpeg_version()
    if not version:
        say("[INFO] ffmpeg: not installed (only needed for 'Sound: Convert with ffmpeg')")
        return
    say("[INFO] ffmpeg: %s" % version)
    from .proxy import StreamProxy
    relay = StreamProxy(sources, audio_mode=lambda: "fix")
    t0 = time.time()
    try:
        resp = net.Session().open(relay.url(video, False, convert=True), timeout=(5, 30))
        data = b""
        try:
            if resp.status_code == 200:
                for chunk in resp.iter_content(65536):
                    data += chunk
                    if len(data) >= 188 * 500:
                        break
        finally:
            resp.close()
        ts = len(data) >= 188 * 4 and all(data[i] == 0x47 for i in range(0, 188 * 4, 188))
        if ts:
            say("[ OK ] Sound conversion with ffmpeg: MPEG-TS with MP2 sound started in %.1fs"
                % (time.time() - t0))
        else:
            say("[FAIL] Sound conversion with ffmpeg: %s" % (relay.convert_failed or
                                                            "HTTP %d, no MPEG-TS data" % resp.status_code))
    except Exception as e:
        say("[FAIL] Sound conversion with ffmpeg: %s" % e)
    finally:
        relay.stop()


def run(sources, username, league, emit, version="", sound=None):
    """Blocking; call from a worker thread. emit(line) receives each line."""
    lines, trace = [], []

    def say(text=""):
        lines.append(text)
        emit(text)

    say("SimplyScores %s connection test, %s" % (version, time.strftime("%Y-%m-%d %H:%M")))
    say("Box: " + _versions())
    say("Test channel: @%s" % username)
    for host in DNS_HOSTS:
        try:
            ips = sorted(set(a[4][0] for a in socket.getaddrinfo(host, 443, 0, socket.SOCK_STREAM)))
            say("DNS %s -> %s" % (host, ", ".join(ips[:3])))
        except Exception as e:
            say("DNS %s -> FAILED (%s)" % (host, e))
    say("")

    try:
        matches = api_scores.scoreboard(league)[1]
        say("%s ESPN scores (%s): %d matches" % (_mark(True), league, len(matches)))
    except Exception as e:
        say("%s ESPN scores (%s): %s" % (_mark(False), league, e))

    tikwm_ok = None
    for i, style in enumerate(src_tikwm.STYLES):
        ok, text = sources.tikwm.test_style(i, username, trace)
        say("%s TikWM, %s: %s" % (_mark(ok), style[0], text))
        if ok and tikwm_ok is None:
            tikwm_ok = i

    video, tiktok_ok = None, False
    solved_before = sources.tiktok.solved
    t0 = time.time()
    try:
        prof = sources.tiktok.profile(username, trace)
        say("%s TikTok profile: %s, %s followers, account id %s (%.1fs)" % (
            _mark(True), prof["name"], fmt_count(prof["followers"]), "found" if prof["sec_uid"] else "MISSING",
            time.time() - t0))
        sec = prof["sec_uid"] or sources.tiktok.sec_uid_from_embed(username, trace)
        if sec:
            items = sources.tiktok.item_list(username, sec, 5, trace)
            vids = [v for v in (parse_item(it, username) for it in items) if v]
            kinds = sorted(set("%s %dp" % (s[1], min(s[2], s[3])) if s[2] and s[3] else s[1]
                               for v in vids for s in v["streams"]))
            say("%s TikTok video list: %d videos%s" % (
                _mark(bool(vids)), len(vids), ("  (%s)" % ", ".join(kinds[:6])) if kinds else ""))
            if vids:
                tiktok_ok, video = True, vids[0]
    except SourceError as e:
        say("%s TikTok: %s" % (_mark(False), e))
    if sources.tiktok.solved > solved_before:
        say("       TikTok's bot check appeared and was solved")

    if video is None and tikwm_ok is not None:
        try:
            vids = sources.tikwm.user_posts({"username": username}, 3, trace)[0]
            video = vids[0] if vids else None
        except SourceError:
            pass
    if video:
        if video.get("links_from") == "list":
            plan = sources.stream_plan(video, False)
            if plan:
                url, session, headers, _ = plan[0]
                h = dict(headers)
                h.update({"Range": "bytes=0-1", "Accept-Encoding": "identity"})
                try:
                    r = session.open(url, headers=h)
                    answer = "HTTP %d" % r.status_code
                    r.close()
                except NetError as e:
                    answer = str(e)
                note(trace, "list link %s -> %s" % (host_of(url), answer))
                say("[INFO] Link from the video list: %s (playback takes links from each clip's page)"
                    % answer)
            t0 = time.time()
            ok, err = sources.prepare(video, trace)
            if ok:
                say("%s Clip page links: %s (%.1fs)" % (_mark(True), stream_kinds(video["streams"]),
                                                        time.time() - t0))
            else:
                say("%s Clip page links: %s" % (_mark(False), err))
        resp, err = sources.open_stream(video, False, "bytes=0-65535", trace)
        if resp is None:
            say("%s Video stream: %s" % (_mark(False), err))
        else:
            data = b""
            try:
                for chunk in resp.iter_content(16384):
                    data += chunk
                    if len(data) >= 65536:
                        break
            except Exception as e:
                say("       stream read error: %s" % e)
            finally:
                resp.close()
            mp4 = b"ftyp" in data[:64]
            say("%s Video stream: HTTP %d, %s, %d KB read%s" % (
                _mark(mp4), resp.status_code, describe_stream(sources.served.get(video["id"])),
                len(data) // 1024, "" if mp4 else " (not an MP4 file)"))
            if mp4:
                _media_report(sources, video, say, trace)
                _conversion_report(sources, video, say)
    else:
        say("[SKIP] Video stream: no video list to test with")
    say("Codec setting: %s%s" % ("H.264 only" if sources.codec() == "h264" else "H.264 first",
                                 " (learned: this receiver needs H.264)" if sources.h264_only else ""))
    if sound:
        say("Sound setting: %s" % {"fix": "fix TikTok's HE-AAC", "convert": "convert with ffmpeg",
                                   "original": "leave as it is"}.get(sound(), sound()))

    offset = net.clock_offset()
    if abs(offset) > 300:
        say("[WARN] The box clock is off by about %d minutes: fix the time (NTP)" % (offset / 60))
    say("")
    if tikwm_ok is not None:
        say("Result: videos load through TikWM (%s)." % src_tikwm.STYLES[tikwm_ok][0])
    elif tiktok_ok:
        say("Result: TikWM refuses this box, but TikTok direct works and is used automatically.")
    else:
        say("Result: no video source answers this box right now. Please share this report.")
    played = playlog_tail(30)
    if played:
        say("")
        say("Activity log (latest):")
        for line in played:
            say("  " + line)
    say("")
    say("Request log:")
    for line in trace:
        say("  " + line)
    try:
        ensure_dir(CACHE_DIR)
        with open(report_path(), "w", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")
        say("")
        say("Saved to " + report_path())
    except Exception as e:
        say("Couldn't save the report: %s" % e)
    return lines
