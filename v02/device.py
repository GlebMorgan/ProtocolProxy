from threading import RLock
from typing import Union, Mapping, TypeVar

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


ParType = TypeVar('ParType', str, int, float, bool)


class Par(Notifier):
    __slots__ = 'name', 'alias', 'value', 'status'


    def __init__(self, name: str, alias: str, reqType: type):
        super().__init__()

        self.name = name
        self.alias = alias
        self.value: ParType = reqType()  # ◄ value requested by app
        self.status: reqType = None  # ◄ value obtained from device

        self.addEvent('altered')
        self.addEvent('synced')
        log.debug(f"Parameter created: {self}")

    @property
    def inSync(self) -> bool:
        return self.value == self.status

    def ack(self, obtainedValue: ParType):
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
    # TODO: add Prop class that will contain state variables (like CNT_OUT) and add them to API
    DEVICE_ADDRESS: int
    DEVICE_MAX_INPUT_BUFFER_SIZE: int = 255
    NATIVE_PARITY: str
    NATIVE_BAUDRATE: int
    NATIVE_MAX_INPUT_BUFFER_SIZE: int = 255
    DEFAULT_PAYLOAD: bytes  # accepted for future redesigns — use 'IDLE_PAYLOAD' instead
    IDLE_PAYLOAD: bytes  # should not change device state when sent to device (init with default payload)
    COMMUNICATION_INTERFACE: str  # name of physical communication interface
    API: Mapping[str, Par] = None  # device control external API

    def wrap(self, data: bytes) -> bytes:
        return NotImplemented

    def unwrap(self, packet: bytes) -> bytes:
        return NotImplemented

    def sendNative(self, transceiver, data: bytes) -> int:
        return NotImplemented

    def receiveNative(self, transceiver) -> bytes:
        return NotImplemented

    def ackParams(self, params: Union[dict, tuple]):
        """ 'params' must be a 'parameter_name : device_obtained_value' mapping """
        if isinstance(params, Mapping):
            for parName, checkValue in params:
                getattr(self.__class__, parName).ack(checkValue)

    def configureInterface(self, applicationInterface, deviceInterface):
        if (self.COMMUNICATION_INTERFACE == 'serial'):
            deviceInterface.deviceAddress = self.DEVICE_ADDRESS
            applicationInterface.parity = self.NATIVE_PARITY
            applicationInterface.baudrate = self.NATIVE_BAUDRATE
            log.info(f"Interfaces {applicationInterface.__class__.__name__} and {deviceInterface.__class__.__name__} "
                     f"reconfigured for {self.name} protocol")

    def __init__(self):
        self.lock = RLock()
        self.name = self.__class__.__name__
        self.API = {par.alias: par for par in self}  # TESTME

    def __iter__(self):
        # TODO: redesign —> iterate on self.API dict
        yield from (value for value in vars(self.__class__).values() if isinstance(value, Par))

    def __str__(self):
        return f"{self.__class__.__name__}({', '.join((str(par) for par in self))})"

    def __repr__(self):
        return auto_repr(self, ', '.join((str(par) for par in self)))
