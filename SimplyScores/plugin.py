# -*- coding: utf-8 -*-
"""SimplyScores - TikTok-style football highlights & live scores for Enigma2."""
from Components.config import (ConfigInteger, ConfigSelection, ConfigSubsection, ConfigYesNo,
                               config)
from Plugins.Plugin import PluginDescriptor

config.plugins.simplyscores = ConfigSubsection()
_cfg = config.plugins.simplyscores
_cfg.source = ConfigSelection(default="auto", choices=[
    ("auto", "Automatic (TikWM, else TikTok)"),
    ("tikwm", "TikWM only"),
    ("tiktok", "TikTok direct only")])
_cfg.player = ConfigSelection(default="4097", choices=[
    ("4097", "GStreamer (4097)"),
    ("5002", "ServiceApp exteplayer3 (5002)"),
    ("5001", "ServiceApp gstplayer (5001)")])
_cfg.codec = ConfigSelection(default="auto", choices=[
    ("auto", "H.264 first, H.265 if a clip has nothing else"),
    ("h264", "H.264 only (receivers without H.265)")])
_cfg.audio = ConfigSelection(default="fix", choices=[
    ("fix", "Fix TikTok's HE-AAC sound for this receiver"),
    ("convert", "Convert the sound with ffmpeg (MP2)"),
    ("original", "Leave the sound as it is")])
_cfg.hd = ConfigYesNo(default=False)
_cfg.on_end = ConfigSelection(default="next", choices=[
    ("next", "Play the next video"),
    ("loop", "Replay it (TikTok style)"),
    ("stop", "Stop")])
_cfg.max_age = ConfigSelection(default="7", choices=[
    ("1", "Last 24 hours"), ("3", "Last 3 days"), ("7", "Last 7 days"),
    ("14", "Last 14 days"), ("30", "Last 30 days"), ("0", "Any time")])
_cfg.per_channel = ConfigSelection(default="20", choices=[("10", "10"), ("20", "20"), ("30", "30")])
_cfg.cache_minutes = ConfigSelection(default="15", choices=[
    ("5", "5 minutes"), ("15", "15 minutes"), ("30", "30 minutes"), ("60", "1 hour")])
_cfg.show_scores = ConfigYesNo(default=True)
_cfg.show_hashtags = ConfigYesNo(default=True)
_cfg.landscape_clean = ConfigYesNo(default=True)
_cfg.arabic_fix = ConfigYesNo(default=False)
_cfg.update_check = ConfigYesNo(default=True)
_cfg.league_index = ConfigInteger(default=0, limits=(0, 99))


def main(session, **kwargs):
    try:
        from .ui_feed import SimplyScoresFeed
    except Exception as e:
        import traceback
        traceback.print_exc()
        from Screens.MessageBox import MessageBox
        session.open(MessageBox, "SimplyScores could not start:\n%s" % e, MessageBox.TYPE_ERROR)
        return
    session.open(SimplyScoresFeed)


def menu_icon():
    """150x60 icon for FHD skins, 100x40 for HD skins (the plugin browser's icon box)."""
    try:
        from enigma import getDesktop
        if getDesktop(0).size().width() >= 1920:
            return "plugin_fhd.png"
    except Exception:
        pass
    return "plugin.png"


def Plugins(**kwargs):
    description = "TikTok-style football highlights & live scores"
    return [
        PluginDescriptor(name="SimplyScores", description=description,
                         where=PluginDescriptor.WHERE_PLUGINMENU, icon=menu_icon(), fnc=main),
        PluginDescriptor(name="SimplyScores", description=description,
                         where=PluginDescriptor.WHERE_EXTENSIONSMENU, fnc=main),
    ]
