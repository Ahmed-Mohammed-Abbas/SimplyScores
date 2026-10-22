from Components.GUIComponent import GUIComponent


class Label(GUIComponent):
    def __init__(self, text=""):
        GUIComponent.__init__(self)
        self.text = text

    def setText(self, text):
        assert isinstance(text, str), "Label text must be str, got %r" % (text,)
        self.text = text

    def getText(self):
        return self.text
