# -*- coding: utf-8 -*-
"""Updates from the plugin's GitHub repository.

The repository holds version.txt (first line: the latest version, then optional
release notes) and the matching package ipk/enigma2-plugin-extensions-simplyscores_<version>_all.ipk.
The same files serve the telnet installer (installer.sh in the repository).
"""
import os
import re
import time

from .net import NetError, Session

REPO = "Ahmed-Mohammed-Abbas/SimplyScores"
BRANCH = "main"
RAW = "https://raw.githubusercontent.com/%s/%s" % (REPO, BRANCH)
PACKAGE = "enigma2-plugin-extensions-simplyscores"
CHECK_EVERY = 24 * 3600          # automatic check at most once a day


def telnet_command():
    return "wget -q --no-check-certificate %s/installer.sh -O - | /bin/sh" % RAW


def parse_version(text):
    """(version, notes) from version.txt, or (None, '') when it doesn't start with one."""
    lines = (text or "").replace("\r", "").strip().split("\n")
    m = re.match(r"^v?(\d+(?:\.\d+){1,3})$", lines[0].strip()) if lines else None
    if not m:
        return None, ""
    return m.group(1), "\n".join(l.strip() for l in lines[1:] if l.strip())


def version_key(version):
    return tuple(int(p) for p in re.findall(r"\d+", version or "0"))


def is_newer(latest, current):
    return bool(latest) and version_key(latest) > version_key(current)


def ipk_name(version):
    return "%s_%s_all.ipk" % (PACKAGE, version)


def check(timeout=12):
    """(latest version, notes) from GitHub. Raises NetError. Blocking."""
    url = "%s/version.txt?t=%d" % (RAW, int(time.time()))    # skip GitHub's 5-minute cache
    reply = Session().request("GET", url, headers={"Cache-Control": "no-cache"}, timeout=timeout,
                              label="update check")
    if reply.status != 200:
        raise NetError("GitHub answered HTTP %d" % reply.status)
    version, notes = parse_version(reply.text)
    if not version:
        raise NetError("version.txt has no version number")
    return version, notes


def download(version, folder="/tmp", timeout=60):
    """Saves the package of that version and returns its path. Raises NetError. Blocking."""
    url = "%s/ipk/%s" % (RAW, ipk_name(version))
    reply = Session().request("GET", url, timeout=timeout, label="update download")
    if reply.status != 200:
        raise NetError("package download: HTTP %d" % reply.status)
    if not reply.content.startswith(b"!<arch>\n") or len(reply.content) < 2048:
        raise NetError("the downloaded package is damaged")
    path = os.path.join(folder, ipk_name(version))
    with open(path, "wb") as f:
        f.write(reply.content)
    return path


def install_command(path):
    return "opkg install --force-reinstall %s" % path
