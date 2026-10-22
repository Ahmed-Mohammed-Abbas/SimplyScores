# -*- coding: utf-8 -*-
"""Synthetic TikWM / ESPN replies shaped like the real APIs (test harness only)."""
import hashlib
import io
import time

from PIL import Image, ImageDraw, ImageFont

NOW = time.time()
H = 3600

CAPTIONS = {
    "kayfa1x_2": [
        (25 * 60, "ملخص مباراة ريال مدريد وبرشلونة 2-1 | الكلاسيكو 🔥 #الكلاسيكو #ريال_مدريد #برشلونة", 58),
        (3 * H, "أهداف ليفربول ضد مانشستر سيتي 3-1 ⚽ #ليفربول #الدوري_الانجليزي", 71),
        (9 * H, "ملخص إنتر ميلان وبايرن ميونخ 1-1 في دوري الأبطال #دوري_ابطال_اوروبا", 64),
        (26 * H, "أجمل أهداف الجولة في الدوري الإسباني #لاليغا", 49),
        (50 * H, "ملخص مباراة الأهلي والهلال 2-2 #دوري_روشن", 66),
        (9 * 24 * H, "ملخص قديم خارج نطاق الأيام السبعة", 40),
    ],
    "championsleague": [
        (2 * H, "Every goal from Matchday 3 👀 #UCL #ChampionsLeague", 45),
        (20 * H, "What a finish! 🚀 #UCL", 18),
        (3 * 24 * H, "Best saves of the week 🧤", 33),
    ],
    "laliga": [
        (5 * H, "Vinícius on fire 🔥 #LALIGA #RealMadrid", 22),
        (30 * H, "Top 5 goals of the round #LALIGAEASPORTS", 61),
    ],
    "premierleague": [
        (90 * 60, "Goal of the Month contenders ⚽ #PremierLeague", 52),
        (40 * H, "Unbelievable last-minute winner #PL", 27),
    ],
    "cbssportsgolazo": [
        (11 * H, "Reacting to El Clásico 😱 #Golazo", 74),
    ],
    "newchan": [
        (40 * 60, "Fresh upload from the new channel #football", 30),
    ],
    "spl": [
        (4 * H, "أهداف الجولة في دوري روشن السعودي ⚽ #دوري_روشن", 44),
        (28 * H, "ملخص الهلال والنصر #دوري_روشن", 59),
    ],
    "qsl": [
        (10 * H, "أهداف مباراة السد والدحيل #دوري_نجوم_قطر", 47),
    ],
    "433": [
        (6 * H, "This touch 🤯 #football", 15),
    ],
    "brfootball": [
        (8 * H, "Last-minute winner 😱 #football", 21),
    ],
}

NICK = {"kayfa1x_2": "كيفا Kayfa", "championsleague": "UEFA Champions League", "laliga": "LALIGA",
        "premierleague": "Premier League", "cbssportsgolazo": "CBS Sports Golazo", "newchan": "New Channel",
        "spl": "دوري روشن السعودي", "qsl": "QSL", "433": "433", "brfootball": "B/R Football"}


def _vid(user, i):
    return str(7400000000000000000 + int(hashlib.md5(user.encode()).hexdigest()[:6], 16) * 100 + i)


def tikwm_posts(user):
    if user not in CAPTIONS:
        return {"code": -1, "msg": "Url parsing is failed! Please check url."}
    videos = []
    for i, (age, caption, dur) in enumerate(CAPTIONS[user]):
        vid = _vid(user, i)
        videos.append({
            "id": vid, "video_id": vid, "region": "IQ", "title": caption,
            "cover": "/video/cover/%s.webp" % vid, "origin_cover": "/video/cover/%s.webp" % vid,
            "duration": dur, "play": "/video/media/play/%s.mp4" % vid,
            "wmplay": "/video/media/wmplay/%s.mp4" % vid, "hdplay": "/video/media/hdplay/%s.mp4" % vid,
            "size": 2000000, "music": "", "music_info": {"title": "original sound", "author": NICK[user]},
            "play_count": 1200000 // (i + 1), "digg_count": 98400 // (i + 1), "comment_count": 2310 // (i + 1),
            "share_count": 870 // (i + 1), "collect_count": 4000, "create_time": int(NOW - age),
            "is_ad": False, "author": {"id": "1", "unique_id": user, "nickname": NICK[user],
                                       "avatar": "/video/avatar/%s.jpeg" % user},
        })
    # a pinned old post (shown first by TikTok) and a photo slideshow (must be skipped)
    old = _vid(user, 90)
    videos.insert(0, dict(videos[0], id=old, video_id=old, is_top=1, title="Pinned: channel trailer",
                          create_time=int(NOW - 60 * 24 * H)))
    photo = _vid(user, 91)
    videos.insert(1, dict(videos[0], id=photo, video_id=photo, images=["a.jpg"], is_top=0,
                          create_time=int(NOW - 60)))
    return {"code": 0, "msg": "success", "processed_time": 0.4,
            "data": {"videos": videos, "cursor": "0", "hasMore": False}}


