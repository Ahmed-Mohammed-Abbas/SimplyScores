class Console(object):
    def __init__(self, session, title="Console", cmdlist=None, **kw):
        self.title, self.cmdlist = title, cmdlist or []
        self.callback = None
