from Components.GUIComponent import GUIComponent


class ProgressBar(GUIComponent):
    def __init__(self):
        GUIComponent.__init__(self)
        self.value = 0

    def setValue(self, v):
        assert 0 <= v <= 100
        self.value = v
