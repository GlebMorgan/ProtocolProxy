import struct

from Utils import bitsarray, flags, flag, Logger

from device import Device, Par, Prop, DataInvalidError


log = Logger("SONY")
log.setLevel('DEBUG')


class SONY(Device):
    # Device config
    COMMUNICATION_INTERFACE: str = 'serial'
    DEV_ADDRESS: int = 12
    APP_TIMEOUT: float = 0.2
    APP_PARITY: str = 'N'
    APP_BAUDRATE: int = 9600
    DEFAULT_PAYLOAD: bytes = b'\xFF' * 16
    IDLE_PAYLOAD: bytes = DEFAULT_PAYLOAD

    # Internal service attrs
    APP_PACKET_MAX_SIZE: int = 18
    APP_TERMINATOR: bytes = b'\xFF'

    # Master-driven parameters
    POWER = Par('Power', 'p', bool)
    RESET = Par('Reset', 'r', bool)
    VIDEO_IN_EN = Par('Sony video receiver', 'vin', bool)
    VIDEO_OUT_EN = Par('Output video transmitter', 'vout', bool)

    # Device-driven properties
    CNT_IN = Prop('Incoming msgs counter', 'in', int)
    CNT_OUT = Prop('Outgoing msgs counter', 'out', int)

    def wrap(self, data: bytes) -> bytes:
        with self.lock:
            if data != self.IDLE_PAYLOAD: self.CNT_IN += 1
            header = bitsarray(self.POWER, self.RESET, self.VIDEO_IN_EN, self.VIDEO_OUT_EN), self.CNT_IN % 0x100
            return struct.pack('< B B', *header) + data

    def unwrap(self, packet: bytes) -> bytes:
        self.validateReply(packet)
        cls = self.__class__
        POWER_STATE, RESET_STATE, VIDEO_IN_STATE, VIDEO_OUT_STATE = flags(packet[0], 4)
        with self.lock:
            # ▼ Access parameters via class to get a descriptor, not parameter value
            cls.POWER.ack(POWER_STATE)
            cls.RESET.ack(RESET_STATE)
            cls.VIDEO_IN_EN.ack(VIDEO_IN_STATE)
            cls.VIDEO_OUT_EN.ack(VIDEO_OUT_STATE)
            self.CNT_OUT = packet[1]
        return packet[2:]

    def sendNative(self, com, data: bytes) -> int:
        # ▼ SONY native control software does not accept '00's
        if data == b'\x00' * 16: data = self.APP_TERMINATOR
        endIndex = data.find(self.APP_TERMINATOR)
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
            byte = com.read()  # skip all leading 'FF's
        yield byte
        for _ in range(15):  # first byte has been already read a line above
            byte = com.read()
            yield byte
            if byte == b'\xFF': return
        raise DataInvalidError(f"Bad data from SONY control software — message size is > 16 bytes")

    def validateCommandNative(self, packet: bytes):
        assert(packet[-1] == self.APP_TERMINATOR[0])
        if flag(packet[0], 7) is not True:
            log.error("First byte is invalid SONY message header (wrong data source is on the line?)")
        if packet[1] not in (0x1, 0x9, 0x21, 0x22, 0x30, 0x38):
            log.warning(f"Unknown command type: {packet[1]}")

    def validateReply(self, reply: bytes):
        if len(reply) > self.APP_PACKET_MAX_SIZE:
            raise DataInvalidError(f"Invalid reply packet size (expected at most {self.APP_PACKET_MAX_SIZE}, "
                                   f"got {len(reply)})")
        if (len(reply) < 3): raise DataInvalidError("Invalid reply packet size (expected at least 3, "
                                                    f"got {len(reply)}")
