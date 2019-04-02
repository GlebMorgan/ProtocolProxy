import logging
import struct
import time
from typing import NamedTuple

import bits
from checksums import rfc1071
from colored_logger import ColorHandler
from utils import bytewise

from proxy_protocol_tools import ProxyProtocolMetaclass, PAR
from serial_transceiver import SerialError, SerialCommunicationError, SerialReadTimeoutError


log = logging.getLogger(__name__ + ":main")
log.setLevel(logging.DEBUG)
log.addHandler(ColorHandler())
log.disabled = False


class MWXC(metaclass=ProxyProtocolMetaclass):

    POWER:PAR = False
    VIDEO_OUT_EN:PAR = False

    POWER_STATE = None
    VIDEO_IN_STATE = None
    VIDEO_OUT_STATE = None
    CTRL_CHNL_STATE = None


    class PARAMS(NamedTuple):
        DEVICE_ADDRESS = 14
        PARITY = 'O'
        BAUDRATE = 115200
        NATIVE_COMMAND_STARTBYTE = b'\xA0'
        NATIVE_REPLY_STARTBYTE = b'\x50'
        NATIVE_PACKET_SIZE = 13

        bufferedPacket = bytes.fromhex('00 85 43 00 04 00 04 00 00 00 00')

        flagAliases = {
            'en': 'POWER',
            'vout': 'VIDEO_OUT_EN',
        }


    @classmethod
    def wrap(cls, msg:bytes):
        with cls.lock:
            return struct.pack('< B', bits.bitsarray(cls.POWER, cls.VIDEO_OUT_EN)) + msg


    @staticmethod
    def unwrap(packet):
        return packet[1:]


    @classmethod
    def wrapNative(cls, data:bytes) -> bytes:
        data = cls.PARAMS.NATIVE_REPLY_STARTBYTE + data
        return data + rfc1071(data)


    @classmethod
    def readNative(cls, com)->bytes:
        startByte = com.read(1)
        if (not startByte): raise SerialReadTimeoutError("No reply")
        if (startByte != cls.PARAMS.NATIVE_COMMAND_STARTBYTE):
            log.warning(f"Bad data in front of the stream: {startByte} Searching for valid startbyte...")
            for i in range(1, 1+cls.PARAMS.NATIVE_PACKET_SIZE*3):
                startByte = com.read(1)
                if (not startByte):
                    raise SerialCommunicationError("Bad startbyte")
                if (startByte == cls.PARAMS.NATIVE_COMMAND_STARTBYTE):
                    log.info(f"Found valid header at pos {i}")
                    break
            else: raise SerialCommunicationError("Cannot find header in datastream, too many attempts...")

        nativePacket = startByte + com.read(cls.PARAMS.NATIVE_PACKET_SIZE - 1)
        if (int.from_bytes(rfc1071(nativePacket), byteorder='big') != 0):
            if (len(nativePacket) == cls.PARAMS.NATIVE_PACKET_SIZE):
                raise SerialCommunicationError("Bad checksum, packet discarded")
            else:
                raise SerialCommunicationError("Bad data, packet is too short")

        return nativePacket[1:-2]


    @classmethod
    def communicate(cls, devCom, appCom, stopEvent):
        with devCom, appCom:
            while 1:
                try:
                    if (stopEvent.isSet()):
                        print("Stop communication")
                        return

                    elif (appCom.in_waiting > 0):
                        with cls.lock:
                            log.info(f"Found incoming request from {cls.__name__} control soft, "
                                     f"{appCom.in_waiting} bytes")

                            nativePacket = cls.readNative(appCom)
                            log.debug(f"Data from {cls.__name__} control soft: {bytewise(nativePacket)}")

                            log.debug(f"Packet to MPOS: {bytewise(cls.wrap(nativePacket))}")
                            devCom.sendPacket(cls.wrap(nativePacket))

                            reply = devCom.receivePacket()
                            log.debug(f"Reply from MPOS: {bytewise(reply)}")

                            appCom.write(cls.wrapNative(cls.unwrap(reply)))
                            log.debug(f"Data to control soft: {bytewise(cls.wrapNative(cls.unwrap(reply)))}")

                            cls.bufferedPacket = nativePacket

                    elif (cls.altered):
                        with cls.lock:
                            log.debug(f"{cls.__name__} internal attr was altered")

                            devCom.sendPacket(cls.wrap(cls.PARAMS.bufferedPacket))
                            reply = devCom.receivePacket()

                            data = cls.unwrap(reply)
                            log.debug(f"Reply from MPOS: {bytewise(data)}")

                    else:
                        time.sleep(0.1)
                        continue

                except SerialError as e: log.error(e)
