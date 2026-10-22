# SimplyScores 1.6.0 — TikTok-style football feed for Enigma2

A vertical, **newest-first** feed of match summaries and highlights from the TikTok
channels you choose (e.g. `@kayfa1x_2`), played full screen like TikTok, with an
ESPN live-scores panel in the side bar. Python 3 images: OpenATV, OpenPLi, OpenViX, Egami.

## Install

**By telnet/SSH (easiest):** run this one line on the receiver. It installs the latest version
from this repository, or updates an older one, then restarts the GUI:

```sh
wget -q --no-check-certificate https://raw.githubusercontent.com/Ahmed-Mohammed-Abbas/SimplyScores/main/installer.sh -O - | /bin/sh
```

**By hand:** copy `ipk/enigma2-plugin-extensions-simplyscores_1.6.0_all.ipk` to `/tmp` on the box
and run `opkg install /tmp/enigma2-plugin-extensions-simplyscores_1.6.0_all.ipk`, then restart
the GUI. Your channel list is kept on updates.

Open **SimplyScores** from the Plugins menu or the BLUE/Extensions menu.

Optional: `opkg install python3-pillow` for cover thumbnails and round avatars
(without it the feed still works, the Up-next list just has no pictures).

## Updates

- **MENU > Update plugin** checks this repository, shows what's new, downloads the package,
  installs it with opkg and offers to restart the GUI.
- **Automatic check:** once a day, when the plugin opens, it reads `version.txt` from this
  repository. When a newer version is there, the feed says so (*MENU: update x.y.z available*).
  Switch it off in MENU > Settings.
- The telnet command above works as an update too.

**Publishing a new version** (for the maintainer): set `VERSION` in `SimplyScores/__init__.py`,
run `python3 tools/build_ipk.py ipk`, delete the older package from `ipk/`, write the new version
on the first line of `version.txt` (release notes on the next lines) and push. `version.txt` must
name a package that exists in `ipk/`.

## Remote

| Key | In the feed |
|---|---|
| ▼ / P− | next video (older) |
| ▲ / P+ | previous video; at the top it checks for new uploads |
| ◄ / ► | switch tab: **For You** (all channels merged) or one channel |
| OK / Play-Pause | pause / resume |
| ⏪ / ⏩ | seek −10 s / +10 s |
| INFO | clean view (hide all panels) |
| RED | refresh now and jump to the newest video |
| GREEN | next league in the scores panel |
| YELLOW | video list of the current tab — OK jumps to a clip |
| BLUE | channel manager |
| MENU | menu: settings, update plugin, connection test, about |
| EXIT | close and return to live TV |

## Preferred channels (first in For You)

Channels marked **TOP** are preferred: when the plugin opens on *For You*, their videos come
first (newest first), then the videos of your other channels. Updating 1.5.0 adds these
preferred channels once, at the top of your list: `@football_actuality10`, `@kayfa1x_2`,
`@kayfa1x`, `@myintthuhighlights5`, `@ligue1`, `@mouhamedfoot333`, `@zzcombs3`,
`@koglogrgorden`, plus the channel behind `vt.tiktok.com/ZSgyS93uw/` (read on the box at the
first start). Their names are filled in from TikTok on the first update.
Change it later: MENU in the channel manager, or *Prefer* / *Unprefer* on the phone page.

The right side of the feed shows the arrow keys: ▲ previous (newer) video, ▼ next (older)
video, ◄ ► switch channel tab. INFO hides it with the other panels.

## Adding channels

**From the remote:** BLUE (channel manager) → GREEN *Add channels*. The list offers:

- **Type a username or paste a link**: `kayfa1x_2`, `@kayfa1x_2`, a `tiktok.com/@…` link or a
  share link from the TikTok app (`vt.tiktok.com/…`, `vm.tiktok.com/…`, `tiktok.com/t/…`).
  Several at once: separate them with commas.
- **Add all suggested channels**, or one of them (OK). Channels already in your list are
  shown at the end.

Every channel is checked on TikTok first and added with its real display name. In the
manager: OK = on/off, RED = remove, YELLOW = rename, BLUE = move up (order = tab order).

**From a phone or PC (easiest):** while the channel manager is open, its subtitle shows an
address such as `http://192.168.1.20:8765/`. Open it on any phone or PC on the same network:

- paste up to 30 usernames or links at a time, one per line or separated by commas. Text copied
  from TikTok's share button ("Check out … https://vt.tiktok.com/…") works as it is;
- tap *Add* next to a suggested channel, or *Add all*;
- switch channels off or remove them.

