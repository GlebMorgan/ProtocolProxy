import threading
from notifier import Notifier
from serial_transceiver import DeviceError


class Protocol():
    DEVICE_ADDRESS: int
    PARITY: str
    BAUDRATE: int
    flagAliases: dict

    def __init__(self):
        object.__setattr__(self, 'params', {})
        self.lock = threading.RLock()
        super().__init__()

    def wrap(self, *args, **kwargs):
        return NotImplemented

    def unwrap(self, *args, **kwargs):
        return NotImplemented

    def readNative(self, *args, **kwargs):
        return NotImplemented

    def communicate(self, *args, **kwargs):
        return NotImplemented

    def _setPar(self, name, value):
        par = getattr(self, name)
        par.value = value
        par.inSync = False
        par.notify('altered', name, value)

    def _getPar(self, name):
        return getattr(self, name).value

    def __getattribute__(self, name):
        if name in object.__getattribute__(self, 'params'):
            return object.__getattribute__(self, 'params')[name].__getattribute__('get').__call__()
        return super().__getattribute__(name)

    def __setattr__(self, name, value):
        if isinstance(value, Par):
            value._name = name
            self.params[name] = value
        elif name in self.params:
            self.params[name].set(value)
        super().__setattr__(name, value)

    def __str__(self):
        return f"{self.__class__.__name__} ({', '.join(f'{name}={getattr(self, name)}' for name in self.params)})"


class Par(Notifier):

    def __init__(self, reqType):
        super().__init__()
        self._name = None
        self._value = reqType()
        self.inSync: bool = False

    def ack(self, value):
        if self.inSync:
            if self._value == value: return
            else: raise DeviceError(f"Unprompted parameter change from {self._value} to {value}")
        else:
            if self._value == value:
                self.inSync = True
                self.notify('synced', self._name, value)

    @property
    def v(self):
        return self._value

    @v.setter
    def v(self, value):
        self._value = value
        self.inSync = False
        self.notify('altered', self._name, value)

    def get(self):
        return self._value

    def set(self, value):
        self._value = value
        self.inSync = False
        self.notify('altered', self._name, value)

    def __str__(self):
        return str(self._value)

    def __repr__(self):  # TODO: change this to use autorepr
        return f"{self._value}{'✓' if self.inSync else '✗'}"
