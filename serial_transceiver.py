from __future__ import annotations

import logging
import struct

import serial
import utils
from checksums import rfc1071
from colored_logger import ColorHandler
from utils import bytewise

log = utils.getLogger(__name__)

# —————————————————————————————————————————————————————————————————————————————————————————————————————————————————————


SerialError = serial.serialutil.SerialException

SerialWriteTimeoutError = serial.serialutil.SerialTimeoutException


class SerialReadTimeoutError(SerialError): __slots__ = ()


class SerialCommunicationError(SerialError):
    """Communication-level error, indicate failure in packet transmission process"""
    __slots__ = ()

    def __init__(self, *args, data=None, dataname=None):
        if (data is not None):
            if (dataname is None):
                log.error(f"In call to {self.__class__} - 'dataname' attribute not specified")
                self.dataname = "Analyzed data"
            else: self.dataname = dataname
            self.data = data
        super().__init__(*args)


class DeviceError(RuntimeError):
    """Firmware-level error, indicate the command sent to the device was not properly executed"""
    __slots__ = ()


class SerialTransceiver(serial.Serial):
    DEFAULT_COM = 'COM1'
    DEFAULT_PARITY = serial.PARITY_NONE
    DEFAULT_BAUDRATE = 921600
    TIMEOUT = 0.5
    HEADER_LEN = 6  # in bytes
    STARTBYTE: int = 0x5A
    MASTER_ADDRESS = 0  # should be in reply to host machine
    RFC_CHECK_DISABLED = True
    LRC_CHECK_DISABLED = False

    def __init__(self, devAddr, port=DEFAULT_COM, baudrate=DEFAULT_BAUDRATE, parity=DEFAULT_PARITY,
                 timeout=TIMEOUT, write_timeout=TIMEOUT, **kwargs):
        self.deviceAddress = devAddr
        super().__init__(port=port, baudrate=baudrate, parity=parity,
                         timeout=timeout, write_timeout=write_timeout, **kwargs)

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

        bytesReceived = self.read(self.HEADER_LEN)

        if (len(bytesReceived) == self.HEADER_LEN and bytesReceived[0] == self.STARTBYTE and
                (self.RFC_CHECK_DISABLED or int.from_bytes(rfc1071(bytesReceived), byteorder='big') == 0)):
            header = bytesReceived
            return self.__readData(header)
        elif (len(bytesReceived) == 0):
            raise SerialReadTimeoutError("No reply")
        elif (len(bytesReceived) < self.HEADER_LEN):
            raise SerialCommunicationError(f"Bad header (too small, [{len(bytesReceived)}] out of [{self.HEADER_LEN}])",
                                           dataname="Header", data=bytesReceived)
        else:
            if (bytesReceived[0] == self.STARTBYTE):
                log.warning(f"Bad header checksum (expected '{bytewise(rfc1071(bytesReceived[:-2]))}', "
                            f"got '{bytewise(bytesReceived[-2:])}'). Header discarded, searching for valid one...",
                            dataname="Header", data=bytesReceived)
            else:
                log.warning(f"Bad data in front of the stream: [{bytewise(bytesReceived)}]. "
                            f"Searching for valid header...")
            for i in range(1, 100):
                while True:
                    startbyteIndex = bytesReceived.find(self.STARTBYTE)
                    if (startbyteIndex == -1):
                        if (len(bytesReceived) < self.HEADER_LEN):
                            raise SerialCommunicationError("Failed to find valid header")
                        bytesReceived = self.read(self.HEADER_LEN)
                        log.warning(f"Try next {self.HEADER_LEN} bytes: [{bytewise(bytesReceived)}]")
                    else: break
                headerReminder = self.read(startbyteIndex)
                if (len(headerReminder) < startbyteIndex):
                    raise SerialCommunicationError("Bad header", dataname="Header",
                                                   data=bytesReceived[startbyteIndex:] + headerReminder)
                header = bytesReceived[startbyteIndex:] + headerReminder
                if (self.RFC_CHECK_DISABLED or int.from_bytes(rfc1071(header), byteorder='big') == 0):
                    log.info(f"Found valid header at pos {i * self.HEADER_LEN + startbyteIndex}")
                    return self.__readData(header)
            else: raise SerialCommunicationError("Cannot find header in datastream, too many attempts...")

    def __readData(self, header):
        datalen, zerobyte = self.__parseHeader(header)
        data = self.read(datalen + 2)  # 2 is wrapper RFC
        if (len(data) < datalen + 2):
            raise SerialCommunicationError(f"Bad packet (data too small, [{len(data)}] out of [{datalen + 2}])",
                                           dataname="Packet", data=header + data)
        if (self.RFC_CHECK_DISABLED or int.from_bytes(rfc1071(header + data), byteorder='big') == 0):
            log.info(f"Reply packet [{len(header + data)}]: {bytewise(header + data)}")
            if (self.in_waiting != 0):
                log.warning(f"Unread data ({self.in_waiting} bytes) is left in a serial datastream")
                self.reset_input_buffer()
                log.info(f"Serial input buffer flushed")
            return data[:-2] if (not zerobyte) else data[:-3]  # 2 is packet RFC, 1 is zero padding byte
        else:
            raise SerialCommunicationError(f"Bad packet checksum (expected '{bytewise(rfc1071(data[:-2]))}', "
                                           f"got '{bytewise(data[-2:])}'). Packet discarded",
                                           dataname="Packet", data=header + data)

    @classmethod
    def __parseHeader(cls, header):
        assert (len(header) == cls.HEADER_LEN)
        assert (header[0] == cls.STARTBYTE)

        # unpack header (fixed structure - 6 bytes)
        fields = struct.unpack('< B B H H', header)
        if (fields[1] != cls.MASTER_ADDRESS):
            raise DeviceError(f"Wrong master address (expected '{cls.MASTER_ADDRESS}', got '{fields[1]}')")
        datalen = (fields[2] & 0x0FFF) * 2  # extract size in bytes, not 16-bit words
        zerobyte = (fields[2] & 1 << 15) >> 15  # extract EVEN flag (b15 in LSB / b7 in MSB)
        return datalen, zerobyte

    def sendPacket(self, msg):
        """ Wrap msg and send packet over serial port """

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
        log.info(f"Packet [{len(packetToSend)}]: {bytewise(packetToSend)}")
        return bytesSentCount