The page shows what was added, what was already there and what couldn't be checked, with an
*Add anyway* button for each of those. It closes with the channel manager.

**Finding more channels like Kayfa1x:** in the TikTok app, search hashtags such as
`#footballtiktok`, `#goalcompilation` or `#matchday`, open a video from a channel you like,
tap *Share → Copy link* and paste the link on the phone page. The plugin can't follow a
hashtag itself: TikTok serves hashtag feeds to its app only, ordered by popularity rather than
newest first.

### Suggested channels

| Channel | Content |
|---|---|
| `@kayfa1x_2` Kayfa1x Summaries | match summaries and goals (in the default list) |
| `@spl` Saudi Pro League | official league channel, Arabic |
| `@qsl` Qatar Stars League | official league channel, Arabic |
| `@fifaworldcup` FIFA World Cup | official World Cup channel |
| `@championsleague`, `@premierleague`, `@laliga` | official channels (in the default list) |
| `@433` | goals, skills and big moments |
| `@brfootball` B/R Football | highlights and football culture |
| `@cbssportsgolazo` CBS Sports Golazo | highlights and studio shows (in the default list) |

The handles were checked against the leagues' own websites and press coverage in October 2026.

**By file:** edit `/etc/enigma2/simplyscores.json` (created on first start) and add
entries to `tiktok_channels`, e.g. `{"name": "My channel", "username": "somechannel", "enabled": true}`.
Leagues for the scores panel live in `score_leagues` (ESPN codes such as `eng.1`,
`esp.1`, `ita.1`, `ger.1`, `fra.1`, `uefa.champions`). The file format of the original
plan is accepted as-is.

## How it works

- Two video sources, chosen automatically (MENU > Settings → *Video source* to force one):
  - **TikWM** (tikwm.com), a free API. It sits behind Cloudflare, which may answer
    "HTTP 403" to some networks or clients, so four request styles are tried, each in
    a fresh session, and the one that works is remembered.
  - **TikTok direct**, the method yt-dlp uses: the channel page gives the account id
    (secUid, cached in the channel list), then TikTok's `creator/item_list` API returns
    the newest posts. TikTok's "Please wait..." bot check (a SHA-256 puzzle) is solved
    on the box.
  A source that refuses the box is skipped for 20 minutes; the one that worked is tried
  first next time. Photo slideshows and ads are skipped, pinned posts are re-sorted by
  date, and everything is merged newest-first.
- Playable links come from each clip's own TikTok page, loaded in a session of its own:
  TikTok's CDN refuses links unless the request carries the cookies of the session that
  loaded them, and it refuses the links in the video list itself. A background worker
  fetches them for the clip about to play first, then for the next two, so swiping is quick
  and the player never waits on TikTok.
- Playback goes through a small relay on `127.0.0.1` inside the plugin. It requests
  the clip with that session's cookies and the Referer TikTok's CDN expects, passes seeking
  (Range) through, tries the next link when one fails and fetches fresh links from the
  clip's page when all have expired. It works the same with GStreamer and exteplayer3.
- Sound: TikTok's clips use HE-AAC (AAC + SBR, usually + PS: "mp4a.40.29"). The
  receivers' GStreamer audio sink turns that MP4 header into an ADTS header with an invalid
  AAC profile, so the hardware decoder stays silent. The relay rewrites the header to AAC-LC
  at the core sample rate (same length, nothing else in the file moves); the decoder then
  finds the SBR/PS data by itself. MENU > Settings → *Sound* can instead convert the sound to MP2 with
  ffmpeg, or leave it untouched.
- H.264 links are preferred. If the receiver reports it can't decode H.265, the plugin
  switches to H.264 links by itself and retries the clip (MENU > Settings → *Video codec* to force it).
- Share links (`vt.tiktok.com/…`) are followed the way yt-dlp does it, asking as a
  link-preview robot, which gets a plain redirect to `tiktok.com/@channel/video/…`. A video
  link without a channel name is looked up on the clip's page (TikWM is asked when TikTok's
  pages refuse the box).
- Feeds are cached in `/tmp/simplyscores` (RAM), shown instantly on the next open,
  and re-checked every 15 minutes while you watch. New uploads appear above the
  current clip with a "new" pill; the very first update after opening jumps to the newest.
- Clips newer than your last visit get a **NEW** badge.
- The receiver pillarboxes vertical video into the centre column; all panels sit in
  the black side bars. Landscape clips hide the panels automatically.
