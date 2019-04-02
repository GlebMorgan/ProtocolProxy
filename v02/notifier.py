from typing import MutableMapping


class Notifier:
    __slots__ = 'events',

    def __init__(self):
        self.events: MutableMapping[str, list] = {}

    def notify(self, event: str, *args, **kwargs):
        for handler in self.events[event]:
            handler(*args, **kwargs)

    def addEvent(self, event: str):
        self.events[event] = []
