class TryQuitMainloop(object):
    def __init__(self, session, retvalue=1, **kw):
        self.retvalue = retvalue
        self.callback = None
