class Screen(dict):
    def __init__(self, session):
        dict.__init__(self)
        self.session = session
        self.onLayoutFinish = []
        self.onClose = []
        self.onShown = []
        self.closed = False
        self.retval = None
        self.callback = None

    def close(self, *retval):
        assert not self.closed, "screen closed twice"
        self.closed = True
        for fn in self.onClose:
            fn()
        self.retval = retval
        if self.callback:
            self.callback(*retval)

    def setTitle(self, title):
        self.title = title
