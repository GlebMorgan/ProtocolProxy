import logging
import struct
import time
from typing import NamedTuple

import utils
from bits import bitsarray, flags
from colored_logger import ColorHandler
from utils import bytewise

from protocol import Protocol, Par
from serial_transceiver import SerialError

log = utils.getLogger(__name__)


class SONY(Protocol):
    DEVICE_ADDRESS = 12
    PARITY = 'N'
    BAUDRATE = 921600

    flagAliases = {
        'en': 'POWER',
        'r': 'RESET',
        'vin': 'VIDEO_IN_EN',
        'vout': 'VIDEO_OUT_EN',
    }

    def __init__(self, devCom, appCom):
        super().__init__()

        self.POWER = Par(bool)
        self.RESET = Par(bool)
        self.VIDEO_IN_EN = Par(bool)
        self.VIDEO_OUT_EN = Par(bool)

        self.CNT_IN = 0
        self.CNT_OUT = 0

        for par in self.params.values():
            par.attach(self.sendNoDataPacket)

        self.devCom = devCom
        self.appCom = appCom

    def wrap(self, msg: bytes):
        with self.lock:
            return struct.pack('< B B',
                               bitsarray(self.POWER, self.RESET, self.VIDEO_IN_EN, self.VIDEO_OUT_EN),
                               self.CNT_IN % 0x100,
                               ) + msg

    def unwrap(self, packet):
        end = packet.find(b'\xFF') + 1
        POWER_STATE, RESET_STATE, VIDEO_IN_STATE, VIDEO_OUT_STATE = flags(packet[0], 4)
        self.params['POWER'].ack(POWER_STATE)
        self.params['RESET'].ack(RESET_STATE)
        self.params['VIDEO_IN_EN'].ack(VIDEO_IN_STATE)
        self.params['VIDEO_OUT_EN'].ack(VIDEO_OUT_STATE)
        self.CNT_OUT = packet[1]
        return packet[2:end]

    def readNative(self, com) -> bytes:
        inputBuffer = []
        for i in range(16):
            byte = com.read()
            inputBuffer.append(byte)
            if (byte == b'\xFF'): break
        if (com.in_waiting != 0):
            log.warning(f"Unread data ({com.in_waiting} bytes) is left in a serial datastream")
            # com.reset_input_buffer()
            # log.info(f"Serial input buffer flushed")
        return b''.join(inputBuffer)

    def sendNoDataPacket(self, event, name, value):
        if (event == 'altered'): log.info(f"Altered: {self.__class__.__name__}.{name} to {value}")
        elif (event == 'check'): log.info(f"Checking {self.__class__.__name__} status")
        else: return

        with self.lock:

            data = b'\xFF' * 16

            self.devCom.sendPacket(self.wrap(data))
            reply = self.devCom.receivePacket()

            data = self.unwrap(reply)
            log.debug(f"Reply from MPOS: {bytewise(data)}")

    def communicate(self, stopEvent):
        print("Start communication")
        with self.devCom, self.appCom:
            while 1:
                try:
                    if (stopEvent.isSet()):
                        print("Stop communication")
                        return

                    if (self.appCom.in_waiting >= 3):
                        with self.lock:
                            log.info(f"Found incoming request from {self.__class__.__name__} control soft, "
                                     f"{self.appCom.in_waiting} bytes")
                            packet = self.readNative(self.appCom)

                            self.CNT_IN += 1
                            log.debug(f"Sony packet #{self.CNT_IN}: {bytewise(packet)}")

                            data = packet + b'\xFF' * (16 - len(packet))
                            log.debug(f"Data to MPOS: {bytewise(data)}")

                            for n in range(0x100):
                                log.debug(f"Attempt #{n}")

                                log.debug(f"Packet to MPOS: {bytewise(self.wrap(data))}")
                                self.devCom.sendPacket(self.wrap(data))

                                reply = self.devCom.receivePacket()
                                log.debug(f"Reply from MPOS: {bytewise(reply)}")

                                self.appCom.write(self.unwrap(reply))
                                log.debug(f"Data to control soft: {bytewise(self.unwrap(reply))}")

                                self.CNT_OUT = reply[1]
                                if (self.CNT_IN % 0x100 == self.CNT_OUT): break

                            else: log.error(f"Device is not responding on message #{self.CNT_IN}")

                    else:
                        time.sleep(0.1)
                        continue

                except SerialError as e: log.error(e)
