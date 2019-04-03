import serial
from utils import alias, Logger

# TESTME: does log and slog here and in PelengTransceiver actually connected (they should)
log = Logger("Serial")
slog = Logger("Packets")

# ▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼ ERRORS ▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼ #

SerialError = alias(serial.serialutil.SerialException)


SerialWriteTimeoutError = alias(serial.serialutil.SerialTimeoutException)
SerialWriteTimeoutError.__doc__ = """ Failed to send data for 'Serial().write_timeout' seconds """


class SerialReadTimeoutError(SerialError):
    """ No data is received for 'Serial().timeout' seconds """


class SerialCommunicationError(SerialError):
    """ Communication-level error, indicate failure in packet transmission process """
    __slots__ = ()

    def __init__(self, *args, data=None, dataname=None):
        if (data is not None):
            if (dataname is None):
                log.error(f"In call to {self.__class__} - 'dataname' attribute not specified")
                self.dataname = "Analyzed data"
            else: self.dataname = dataname
            self.data = data
        super().__init__(*args)


class BadDataError(SerialCommunicationError):
    """ Data received over serial port is corrupted """


class BadRfcError(SerialCommunicationError):
    """ RFC checksum validation failed """


class BadLrcError(SerialCommunicationError):
    """ DSP protocol: LRC checksum validation failed """


class DeviceError(RuntimeError):
    """ Firmware-level error, indicate the command sent to the device was not properly executed """


class DataInvalidError(DeviceError):
    """ Device reply contains invalid data """


class BadAckError(DeviceError):
    """ DSP protocol: devise has sent 'FF' acknowledge byte => error executing command on device side """


# TODO: move def of this error to Application class
class CommandError(RuntimeError):
    """ Application-level error, indicates invalid command signature / parameters / semantics """

# ▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲ ERRORS ▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲ #


class SerialTransceiver(serial.Serial):
    DEFAULT_CONFIG = {
        'port': 'COM1',
        'baudrate': 921600,
        'bytesize': serial.EIGHTBITS,
        'parity': serial.PARITY_NONE,
        'stopbits': serial.STOPBITS_ONE,
        'timeout': 0.5,
        'write_timeout': 0.5,
    }

    def __init__(self, **kwargs):
        config = self.DEFAULT_CONFIG
        config.update(kwargs)
        super().__init__(config, **kwargs)

    def read(self, size=1):
        data = super().read(size)
        actualSize = len(data)
        if actualSize != size:
            if actualSize == 0:
                raise SerialReadTimeoutError("No reply")
            else:
                raise BadDataError("Incomplete data")
        return data

    def readSimple(self, size=1):
        return super().read(size)

    def handleSerialError(self):  # TODO: PelengTransceiver.handleSerialError()
        print(f"{self}.handleSerialError() is NotImplemented")
