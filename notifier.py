from typing import Callable

import utils

log = utils.getLogger(__name__)


class Notifier:

    def __init__(self):
        self.handlers = []

    def attach(self, callable_handler: Callable):
        self.handlers.append(callable_handler)

    def detach(self, callable_handler):
        try:
            self.handlers.pop(callable_handler)
        except IndexError:
            log.warning(f"Handlers list does not contain callable {callable_handler.__name__}")

    def notify(self, *args, **kwargs):
        for handler in self.handlers:
            handler.__call__(*args, **kwargs)
