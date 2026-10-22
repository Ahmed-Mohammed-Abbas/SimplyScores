import os


def LoadPixmap(path, desktop=None, cached=False, **kw):
    if path and os.path.exists(path):
        return ("ptr", path)
    return None
