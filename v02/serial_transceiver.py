import struct
from functools import wraps

import serial
from checksums import rfc1071
from utils import alias
from utils import bytewise, Logger

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
                log.warning(f"In call to {self.__class__} - 'dataname' attribute not specified")
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
        super().__init__(**config)

    def read(self, size=1):
        data = super().read(size)
        actualSize = len(data)
        if actualSize != size:
            if actualSize == 0:
                raise SerialReadTimeoutError("No reply")
            else:
                raise BadDataError("Incomplete data", data=data)
        return data

    def readSimple(self, size=1):
        return super().read(size)

    def handleSerialError(self):  # TODO: PelengTransceiver.handleSerialError()
        print(f"{self}.handleSerialError() - NotImplemented")


class PelengTransceiver(SerialTransceiver):
    AUTO_LRC = False
    HEADER_LEN: int = 6  # in bytes
    STARTBYTE: int = 0x5A
    MASTER_ADR: int = 0  # should be set in reply to host machine

    def __init__(self, device: int, master: int = MASTER_ADR, **kwargs):
        super().__init__(**kwargs)
        self.deviceAddress = device
        self.masterAddress = master
        # FIXME: make this ▼ 2 constant 'CHSUM_CHECK' + default them to True + change code in places where it is used
        self.RFC_CHECK_DISABLED = False
        self.FLUSH_UNREAD_DATA = False

    class addCRC():
        """Decorator to sendPacket() method, appending LRC byte to msg"""
        __slots__ = ('addLRC')

        def __init__(self, addLRC):
            self.addLRC = addLRC

        def __call__(self, sendPacketFunction):
            if (not self.addLRC):
                return sendPacketFunction
            else:
                from checksums import lrc

                @wraps(sendPacketFunction)
                def sendPacketWrapper(wrappee_self, msg, *args, **kwargs):
                    return sendPacketFunction(wrappee_self, msg + lrc(msg), *args, **kwargs)

                return sendPacketWrapper

    def receivePacket(self) -> bytes:
        """
        Reads packet from serial datastream and returns unwrapped data:
            Reads header and determines the length of payload data
            Reads payload and wrapper footer (checksum - 2 bytes)
            Returns payload data if header and data lengths + header and packet checksums are OK. Raises error otherwise
        If header is not contained in very first bytes of datastream, sequentially reads bytes portions of header length
        until valid header is found. Raise error otherwise.
        No extra data is grabbed from datastream after valid packet is successfully read.

        :raises: SerialError, SerialReadTimeoutError, BadDataError, RuntimeError
        :return: unwrapped high-level data
        :rtype: bytes
        """

        bytesReceived = self.read(self.HEADER_LEN)

        # TODO: byteorder here ▼ and everywhere - ?
        if (len(bytesReceived) == self.HEADER_LEN and bytesReceived[0] == self.STARTBYTE and
                (self.RFC_CHECK_DISABLED or int.from_bytes(rfc1071(bytesReceived), byteorder='big') == 0)):
            header = bytesReceived
            return self.__readData(header)
        elif (len(bytesReceived) == 0):
            raise SerialReadTimeoutError("No reply")
        elif (len(bytesReceived) < self.HEADER_LEN):
            raise BadDataError(f"Bad header (too small, [{len(bytesReceived)}] out of [{self.HEADER_LEN}])",
                               dataname="Header", data=bytesReceived)
        else:
            if (bytesReceived[0] == self.STARTBYTE):
                log.warning(f"Bad header checksum (expected '{bytewise(rfc1071(bytesReceived[:-2]))}', "
                            f"got '{bytewise(bytesReceived[-2:])}'). Header discarded, searching for valid one...")
            else:
                log.warning(f"Bad data in front of the stream: [{bytewise(bytesReceived)}]. "
                            f"Searching for valid header...")
            for i in range(1, 100):  # TODO: limit infinite loop in a better way
                while True:
                    startbyteIndex = bytesReceived.find(self.STARTBYTE)
                    if (startbyteIndex == -1):
                        if (len(bytesReceived) < self.HEADER_LEN):
                            raise BadDataError("Failed to find valid header",
                                               dataname="Header", data=bytesReceived)
                        bytesReceived = self.readSimple(self.HEADER_LEN)
                        log.warning(f"Try next {self.HEADER_LEN} bytes: [{bytewise(bytesReceived)}]")
                    else: break
                headerReminder = self.readSimple(startbyteIndex)
                if (len(headerReminder) < startbyteIndex):
                    raise BadDataError("Bad header", dataname="Header",
                                       data=bytesReceived[startbyteIndex:] + headerReminder)
                header = bytesReceived[startbyteIndex:] + headerReminder
                if (self.RFC_CHECK_DISABLED or int.from_bytes(rfc1071(header), byteorder='big') == 0):
                    log.info(f"Found valid header at pos {i * self.HEADER_LEN + startbyteIndex}")
                    return self.__readData(header)
                else: bytesReceived = self.readSimple(self.HEADER_LEN)
            else: raise SerialCommunicationError("Cannot find header in datastream, too many attempts...")
        # TODO: still have unread data at the end of the serial stream sometimes.
        # scenario that once caused the issue: send 'ms 43 0' without adding a signal value (need to alter the code)

    def __readData(self, header):
        datalen, zerobyte = self.__parseHeader(header)
        data = self.read(datalen + 2)  # 2 is wrapper RFC
        if (len(data) < datalen + 2):
            raise BadDataError(f"Bad packet (data too small, [{len(data)}] out of [{datalen + 2}])",
                               dataname="Packet", data=header + data)
        if (self.RFC_CHECK_DISABLED or int.from_bytes(rfc1071(header + data), byteorder='big') == 0):
            slog.debug(f"Reply packet [{len(header + data)}]: {bytewise(header + data)}")
            if (self.in_waiting != 0):
                log.warning(f"Unread data ({self.in_waiting} bytes) is left in a serial datastream")
                if (self.FLUSH_UNREAD_DATA):
                    self.reset_input_buffer()
                    log.info(f"Serial input buffer flushed")
            return data[:-2] if (not zerobyte) else data[:-3]  # 2 is packet RFC, 1 is zero padding byte
        else:
            raise BadRfcError(f"Bad packet checksum (expected '{bytewise(rfc1071(data[:-2]))}', "
                              f"got '{bytewise(data[-2:])}'). Packet discarded",
                              dataname="Packet", data=header + data)

    def __parseHeader(self, header):
        assert (len(header) == self.HEADER_LEN)
        assert (header[0] == self.STARTBYTE)

        # unpack header (fixed structure - 6 bytes)
        fields = struct.unpack('< B B H H', header)
        if (fields[1] != self.masterAddress):
            # FIXME: what is this error?
            raise ValueError(f"Wrong master address (expected '{self.masterAddress}', got '{fields[1]}')")
        datalen = (fields[2] & 0x0FFF) * 2  # extract size in bytes, not 16-bit words
        zerobyte = (fields[2] & 1 << 15) >> 15  # extract EVEN flag (b15 in LSB / b7 in MSB)
        log.debug(f"ZeroByte: {zerobyte == 1}")
        return datalen, zerobyte

    @addCRC(AUTO_LRC)
    def sendPacket(self, msg):
        """
        Wrap msg and send packet over serial port
        For DspAssist protocol - if AUTO_LRC is False, it is assumed that LRC byte is already appended to msg

        :param msg: binary payload data
        :type msg: bytes
        :return: bytes written count
        :rtype: int
        """

        datalen = len(msg)  # get data size in bytes
        assert (datalen <= 0xFFF)
        assert (self.deviceAddress <= 0xFF)
        zerobyte = b'\x00' if (datalen % 2) else b''
        datalen += len(zerobyte)
        # below: data_size = datalen//2 ► translate data size in 16-bit words
        header = struct.pack('< B B H', self.STARTBYTE, self.deviceAddress, (datalen // 2) | (len(zerobyte) << 15))
        packet = header + rfc1071(header) + msg + zerobyte
        packetToSend = packet + rfc1071(packet)
        bytesSentCount = self.write(packetToSend)
        slog.debug(f"Packet [{len(packetToSend)}]: {bytewise(packetToSend)}")
        return bytesSentCount
