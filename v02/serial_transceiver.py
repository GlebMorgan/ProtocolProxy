import struct
from functools import wraps

import serial
from checksums import rfc1071
from logger import Logger
from utils import alias, bytewise, VerboseError

log = Logger("Serial")
slog = Logger("Packets")

# CONSIDER: move all SerialCommunication-related errors to Transceiver class (interface)
#           and import it into utilizing classes to allow interface definition and raising proper error types

# ▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼ ERRORS ▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼ #


SerialError = alias(serial.serialutil.SerialException)

SerialWriteTimeoutError = alias(serial.serialutil.SerialTimeoutException)
SerialWriteTimeoutError.__doc__ = """ Failed to send data for 'Serial().write_timeout' seconds """


class SerialReadTimeoutError(SerialError):
    """ No data is received for 'Serial().timeout' seconds """


class AddressMismatchError(SerialError):
    """ Address defined in header does not match with host address """


class SerialCommunicationError(VerboseError, SerialError):
    """ Communication-level error, indicate failure in packet transmission process """


class BadDataError(SerialCommunicationError):
    """ Data received over serial port is corrupted """


class BadRfcError(SerialCommunicationError):
    """ RFC checksum validation failed """


class BadLrcError(SerialCommunicationError):
    """ DSP protocol: LRC checksum validation failed """


# ▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲ ERRORS ▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲ #

# COMMAND PACKET STRUCTURE
# 1           2     3:4           5:6         7:8       9:...         -3    -2:-1
# StartByte   ADR   Length|EVEN   HeaderRFC   COMMAND   CommandData   LRC   PacketRFC

# REPLY PACKET STRUCTURE
# 1           2     3:4           5:6         7          10:...      -3    -2:-1
# StartByte   ADR   Length|EVEN   HeaderRFC   ACK byte   ReplyData   LRC   PacketRFC


