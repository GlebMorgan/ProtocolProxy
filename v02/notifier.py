from typing import MutableMapping, Callable


class Notifier:
    __slots__ = 'events',

    def __init__(self):
        self.events: MutableMapping[str, list] = {}

    def notify(self, event: str, *args, **kwargs):
        try:
            handlers = self.events[event]
        except KeyError:
            raise AssertionError(f"Notifier.notify() is called on non-existing event '{event}'")
        for handler in handlers: handler(*args, **kwargs)

    def addHandler(self, event: str, handler: Callable):
        try:
            self.events[event].append(handler)
        except KeyError:
            self.events[event] = []
            self.addHandler(event, handler)
