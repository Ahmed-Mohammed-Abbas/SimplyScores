from Components.GUIComponent import GUIComponent


class ConfigList(GUIComponent):
    def __init__(self, lst):
        GUIComponent.__init__(self)
        self.list = lst


class ConfigListScreen(object):
    def __init__(self, list, session=None, on_change=None, fullUI=False):
        self["config"] = ConfigList(list)
