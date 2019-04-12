from abc import ABC


class Transceiver(ABC):
    token: str
    nTimeouts: int

    def __new__(cls, *args, **kwargs):
        raise SyntaxError(f"Class {cls.__name__} is an interface")

    def read(self) -> bytes: ...

    def write(self, data: bytes) -> int: ...