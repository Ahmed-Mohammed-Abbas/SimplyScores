"""Updates from GitHub: version.txt, the daily check, MENU > Update plugin, the telnet installer.

Usage: python3 tests/test_update.py
"""
import os
import subprocess

import harness
from harness import FakeSession, settle

world = harness.install()

from SimplyScores import VERSION, core, net, updater  # noqa: E402
from SimplyScores import plugin  # noqa: E402,F401  (defines config.plugins.simplyscores)
assert plugin
from SimplyScores.ui_feed import SimplyScoresFeed  # noqa: E402
from SimplyScores.ui_update import PluginMenu  # noqa: E402

passed = []
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def check(cond, label):
    assert cond, "FAILED: " + label
    passed.append(label)


def bump(version):
    parts = [int(p) for p in version.split(".")]
    parts[-1] += 1
    return ".".join(str(p) for p in parts)


# --------------------------------------------------------------------------- version.txt
check(updater.parse_version("1.6.0\nUpdate from GitHub\n") == ("1.6.0", "Update from GitHub"), "version and notes read")
check(updater.parse_version("v2.0\r\n") == ("2.0", ""), "'v' prefix and Windows line ends accepted")
check(updater.parse_version("<html>404</html>") == (None, ""), "an error page is not a version")
check(updater.is_newer("1.10.0", "1.9.3") and not updater.is_newer("1.5.0", "1.5.0")
      and not updater.is_newer("1.4.9", "1.5.0"), "versions compared as numbers")
repo_version = open(os.path.join(ROOT, "version.txt")).read()
check(updater.parse_version(repo_version)[0] == VERSION, "version.txt in the repository matches the plugin")

NEW = bump(VERSION)
fake_ipk = b"!<arch>\n" + b"x" * 4096
world.gh_files.update({"version.txt": ("%s\nFaster loading\n" % NEW).encode(), "ipk/" + updater.ipk_name(NEW): fake_ipk})
check(updater.check() == (NEW, "Faster loading"), "latest version read from GitHub")
folder = os.path.join(harness.TMP, "dl")
os.makedirs(folder)
path = updater.download(NEW, folder)
check(open(path, "rb").read() == fake_ipk and path.endswith(updater.ipk_name(NEW)), "package downloaded")
world.gh_files["ipk/" + updater.ipk_name(NEW)] = b"<html>oops</html>"
try:
    updater.download(NEW, folder)
    damaged = False
except net.NetError:
    damaged = True
check(damaged, "a damaged package is refused")
world.gh_files["ipk/" + updater.ipk_name(NEW)] = fake_ipk

# --------------------------------------------------------------------------- daily check when the feed opens
if os.path.exists(core.CONFIG_PATH):
    os.remove(core.CONFIG_PATH)
session = FakeSession()
scr = session.open(SimplyScoresFeed)
settle(lambda: scr.update_available == NEW, 20)
check(scr.update_available == NEW and "MENU: update %s available" % NEW in scr["key_hint"].getText(),
      "new version announced on screen")
check(scr.store.extra["update_latest"] == NEW and scr.store.extra["update_checked"] > 0, "check result remembered")
hits = world.hits.get("github", 0)
scr.autoUpdateCheck()
settle(lambda: True)
check(world.hits.get("github", 0) == hits, "checked at most once a day")
scr.cfg.update_check.value = False
scr.store.extra["update_checked"] = 0
scr.autoUpdateCheck()
settle(lambda: True)
check(world.hits.get("github", 0) == hits, "no check when switched off in the settings")
scr.cfg.update_check.value = True

# --------------------------------------------------------------------------- MENU > Update plugin
scr["actions"].actions["menu"]()
menu = session.dialogs[-1]
check(isinstance(menu, PluginMenu) and menu.unskinned == [], "MENU opens the plugin menu")
check(menu["list"].list[1][0] == "update" and ("Update plugin to %s" % NEW) == menu["list"].list[1][2][1]["text"],
      "menu offers the new version")
