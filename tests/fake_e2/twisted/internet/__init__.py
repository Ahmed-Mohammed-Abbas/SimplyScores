import threading


class _Reactor(object):
    """callFromThread queues the call; the test harness pumps the queue."""

    def __init__(self):
        self.queue = []
        self.lock = threading.Lock()

    def callFromThread(self, fn, *args):
        with self.lock:
            self.queue.append((fn, args))

    def pump(self):
        ran = 0
        while True:
            with self.lock:
                if not self.queue:
                    return ran
                fn, args = self.queue.pop(0)
            fn(*args)
            ran += 1


reactor = _Reactor()