def tikwm_info(user):
    if user not in CAPTIONS:
        return {"code": -1, "msg": "user not exist"}
    return {"code": 0, "msg": "success", "data": {
        "user": {"id": "1", "uniqueId": user, "nickname": NICK[user],
                 "avatarThumb": "/video/avatar/%s.jpeg" % user, "privateAccount": False},
        "stats": {"followerCount": 1534000, "videoCount": 812}}}


def _iso(ts):
    return time.strftime("%Y-%m-%dT%H:%MZ", time.gmtime(ts))


def _event(eid, home, away, hs, as_, state, detail, kickoff, goals=()):
    details = [{"scoringPlay": True, "clock": {"displayValue": m}, "team": {"id": "h" if side == "home" else "a"},
                "athletesInvolved": [{"shortName": name}], "ownGoal": False, "penaltyKick": False}
               for name, m, side in goals]
    return {"id": eid, "date": _iso(kickoff), "status": {"type": {"state": state, "shortDetail": detail}},
            "competitions": [{"competitors": [
                {"homeAway": "away", "score": as_, "team": {"id": "a", "shortDisplayName": away}},
                {"homeAway": "home", "score": hs, "team": {"id": "h", "shortDisplayName": home}}],
                "status": {"type": {"state": state, "shortDetail": detail}, "displayClock": detail},
                "details": details}]}


def espn(url):
    events = [
        _event("1", "Real Madrid", "Juventus", "2", "1", "post", "FT", NOW - 20 * H,
               [("Mbappé", "23'", "home"), ("Vlahović", "40'", "away"), ("Vinícius Jr.", "78'", "home")]),
        _event("2", "Bayern", "Arsenal", "1", "1", "in", "67'", NOW - H,
               [("Kane", "12'", "home"), ("Saka", "54'", "away")]),
        _event("3", "PSG", "Inter", "0", "0", "post", "FT", NOW - 21 * H),
        _event("4", "Liverpool", "Barcelona", "0", "0", "pre", "", NOW + 3 * H),
        _event("5", "Man City", "Atlético", "0", "0", "pre", "", NOW + 27 * H),
        _event("6", "Dortmund", "Benfica", "3", "2", "post", "FT", NOW - 22 * H,
               [("Guirassy", "9' 51'", "home"), ("Pavlidis", "33'", "away")]),
        _event("7", "Chelsea", "Napoli", "0", "0", "pre", "", NOW + 28 * H),
    ]
    return {"leagues": [{"name": "UEFA Champions League"}], "events": events}


_FONT = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"


def image_bytes(url):
    """A stand-in for a TikTok cover: a pitch-like gradient with a score banner."""
    seed = int(hashlib.md5(url.encode()).hexdigest()[:6], 16)
    if "/avatar/" in url:
        im = Image.new("RGB", (200, 200), ((seed >> 16) % 200 + 30, (seed >> 8) % 120 + 40, seed % 160 + 60))
        d = ImageDraw.Draw(im)
        d.text((100, 100), url.rsplit("/", 1)[-1][:2].upper(), anchor="mm",
               font=ImageFont.truetype(_FONT, 80), fill=(255, 255, 255))
    else:
        im = Image.new("RGB", (720, 1280))
        d = ImageDraw.Draw(im)
        for y in range(1280):
            g = int(70 + 60 * y / 1280)
            d.line([(0, y), (720, y)], fill=(18, g, 38))
        for x in range(0, 720, 90):
            d.rectangle((x, 0, x + 44, 1280), fill=(22, 98, 44))
        d.rectangle((60, 200, 660, 1080), outline=(220, 240, 220), width=6)
        d.line([(60, 640), (660, 640)], fill=(220, 240, 220), width=6)
        d.ellipse((260, 540, 460, 740), outline=(220, 240, 220), width=6)
        d.ellipse((340, 860, 380, 900), fill=(250, 250, 250))
        d.rectangle((0, 70, 720, 190), fill=(8, 8, 8))
        d.text((360, 130), "RMA  2 - 1  BAR", anchor="mm", font=ImageFont.truetype(_FONT, 64),
               fill=(255, 255, 255))
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=88)
    return buf.getvalue()