menu["list"].moveToIndex(1)
menu["actions"].actions["ok"]()
box = session.dialogs[-1]
check(type(box).__name__ == "MessageBox" and NEW in box.text and "Faster loading" in box.text, "asks before updating")
box.callback(True)
settle(lambda: type(session.dialogs[-1]).__name__ == "Console", 20)
console = session.dialogs[-1]
check(console.cmdlist == ["opkg install --force-reinstall /tmp/" + updater.ipk_name(NEW)], "opkg installs the download")
console.callback()
restart = session.dialogs[-1]
check("Restart the GUI now" in restart.text, "offers a GUI restart")
restart.callback(True)
check(type(session.dialogs[-1]).__name__ == "TryQuitMainloop" and session.dialogs[-1].retvalue == 3, "GUI restarts")
check(not os.path.exists("/tmp/" + updater.ipk_name(NEW)), "downloaded package cleaned up")

# up to date / GitHub unreachable
world.gh_files["version.txt"] = ("%s\n" % VERSION).encode()
scr.update_available = None
scr.startUpdate()
settle(lambda: not scr.updater.busy, 20)
check("latest version" in session.dialogs[-1].text, "'latest version' when nothing is newer")
del world.gh_files["version.txt"]
scr.startUpdate()
settle(lambda: not scr.updater.busy, 20)
check("Couldn't check for updates" in session.dialogs[-1].text and "installer.sh" in session.dialogs[-1].text,
      "error explained, with the telnet command")
scr["actions"].actions["menu"]()
menu = session.dialogs[-1]
menu["list"].moveToIndex(3)
menu["actions"].actions["ok"]()
check("by reali22" in session.dialogs[-1].text and "github.com/Ahmed-Mohammed-Abbas/SimplyScores" in session.dialogs[-1].text
      and "installer.sh -O - | /bin/sh" in session.dialogs[-1].text, "About shows the GitHub page and telnet command")
scr["actions"].actions["cancel"]()

# --------------------------------------------------------------------------- telnet installer
script = os.path.join(ROOT, "installer.sh")
check(subprocess.call(["sh", "-n", script]) == 0, "installer.sh is valid shell")
text = open(script).read()
check("raw.githubusercontent.com/Ahmed-Mohammed-Abbas/SimplyScores/main" in text and "version.txt" in text
      and "opkg install" in text, "installer reads version.txt and installs the package with opkg")
check(os.path.exists(os.path.join(ROOT, "ipk", updater.ipk_name(VERSION))), "package of this version in ipk/")

# run it against the fake GitHub, with stand-ins for opkg and killall
bin_dir = os.path.join(harness.TMP, "bin")
os.makedirs(bin_dir)
log_file = os.path.join(harness.TMP, "calls.txt")
for tool in ("opkg", "killall", "sleep"):
    with open(os.path.join(bin_dir, tool), "w") as f:
        f.write('#!/bin/sh\necho "%s $*" >> %s\nexit 0\n' % (tool, log_file))
    os.chmod(os.path.join(bin_dir, tool), 0o755)
world.gh_files.update({"version.txt": ("%s\nnotes\n" % NEW).encode(), "ipk/" + updater.ipk_name(NEW): fake_ipk})
local = os.path.join(harness.TMP, "installer.sh")
open(local, "w").write(text.replace("https://raw.githubusercontent.com/Ahmed-Mohammed-Abbas/SimplyScores/main",
                                    world.base + "/gh"))
env = dict(os.environ, PATH=bin_dir + ":" + os.environ["PATH"])
env.pop("HTTPS_PROXY", None), env.pop("https_proxy", None), env.pop("HTTP_PROXY", None), env.pop("http_proxy", None)
out = subprocess.run(["sh", local], env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=60).stdout.decode()
calls = open(log_file).read()
check("opkg install --force-reinstall --force-downgrade /tmp/" + updater.ipk_name(NEW) in calls and "killall -9 enigma2" in calls
      and "SimplyScores %s installed" % NEW in out, "telnet installer downloads, installs and restarts the GUI")
del world.gh_files["version.txt"]
open(log_file, "w").close()
code = subprocess.run(["sh", local], env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=60).returncode
check(code == 1 and "killall" not in open(log_file).read(), "installer stops when GitHub can't be read")

print("All %d update checks passed." % len(passed))
