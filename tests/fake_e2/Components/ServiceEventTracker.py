class ServiceEventTracker(object):
    def __init__(self, screen, eventmap):
        self.eventmap = eventmap
        screen._eventmap = eventmap
