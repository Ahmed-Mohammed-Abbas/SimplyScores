class MessageBox(object):
    TYPE_YESNO, TYPE_INFO, TYPE_WARNING, TYPE_ERROR = 0, 1, 2, 3

    def __init__(self, session, text, type=1, timeout=-1, **kw):
        assert isinstance(text, str)
        self.text, self.type = text, type
        self.callback = None
