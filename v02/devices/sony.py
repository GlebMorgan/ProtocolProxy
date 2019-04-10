import struct

from bits import bitsarray, flags
from logger import Logger

from device import Device, Par, DataInvalidError

log = Logger("SONY")


class SONY(Device):
    COMMUNICATION_INTERFACE = 'serial'
    DEVICE_ADDRESS: int = 12
    NATIVE_PARITY: str = 'N'
    NATIVE_BAUDRATE: int = 9600
    DEFAULT_PAYLOAD: bytes = b'\xFF' * 16
    IDLE_PAYLOAD: bytes = DEFAULT_PAYLOAD

    POWER = Par('POWER', bool)
    RESET = Par('RESET', bool)
    VIDEO_IN = Par('VIDEO_IN_EN', bool)
    VIDEO_OUT = Par('VIDEO_OUT_EN', bool)
    CNT_IN = 0
    CNT_OUT = 0

    def wrap(self, data: bytes):  # tested
        with self.lock:
            header = bitsarray(self.POWER, self.RESET, self.VIDEO_IN, self.VIDEO_OUT), self.CNT_IN % 0x100
            return struct.pack('< B B', *header) + data

    def unwrap(self, packet):  # tested
        POWER_STATE, RESET_STATE, VIDEO_IN_STATE, VIDEO_OUT_STATE = flags(packet[0], 4)
        # ▼ access parameters via class to get a descriptor, not parameter value
        self.__class__.POWER.ack(POWER_STATE)
        self.__class__.RESET.ack(RESET_STATE)
        self.__class__.VIDEO_IN.ack(VIDEO_IN_STATE)
        self.__class__.VIDEO_OUT.ack(VIDEO_OUT_STATE)
        self.__class__.CNT_OUT = packet[1]
        return packet[2:]

    def sendNative(self, com, data):
        if data == b'\x00' * 16: data = self.IDLE_PAYLOAD
        com.write(data)

    # NOTE: 'com' lacks type annotation only because of requirement to create dependency just 4 that...
    # TODO: Create interface in this class for this purpose (ToGoogle: how to properly type-annotate interfaces)
    def receiveNative(self, com) -> bytes:
        inputBuffer = b''.join(self.readUpToFirstFF(com))
        if (com.in_waiting != 0):
            log.warning(f"Unread data ({com.in_waiting} bytes) is left in a serial datastream")
        return inputBuffer

    @staticmethod
    def readUpToFirstFF(com):  # tested
        byte = com.read()
        while byte == b'\xFF':
            byte = com.read()  # ◄ skip all leading 'FF's
        yield byte
        for _ in range(15):  # ◄ 1 byte has been already read a line above
            byte = com.read()
            yield byte
            if byte == b'\xFF': return
        # FIXME: intercept this error in receiveNative() and provide data that have been read + provide details
        raise DataInvalidError(f"DataInvalidError: bad data from SONY control software")
