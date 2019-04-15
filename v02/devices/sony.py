import struct

from bits import bitsarray, flags, flag
from logger import Logger

from device import Device, Par, Prop, DataInvalidError

log = Logger("SONY")


class SONY(Device):
    COMMUNICATION_INTERFACE: str = 'serial'
    DEVICE_ADDRESS: int = 12
    NATIVE_TIMEOUT: float = 0.2
    NATIVE_PARITY: str = 'N'
    NATIVE_BAUDRATE: int = 9600
    DEFAULT_PAYLOAD: bytes = b'\xFF' * 16
    IDLE_PAYLOAD: bytes = DEFAULT_PAYLOAD

    # internal service attrs
    NATIVE_PACKET_MAX_SIZE: int = 18
    NATIVE_TERMINATOR: bytes = b'\xFF'

    # master-driven parameters
    POWER = Par('POWER', 'p', bool)
    RESET = Par('RESET', 'r', bool)
    VIDEO_IN = Par('VIDEO_IN_EN', 'vin', bool)
    VIDEO_OUT = Par('VIDEO_OUT_EN', 'vout', bool)

    # device-driven properties
    CNT_IN = Prop('CNT_IN', 'in', int)
    CNT_OUT = Prop('CNT_OUT', 'out', int)

    def wrap(self, data: bytes) -> bytes:
        if data != self.IDLE_PAYLOAD: self.CNT_IN += 1
        with self.lock:
            header = bitsarray(self.POWER, self.RESET, self.VIDEO_IN, self.VIDEO_OUT), self.CNT_IN % 0x100
            return struct.pack('< B B', *header) + data

    def unwrap(self, packet: bytes) -> bytes:
        self.validateReply(packet)
        cls = self.__class__
        POWER_STATE, RESET_STATE, VIDEO_IN_STATE, VIDEO_OUT_STATE = flags(packet[0], 4)
        # ▼ access parameters via class to get a descriptor, not parameter value
        cls.POWER.ack(POWER_STATE)
        cls.RESET.ack(RESET_STATE)
        cls.VIDEO_IN.ack(VIDEO_IN_STATE)
        cls.VIDEO_OUT.ack(VIDEO_OUT_STATE)
        cls.CNT_OUT = packet[1]
        return packet[2:]

    def sendNative(self, com, data: bytes) -> int:
        if data == b'\x00' * 16: data = self.NATIVE_TERMINATOR  # ◄ SONY native control software does not accept '00's
        endIndex = data.find(self.NATIVE_TERMINATOR)
        return com.write(data[:endIndex+1])

    def receiveNative(self, com) -> bytes:
        inputBuffer = b''.join(self.readUpToFirstFF(com))
        if (com.in_waiting != 0):
            log.warning(f"Unread data ({com.in_waiting} bytes) is left in a serial datastream")
        self.validateCommandNative(inputBuffer)
        return inputBuffer

    @staticmethod
    def readUpToFirstFF(com):
        byte = com.read()
        while byte == b'\xFF':
            byte = com.read()  # ◄ skip all leading 'FF's
        yield byte
        for _ in range(15):  # ◄ 1 byte has been already read a line above
            byte = com.read()
            yield byte
            if byte == b'\xFF': return
        raise DataInvalidError(f"Bad data from SONY control software — message size is > 16 bytes")

    def validateCommandNative(self, packet: bytes):
        assert(packet[-1] == self.NATIVE_TERMINATOR[0])
        if flag(packet[0], 7) is not True:
            raise DataInvalidError("First byte is invalid SONY message header (wrong data source is on the line?)")
        if packet[1] not in (0x1, 0x9, 0x21, 0x22, 0x30, 0x38):
            log.warning(f"Unknown command type: {packet[1]}")

    def validateReply(self, reply: bytes):
        if len(reply) > self.NATIVE_PACKET_MAX_SIZE:
            raise DataInvalidError(f"Invalid reply packet size (expected at most {self.NATIVE_PACKET_MAX_SIZE}, "
                                   f"got {len(reply)})", dataname='Packet', data=reply)