- Network work runs in background threads; the GUI is only touched on the main thread
  (`reactor.callFromThread`), so the box never freezes while loading.

## Settings (MENU > Settings)

Video source (automatic / TikWM only / TikTok direct only), video codec (H.264 first /
H.264 only), sound (fix HE-AAC / convert with ffmpeg / as it is), video player (4097 GStreamer /
5002 exteplayer3 / 5001 gstplayer — the last two need ServiceApp), prefer HD, what happens
when a clip ends (next / replay / stop), time range (24 h … any time), videos per channel,
refresh interval, scores panel on/off, hashtags, landscape clean view, and an Arabic text fix.

**BLUE in settings = install ffmpeg** (shown only when it's missing; needed only for
*Sound: convert with ffmpeg*). It runs `opkg update` and `opkg install ffmpeg`.

**YELLOW in settings = connection test.** It checks DNS, ESPN, every TikWM request style,
TikTok's page and video list, streams the first 64 KB of a clip, reads its video and sound
format and tries the ffmpeg conversion, then says which source works. The full report, with every request and answer and the latest playback log, is
saved to `/tmp/simplyscores/diagnose.txt`. Every clip's link fetch, relay answer and player
result is also written to `/tmp/simplyscores/playback.txt`.

## Troubleshooting

- **"Couldn't load videos"** → the message names what each source answered (for example
  `TikWM: HTTP 403 Cloudflare challenge`). Run the connection test (MENU > Connection test) and send
  `/tmp/simplyscores/diagnose.txt` if neither source works.
- **No sound** → keep *Sound: fix TikTok's HE-AAC* (the default). If a receiver is still
  silent, choose *Convert with ffmpeg* (BLUE installs ffmpeg) or try player 5002, then run
  the connection test: its *Clip format* line names the sound type.
- **A clip won't play** → it is skipped after a few seconds and the status line shows why:
  a link problem (`HTTP 403` from the CDN), the player's own message, or a codec the
  receiver can't decode. If many fail, set *Video codec* to H.264 only, or switch the player
  to 5002 in MENU > Settings (install `enigma2-plugin-systemplugins-serviceapp`), then run the
  connection test and send `/tmp/simplyscores/diagnose.txt`.
- **Video is stretched instead of centred** → set the 16:9 TV aspect handling to
  pillarbox/letterbox in the box's A/V settings.
- **Arabic looks disconnected or reversed** → enable *Fix Arabic text* (needs the
  `arabic_reshaper` and `python-bidi` Python modules from your image's feed or pip).
  Leave it off if Arabic already looks right — modern images render it natively.
- **"Free Api Limit"** in the status line → TikWM throttled you; it retries by itself.
- **Wrong box clock** → TikTok pages its video list by time; the plugin corrects the clock
  from the servers' replies, but set NTP so certificates are checked properly too.
- Logs: lines starting with `[SimplyScores]` in the Enigma2 debug log.

## Files

```
/usr/lib/enigma2/python/Plugins/Extensions/SimplyScores/
  plugin.py      entry point + settings definitions
  plugin.png     menu icon for HD skins (100x40), plugin_fhd.png for FHD skins (150x60)
  ui_feed.py     TikTok-style feed screen
  ui_manage.py   channel manager, video list, settings screens
  gui.py         skins (designed for 1920x1080, auto-scaled to 1280x720)
  sources.py     picks the working source, opens streams
  src_tikwm.py   TikWM client (4 request styles)
  src_tiktok.py  TikTok direct client (bot check, item_list, video pages)
  proxy.py       local stream relay       net.py      sessions, block detection
  diagnose.py    connection test          api_scores.py  ESPN scoreboard
  feed.py        merge/cache              images.py   cover/avatar downloader
  audiofix.py    MP4 header reader + HE-AAC sound fix
  transcode.py   optional ffmpeg conversion (MP2 sound, MPEG-TS)
  webpage.py     channel page for phones/PCs
  updater.py     update check and download from GitHub   ui_update.py  MENU and update screens
  core.py        HTTP, text helpers, channel store
/etc/enigma2/simplyscores.json   your channels (+ cached secUid), leagues, last visit,
                                 last working source
```

Source extras: `tools/make_icons.py` (redraws the icons, including the menu icon),
`tools/build_ipk.py` (rebuilds the .ipk), `tests/` (a simulated Enigma2 session against a fake
internet with a blocked TikWM, TikTok's bot check, share links and a cookie-checking CDN:
`python3 tests/test_all.py out`, `test_audio_web.py`, `test_channels.py`, `test_preferred.py`, `test_update.py`).
