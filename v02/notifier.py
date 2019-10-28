from typing import MutableMapping, Callable, NewType, List

from Utils import Logger
from orderedset import OrderedSet

# TODO: make events lifecycle same as object that added them
#   (delete events together with object removing since it cannot initiate those events anymore regardless)

log = Logger('Notifier')
log.setLevel('DEBUG')

# True ––► .notify() and .addHandler() will work only for existing events (no dynamic event creation)
# False ––► .notify() and .addHandler() executed on non-existent event will create new one on-the-fly
REQUIRE_REGISTER = True

Handler = NewType('Handler', Callable)


class Notifier:
    events: MutableMapping[str, OrderedSet] = {}

    @classmethod
    def addEvents(cls, *events: str, unique: bool = False):
        for event in events:
            if event in cls.events and unique is True:
                raise ValueError(f"Event '{event}' already exists")
            cls.events[event] = OrderedSet()

    @classmethod
    def notify(cls, event: str, *args, **kwargs):
        """ Notify handlers about `event`. Calls each handler with specified *args & **kwargs
            Return True if event already exists, False if event is mentioned for the first time
        """
        try:
            handlers: List[Handler] = cls.events[event]
        except KeyError:
            if REQUIRE_REGISTER:
                raise ValueError(f"Event '{event}' have not been registered")
            else:
                cls.addEvents(event)
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
            cls.events[event].add(handler)
        except KeyError:
            if REQUIRE_REGISTER:
                raise ValueError(f"Event '{event}' have not been registered")
            else:
                cls.events.setdefault(event, OrderedSet()).add(handler)
            return False
        else:
            return True
