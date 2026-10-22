class ConfigElement(object):
    def __init__(self, default):
        self.default = default
        self.value = default
        self.saved = default

    def save(self):
        self.saved = self.value

    def cancel(self):
        self.value = self.saved


class ConfigSelection(ConfigElement):
    def __init__(self, choices, default=None):
        keys = [c[0] if isinstance(c, tuple) else c for c in choices]
        assert default in keys, default
        self.choices = keys
        ConfigElement.__init__(self, default)


class ConfigYesNo(ConfigElement):
    pass


class ConfigInteger(ConfigElement):
    def __init__(self, default=0, limits=(0, 9999)):
        ConfigElement.__init__(self, default)
        self.limits = limits


class ConfigSubsection(object):
    pass


class _ConfigFile(object):
    saves = 0

    def save(self):
        _ConfigFile.saves += 1


config = ConfigSubsection()
config.plugins = ConfigSubsection()
configfile = _ConfigFile()


def getConfigListEntry(text, element):
    return (text, element)
