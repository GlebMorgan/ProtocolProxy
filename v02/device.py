from threading import RLock
from typing import Union, Mapping, TypeVar
from Utils import Logger, auto_repr

from notifier import Notifier

log = Logger("Device")


class DeviceError(RuntimeError):
    """ Firmware-level error, device returned error / wrong behaviour """


class DataInvalidError(DeviceError):
    """ Device reply contains invalid data """


class BadAckError(DeviceError):
    """ DSP protocol: devise has sent 'FF' acknowledge byte => error executing command on device side """


ParType = TypeVar('ParType', str, int, float, bool)
PropType = TypeVar('PropType', str, int, float, bool)


class Par(Notifier):
    """ App-defined """

    __slots__ = 'name', 'alias', 'value', 'status', 'type'

    def __init__(self, alias: str, reqType: type):
        super().__init__()
        self.alias = alias
        self.type: type = reqType
        self.value: ParType = reqType()  # ◄ value requested by app
        self.status: ParType = None  # ◄ value obtained from device

    def __set_name__(self, owner, name):
        self.name = name
        log.debug(f"Parameter created: {self}")

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

    @property
    def inSync(self) -> bool:
        return self.value == self.status

    def ack(self, obtainedValue: ParType):
        if self.inSync:
            if self.value != obtainedValue:
                log.warning(f"Unprompted parameter change from '{self.value}' to '{obtainedValue}'")
        else:
            if self.value == obtainedValue:
                self.status = obtainedValue
                self.notify('updated', self.name, obtainedValue)


class Prop(Notifier):
    """ Device-defined """

    __slots__ = 'name', 'alias', 'value'

    def __init__(self, alias: str, reqType: type):
        super().__init__()
        self.alias = alias
        self.value: ParType = reqType()

    def __set_name__(self, owner, name):
        self.name = name
        log.debug(f"Property created: {self}")

    def __get__(self, instance, owner):
        if instance is None: return self
        log.debug(f"Property demanded: {self}")
        return self.value

    def __set__(self, instance, newValue):
        if self.value != newValue:
            self.value = newValue
            self.notify('updated', self.name, newValue)
            log.debug(f"Property updated: {self}")

    def __str__(self):
        return f"{self.name}={self.value}"

    def __repr__(self):
        return auto_repr(self, f"{self.name}={self.value}")


class Device:
    DEV_ADDRESS: int
    DEV_BAUDRATE: int = 921600
    DEV_BYTESIZE: int = 8
    DEV_PARITY: str = 'N'
    DEV_STOPBITS: int = 1
    DEV_TIMEOUT: float = 0.5
    DEV_WRITE_TIMEOUT: float = 0.5
    DEV_MAX_INPUT_BUFFER_SIZE: int = 255

    APP_BAUDRATE: int
    APP_BYTESIZE: int = 8
    APP_PARITY: int
    APP_STOPBITS: int = 1
    APP_TIMEOUT: int
    APP_WRITE_TIMEOUT: int = 0.5
    APP_MAX_INPUT_BUFFER_SIZE: int = 255

    DEFAULT_PAYLOAD: bytes  # accepted for future redesigns — use 'IDLE_PAYLOAD' instead
    IDLE_PAYLOAD: bytes  # should not change device state when sent to device (init with default payload)
    COMMUNICATION_INTERFACE: str  # name of physical communication interface

    API: Mapping[str, Union[Par, Prop]] = None  # device control external API

    def wrap(self, data: bytes) -> bytes:
        return NotImplemented

    def unwrap(self, packet: bytes) -> bytes:
        return NotImplemented

    def sendNative(self, transceiver, data: bytes) -> int:
        return NotImplemented

    def receiveNative(self, transceiver) -> bytes:
        return NotImplemented

    def getPar(self, parName):  # NOTE: not tested
        return getattr(self.__class__, parName)

    def ackParams(self, params: Union[dict, tuple]):  # NOTE: not tested
        """ 'params' must be a 'parameter_name : device_obtained_value' mapping """
        if isinstance(params, Mapping):
            for parName, checkValue in params:
                getattr(self.__class__, parName).ack(checkValue)

    def configureInterface(self, appInterface, devInterface):
        if (self.COMMUNICATION_INTERFACE == 'serial'):
            for par, value in self.__class__.__dict__.items():
                if par.startswith('DEV_'):
                    attr = par.lstrip('DEV_').lower()
                    interface = devInterface
                elif par.startswith('APP_'):
                    attr = par.lstrip('APP_').lower()
                    interface = appInterface
                else: continue
                setattr(interface, attr, value)
            devInterface.deviceAddress = self.DEV_ADDRESS
            log.info(f"In/out {self.COMMUNICATION_INTERFACE} interfaces reconfigured for {self.name} protocol")
        else: raise NotImplementedError(f"Interface {self.COMMUNICATION_INTERFACE} is not supported")

    def __init__(self):
        self.lock = RLock()
        self.name = self.__class__.__name__
        self.params = tuple(slot for slot in vars(self.__class__).values() if isinstance(slot, Par))
        self.API = {slot.alias: slot for slot in vars(self.__class__).values() if isinstance(slot, (Par, Prop))}

    def __iter__(self):
        yield from self.API.values()

    def __str__(self):
        return f"{self.__class__.__name__}{'✓' if all(par.inSync for par in self.params) else '↺'} " \
               f"({', '.join((str(slot) for slot in self))})"

    def __repr__(self):
        return auto_repr(self, '✓' if all(par.inSync for par in self.params) else '↺')