class SerialTransceiver(serial.Serial):
    INTERFACE_NAME = 'serial'
    DEFAULT_CONFIG = {
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
        log.setLevel("WARNING")
        self.nTimeouts = 0

    @property
    def token(self) -> str:
        if not self.port: return self.INTERFACE_NAME.capitalize() + ': ' + 'closed'
        return self.INTERFACE_NAME.capitalize() + ': ' + self.port

    def __enter__(self):
        try:
            this = super().__enter__()
        except SerialError as e:
            self.handleSerialError(e)
            return self
        return this

    def read(self, size=1) -> bytes:
        data = super().read(size)
        actualSize = len(data)
        if actualSize != size:
            if actualSize == 0:
                raise SerialReadTimeoutError("No reply")
            else:
                raise BadDataError("Incomplete data", data=data)
        return data

    def readSimple(self, size=1) -> bytes:
        return super().read(size)

    @staticmethod
    def handleSerialError(error):
        if ("Port is already open." == error.args[0]):
            log.warning("Attempt opening already opened port - error skipped")
            return
        comPortName = error.args[0].split("'", maxsplit=2)[1]
        if ('PermissionError' in error.args[0]):
            raise SerialCommunicationError(f"Cannot open port '{comPortName}' - interface is occupied "
                                           f"by another recourse (different app is using that port?)")
        if ('FileNotFoundError' in error.args[0]):
            raise SerialCommunicationError(f"Cannot open port '{comPortName}' - "
                                           f"interface does not exist (device unplugged?)")


class PelengTransceiver(SerialTransceiver):
    AUTO_LRC: bool = False
    HEADER_LEN: int = 6  # in bytes
    STARTBYTE: int = 0x5A
    MASTER_ADR: int = 0  # should be set in reply to host machine

    chch_packet_out: bytes = '5A 0C 06 80 9F 73 01 01 A8 AB AF AA AC AB A3 AA 08 00 4E 52'
    chch_command: bytes = '01 01 A8 AB AF AA AC AB A3 AA 08'
    chch_packet_in: bytes = '5A 00 06 80 9F 7F 01 01 A8 AB AF AA AC AB A3 AA 08 00 4E 52'
    chch_reply: bytes = '01 01 A8 AB AF AA AC AB A3 AA 08'

    def __init__(self, device: int = None, master: int = MASTER_ADR, **kwargs):
        super().__init__(**kwargs)
        self.deviceAddress = device
        self.masterAddress = master

        self.CHECK_RFC: bool = True
        self.FLUSH_UNREAD_DATA: bool = False
        self.ADDRESS_MISMATCH_ACTION: str = 'WARN&DENY'

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
        """

        bytesReceived = self.readSimple(self.HEADER_LEN)

        # TODO: byteorder here ▼ and everywhere - ?
        if (len(bytesReceived) == self.HEADER_LEN and bytesReceived[0] == self.STARTBYTE and
                (not self.CHECK_RFC or int.from_bytes(rfc1071(bytesReceived), byteorder='big') == 0)):
            header = bytesReceived
            try:
                return self.__readData(header)
            except AddressMismatchError: return self.receivePacket()
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
            header = bytesReceived
            for i in range(1, 100):  # TODO: limit infinite loop in a better way
                while True:
                    startbyteIndex = header.find(self.STARTBYTE, 1)  # ignore byte at position 0, it is not a startbyte
                    if (startbyteIndex == -1):
                        header = self.readSimple(self.HEADER_LEN)
                        log.debug(f"Try next {self.HEADER_LEN} bytes: [{bytewise(header)}]")
                        if (len(header) < self.HEADER_LEN):
                            raise BadDataError("Failed to find valid header",
                                               dataname="Header", data=header)

                    else: break
                headerReminder = self.readSimple(startbyteIndex)
                header = header[startbyteIndex:] + headerReminder
                log.debug(f"Try appending {startbyteIndex} more bytes: [{bytewise(header)}]")
                if (len(headerReminder) < startbyteIndex):
                    raise BadDataError("Bad header", dataname="Header", data=header)
                if (not self.CHECK_RFC or int.from_bytes(rfc1071(header), byteorder='big') == 0):
                    log.info(f"Found valid header at pos {i * self.HEADER_LEN + startbyteIndex}")
                    try: return self.__readData(header)
                    except AddressMismatchError: self.receivePacket()
            else: raise SerialCommunicationError("Cannot find header in datastream, too many attempts...")
        # TODO: Still have unread data at the end of the serial stream sometimes.
        #       Action that once caused the issue: sent 'ms 43 0' without adding a signal value (need to alter the code)

    def __readData(self, header):
        datalen, zerobyte = self.__parseHeader(header)
        data = self.read(datalen + 2)  # 2 is wrapper RFC
        if (len(data) < datalen + 2):
            raise BadDataError(f"Bad packet (data too small, [{len(data)}] out of [{datalen + 2}])",
                               dataname="Packet", data=header + data)
        if (not self.CHECK_RFC or int.from_bytes(rfc1071(header + data), byteorder='big') == 0):
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
        datalen = (fields[2] & 0x0FFF) * 2  # extract size in bytes, not 16-bit words
        zerobyte = (fields[2] & 1 << 15) >> 15  # extract EVEN flag (b15 in LSB / b7 in MSB)
        log.debug(f"ZeroByte: {zerobyte == 1}")
        if (fields[1] != self.masterAddress):
            message = f"Unexpected master address (expected '{self.masterAddress}', got '{fields[1]}')"
            if self.ADDRESS_MISMATCH_ACTION in ('WARN&DENY', 'WARN'):
                log.warning(message)
            if self.ADDRESS_MISMATCH_ACTION in ('WARN&DENY', 'DENY'):
                # read current packet to the end, reject it and restart receivePacket method
                try: self.read(datalen + 2)
                except SerialError: pass
                raise AddressMismatchError(fields[1])
            elif self.ADDRESS_MISMATCH_ACTION == 'ERROR':  # interrupt transaction — raise SerialCommunicationError
                raise SerialCommunicationError(message)
        return datalen, zerobyte

    @addCRC(AUTO_LRC)
    def sendPacket(self, msg:bytes) -> int:
        """ Wrap msg and send packet over serial port. Return number of bytes sent
            For DspAssist protocol - if AUTO_LRC is False, it is assumed that LRC byte is already appended to msg """

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
