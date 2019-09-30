from typing import MutableMapping, Callable, NewType, List

Handler = NewType('Handler', Callable)


class Notifier:
    events: MutableMapping[str, List[Handler]] = {}

    @classmethod
    def notify(cls, event: str, *args, **kwargs):
        """ Notify handlers about `event`. Calls each handler with specified *args & **kwargs
            Return True if event already exists, False if event is mentioned for the first time
        """
        try:
            handlers: List[Handler] = cls.events[event]
        except KeyError:
            cls.events[event] = []
            return False
        else:
            for handler in handlers: handler(*args, **kwargs)
            return True

    @classmethod
    def addHandler(cls, event: str, handler: Callable):
        """ Add event `handler` to `event`. Handlers will be called when event will `.notify()` about itself.
            Return True if event already exists, False if event is mentioned for the first time
        """
        try:
            cls.events[event].append(handler)
        except KeyError:
            cls.events.setdefault(event, []).append(handler)
            return False
        else:
            return True
