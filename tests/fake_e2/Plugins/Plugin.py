class PluginDescriptor(object):
    WHERE_PLUGINMENU, WHERE_EXTENSIONSMENU = 1, 2

    def __init__(self, name="", description="", where=None, icon=None, fnc=None, **kw):
        self.name, self.description, self.where, self.icon, self.fnc = name, description, where, icon, fnc
