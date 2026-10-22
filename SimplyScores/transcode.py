# -*- coding: utf-8 -*-
"""Optional audio conversion with ffmpeg (MENU -> Audio -> Convert with ffmpeg).

ffmpeg reads the clip from the local relay, copies the video and converts the
audio to MPEG-1 Layer II (the DVB broadcast format every receiver decodes),
in an MPEG transport stream the player reads from the relay.
"""
import os
import select
import shutil
import subprocess
import threading

_cache = {}


def ffmpeg_path():
    if "path" not in _cache:
        found = shutil.which("ffmpeg")
        if not found:
            found = next((p for p in ("/usr/bin/ffmpeg", "/usr/local/bin/ffmpeg") if os.path.exists(p)), None)
        _cache["path"] = found
    return _cache["path"]


def reset():
    _cache.clear()


def ffmpeg_version():
    path = ffmpeg_path()
    if not path:
        return None
    try:
        out = subprocess.run([path, "-hide_banner", "-version"], stdout=subprocess.PIPE,
                             stderr=subprocess.STDOUT, timeout=15).stdout
        return out.decode("utf-8", "replace").splitlines()[0].strip()
    except Exception as e:
        return "found but not usable (%s)" % e


def command(path, source):
    return [path, "-nostdin", "-hide_banner", "-loglevel", "error", "-i", source,
            "-map", "0:v:0", "-map", "0:a:0?", "-c:v", "copy",
            "-c:a", "mp2", "-b:a", "192k", "-ar", "48000", "-ac", "2",
            "-f", "mpegts", "-muxdelay", "0", "pipe:1"]


class Converter(object):
    """One running ffmpeg; read() returns MPEG-TS bytes."""

    def __init__(self, source):
        path = ffmpeg_path()
        if not path:
            raise OSError("ffmpeg is not installed")
        self.proc = subprocess.Popen(command(path, source), stdin=subprocess.DEVNULL,
                                     stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        self.errors = []
        t = threading.Thread(target=self._drain)
        t.daemon = True
        t.start()

    def _drain(self):
        for line in iter(self.proc.stderr.readline, b""):
            self.errors.append(line.decode("utf-8", "replace").strip())
            del self.errors[:-10]

    def read(self, timeout=None):
        """Next output bytes; b"" at the end; None if nothing came within timeout."""
        fd = self.proc.stdout.fileno()
        if timeout is not None:
            ready = select.select([fd], [], [], timeout)[0]
            if not ready:
                return None
        return os.read(fd, 65536)

    def error(self):
        text = " ".join(e for e in self.errors[-3:] if e)
        return text or "ffmpeg stopped (exit code %s)" % self.proc.poll()

    def stop(self):
        try:
            if self.proc.poll() is None:
                self.proc.kill()
            self.proc.wait(timeout=5)
        except Exception:
            pass
