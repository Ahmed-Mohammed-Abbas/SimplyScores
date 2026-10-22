from Components.GUIComponent import GUIComponent


class ScrollLabel(GUIComponent):
    def __init__(self, text=""):
        GUIComponent.__init__(self)
        self.text = text
        self.page = 0

    def setText(self, text):
        assert isinstance(text, str)
        self.text = text

    def getText(self):
        return self.text

    def pageUp(self):
        self.page = max(0, self.page - 1)

    def pageDown(self):
        self.page += 1
