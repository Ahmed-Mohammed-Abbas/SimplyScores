class FakeInstance(object):
    def __init__(self):
        self.calls = []
        self.pixmap = None
        self.halign = None
        self.moved_to = None

    def setPixmap(self, ptr):
        self.pixmap = ptr

    def setHAlign(self, a):
        self.halign = a

    def move(self, point):
        self.moved_to = (point.x, point.y)

    def __getattr__(self, name):
        def record(*args):
            self.calls.append((name, args))
        return record


class GUIComponent(object):
    def __init__(self):
        self.instance = None
        self._visible = True

    def show(self):
        self._visible = True

    def hide(self):
        self._visible = False

    @property
    def visible(self):
        return self._visible
