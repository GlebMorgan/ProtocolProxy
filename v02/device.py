from threading import RLock
from typing import Union, Mapping

from logger import Logger
from utils import auto_repr

from notifier import Notifier


log = Logger("Device")


class DeviceError(RuntimeError):
    """ Firmware-level error, device returned error / wrong behaviour """


class DataInvalidError(DeviceError):
    """ Device reply contains invalid data """


class BadAckError(DeviceError):
    """ DSP protocol: devise has sent 'FF' acknowledge byte => error executing command on device side """


class Par(Notifier):
    __slots__ = 'name', 'value', 'status'

    def __init__(self, name, reqType):
        super().__init__()

        self.name: str = name
        self.value: reqType = reqType()  # ◄ value requested by app
        self.status: Union[reqType, None] = None  # ◄ value obtained from device

        self.addEvent('altered')
        self.addEvent('synced')
        log.debug(f"Parameter created: {self}")

    @property
    def inSync(self):
        return self.value == self.status

    def ack(self, obtainedValue):
        if self.inSync:
            if self.value == obtainedValue: return
            else: raise DeviceError(f"Unprompted parameter change from '{self.value}' to '{obtainedValue}'")
        else:
            if self.value == obtainedValue:
                self.status = obtainedValue
                self.notify('synced', self.name, obtainedValue)

    def __get__(self, instance, owner):
        if instance is None: return self
        log.debug(f"Parameter demanded: {self}")
        return self.value

    def __set__(self, instance, newValue):
        self.value = newValue
        self.notify('altered', self.name, newValue)
        log.debug(f"Parameter altered: {self}")

    def __str__(self):
        return f"{self.name}={self.value}{'✓' if self.inSync else '↺'}"

    def __repr__(self):
        return auto_repr(self, f"{self.name}={self.value}{'✓' if self.inSync else '↻'}")


class Device:
    DEVICE_ADDRESS: int
    PARITY: str
    BAUDRATE: int
    DEFAULT_PAYLOAD: bytes
    API: Mapping[str, Par] = {}

    def wrap(self, *args, **kwargs):
        return NotImplemented

    def unwrap(self, *args, **kwargs):
        return NotImplemented

    def sendNative(self, *args, **kwargs):
        return NotImplemented

    def receiveNative(self, *args, **kwargs):
        return NotImplemented

    def ackParams(self, params: Union[dict, tuple]):
        """ 'params' must be a 'parameter_name : device_obtained_value' mapping """
        if isinstance(params, Mapping):
            for parName, checkValue in params:
                getattr(self.__class__, parName).ack(checkValue)

    # FIXME: assign proper type hints to appCom and devCom
    def __init__(self):
        self.lock = RLock()
        # TODO: fill self.API with parameters (iterate over self)

    def __iter__(self):
        yield from (value for value in vars(self.__class__).values() if isinstance(value, Par))

    def __str__(self):
        return f"{self.__class__.__name__}({', '.join((str(par) for par in self))})"

    def __repr__(self):
        return auto_repr(self, ', '.join((str(par) for par in self)))
