import logging
import struct
import time
from typing import NamedTuple

import bits
from colored_logger import ColorHandler
from utils import bytewise

from proxy_protocol_tools import ProxyProtocolMetaclass, PAR
from serial_transceiver import SerialError


log = logging.getLogger(__name__ + ":main")
log.setLevel(logging.DEBUG)
log.addHandler(ColorHandler())
log.disabled = False


class SONY(metaclass=ProxyProtocolMetaclass):

    POWER:PAR = False
    RESET:PAR = False
    VIDEO_IN_EN:PAR = False
    VIDEO_OUT_EN:PAR = False
    CNT_IN = 0


    class PARAMS(NamedTuple):
        DEVICE_ADDRESS = 12
        PARITY = 'N'
        BAUDRATE = 921600

        flagAliases = {
            'en': 'POWER',
            'r': 'RESET',
            'vin': 'VIDEO_IN_EN',
            'vout': 'VIDEO_OUT_EN',
        }


    @classmethod
    def wrap(cls, msg:bytes):
        with cls.lock:
            return struct.pack('< B B',
                               bits.bitsarray(cls.POWER, cls.RESET, cls.VIDEO_IN_EN, cls.VIDEO_OUT_EN),
                               cls.CNT_IN % 0x100,
                               ) + msg


    @staticmethod
    def unwrap(packet):
        end = packet.find(b'\xFF') + 1
        return packet[2:end]


    @staticmethod
    def readNative(com)->bytes:
        inputBuffer = []
        for i in range(16):
            byte = com.read()
            inputBuffer.append(byte)
            if (byte == b'\xFF'): break
        return b''.join(inputBuffer)


    @classmethod
    def communicate(cls, devCom, appCom, stopEvent):
        with devCom, appCom:
            while 1:
                try:
                    if (stopEvent.isSet()):
                        print("Stop communication")
                        return

                    if (appCom.in_waiting >= 3):
                        with cls.lock:
                            log.info(f"Found incoming request from {cls.__name__} control soft, "
                                     f"{appCom.in_waiting} bytes")
                            packet = cls.readNative(appCom)

                            cls.CNT_IN += 1
                            log.debug(f"Sony packet #{cls.CNT_IN}: {bytewise(packet)}")

                            data = packet + b'\xFF' * (16 - len(packet))
                            log.debug(f"Data to MPOS: {bytewise(data)}")

                            for n in range(100):
                                log.debug(f"Attempt #{n}")

                                log.debug(f"Packet to MPOS: {bytewise(cls.wrap(data))}")
                                devCom.sendPacket(cls.wrap(data))

                                reply = devCom.receivePacket()
                                log.debug(f"Reply from MPOS: {bytewise(reply)}")

                                appCom.write(cls.unwrap(reply))
                                log.debug(f"Data to control soft: {bytewise(cls.unwrap(reply))}")

                                CNT_OUT = reply[1]
                                if (cls.CNT_IN % 0x100 != CNT_OUT): break

                            else: log.error(f"Device is not responding on message #{cls.CNT_IN}")

                    elif (cls.altered):
                        with cls.lock:
                            log.debug(f"{cls.__name__} internal attr was altered")
                            data = b'\xFF' * 16

                            devCom.sendPacket(cls.wrap(data))
                            reply = devCom.receivePacket()

                            data = cls.unwrap(reply)
                            log.debug(f"Reply from MPOS: {bytewise(data)}")

                    else:
                        time.sleep(0.1)
                        continue

                except SerialError as e: log.error(e)
