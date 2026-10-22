#!/usr/bin/env python3
"""Build enigma2-plugin-extensions-simplyscores_<version>_all.ipk (ar + tar.gz, as opkg expects)."""
import io
import os
import re
import sys
import tarfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PLUGIN = os.path.join(ROOT, "SimplyScores")
TARGET = "usr/lib/enigma2/python/Plugins/Extensions/SimplyScores"
PACKAGE = "enigma2-plugin-extensions-simplyscores"

CONTROL = """Package: %(pkg)s
Version: %(ver)s
Description: TikTok-style football highlights and live scores
 Vertical, newest-first feed of match clips from TikTok channels you choose,
 with live ESPN scores. Uses TikWM or TikTok directly, whichever works.
Section: extra
Priority: optional
Maintainer: Mohammed Mousa
Architecture: all
Depends: python3-requests
"""

POSTINST = """#!/bin/sh
rm -rf /tmp/simplyscores
rm -f /usr/lib/enigma2/python/Plugins/Extensions/SimplyScores/api_tiktok.py
echo ""
echo "SimplyScores %(ver)s installed."
echo "Restart the GUI to load it (or run: init 4 && sleep 2 && init 3)."
exit 0
"""

POSTRM = """#!/bin/sh
rm -rf /usr/lib/enigma2/python/Plugins/Extensions/SimplyScores/__pycache__ /tmp/simplyscores
rmdir /usr/lib/enigma2/python/Plugins/Extensions/SimplyScores 2>/dev/null
exit 0
"""


def version():
    text = open(os.path.join(PLUGIN, "__init__.py"), encoding="utf-8").read()
    return re.search(r'VERSION = "([^"]+)"', text).group(1)


def _info(name, size, mode, is_dir=False):
    ti = tarfile.TarInfo(name)
    ti.size, ti.mode, ti.mtime = size, mode, int(time.time())
    ti.uid = ti.gid = 0
    ti.uname = ti.gname = "root"
    if is_dir:
        ti.type = tarfile.DIRTYPE
    return ti


def tar_gz(entries):
    """entries: list of (archive name, bytes or None for directory, mode)."""
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz", format=tarfile.GNU_FORMAT) as tar:
        for name, data, mode in entries:
            if data is None:
                tar.addfile(_info(name, 0, mode, True))
            else:
                tar.addfile(_info(name, len(data), mode), io.BytesIO(data))
    return buf.getvalue()


def ar(members):
    out = io.BytesIO()
    out.write(b"!<arch>\n")
    for name, data in members:
        header = "%-16s%-12d%-6d%-6d%-8s%-10d`\n" % (name, int(time.time()), 0, 0, "100644", len(data))
        out.write(header.encode("ascii"))
        out.write(data)
        if len(data) % 2:
            out.write(b"\n")
    return out.getvalue()


def main(out_dir):
    ver = version()
    data = [("./usr", None, 0o755)]
    parts = TARGET.split("/")
    for i in range(2, len(parts) + 1):
        data.append(("./" + "/".join(parts[:i]), None, 0o755))
    for dirpath, dirnames, filenames in os.walk(PLUGIN):
        dirnames[:] = sorted(d for d in dirnames if d != "__pycache__")
        rel = os.path.relpath(dirpath, PLUGIN)
        if rel != ".":
            data.append(("./%s/%s" % (TARGET, rel), None, 0o755))
        for fn in sorted(filenames):
            if fn.endswith((".pyc", ".pyo")):
                continue
            path = os.path.join(dirpath, fn)
            name = "./%s/%s" % (TARGET, fn if rel == "." else rel + "/" + fn)
            data.append((name, open(path, "rb").read(), 0o644))
    control = [("./control", (CONTROL % {"pkg": PACKAGE, "ver": ver}).encode(), 0o644),
               ("./postinst", (POSTINST % {"ver": ver}).encode(), 0o755),
               ("./postrm", POSTRM.encode(), 0o755)]
    ipk = ar([("debian-binary", b"2.0\n"), ("control.tar.gz", tar_gz(control)),
              ("data.tar.gz", tar_gz(data))])
    os.makedirs(out_dir, exist_ok=True)
    target = os.path.join(out_dir, "%s_%s_all.ipk" % (PACKAGE, ver))
    with open(target, "wb") as f:
        f.write(ipk)
    print(target)


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else os.path.join(ROOT, "dist"))
