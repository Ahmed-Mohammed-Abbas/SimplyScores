class VirtualKeyBoard(object):
    def __init__(self, session, title="", text="", **kw):
        self.title, self.text = title, text
        self.callback = None
