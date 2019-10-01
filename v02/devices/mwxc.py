import struct

from Utils import bitsarray, flags, bytewise, Logger
from Transceiver import rfc1071, BadDataError, SerialCommunicationError, BadCrcError

from device import Device, Par, Prop, DataInvalidError


log = Logger("MWXC")


class MWXC(Device):
    # Device config
    COMMUNICATION_INTERFACE: str = 'serial'
    DEV_ADDRESS: int = 14
    APP_TIMEOUT: float = 0.2
    APP_PARITY: str = 'O'
    APP_BAUDRATE: int = 115200
    DEFAULT_PAYLOAD: bytes = bytes.fromhex('01 01 00 00 00 00 00 00 00 00 00')
    IDLE_PAYLOAD: bytes = DEFAULT_PAYLOAD

    # Internal service attrs
    APP_STARTBYTE_COMMAND: bytes = b'\xA0'
    APP_STARTBYTE_REPLY: bytes = b'\x50'
    APP_PACKET_SIZE: int = 13

    # Master-driven parameters
    POWER = Par('p', bool)  # ack by POWER_STATE device property
    VIDEO_OUT_EN = Par('vout', bool)  # ack by VIDEO_OUT_STATE device property

    # Device-driven properties
    VIDEO_IN_STATE = Prop('vin', bool)
    CTRL_CHNL_STATE = Prop('c', bool)

    def wrap(self, data: bytes) -> bytes:
        with self.lock:
            return struct.pack('< B', bitsarray(self.POWER, self.VIDEO_OUT_EN)) + data

    def unwrap(self, packet: bytes) -> bytes:
        self.validateReply(packet)
        cls = self.__class__
        POWER_STATE, VIDEO_IN_STATE, VIDEO_OUT_STATE, CTRL_CHNL_STATE = flags(packet[0], 4)
        # ▼ access parameters via class to get a descriptor, not parameter value
        cls.POWER.ack(POWER_STATE)
        cls.VIDEO_OUT_EN.ack(VIDEO_OUT_STATE)
        cls.VIDEO_IN = VIDEO_IN_STATE
        cls.CTRL = CTRL_CHNL_STATE
        return packet[1:]

    def sendNative(self, com, data: bytes) -> int:
        data = self.APP_STARTBYTE_REPLY + data
        return com.write(data + rfc1071(data))

    def receiveNative(self, com) -> bytes:
        startByte = com.read(1)
        if (startByte != self.APP_STARTBYTE_COMMAND):
            log.warning(f"Bad data in front of the stream: {bytewise(startByte)}. Searching for valid startbyte...")
            for i in range(1, self.APP_PACKET_SIZE):
                startByte = com.readSimple(1)
                if (not startByte):
                    raise BadDataError("No startbyte")
                if (startByte == self.APP_STARTBYTE_COMMAND):
                    log.info(f"Found valid header at pos {i}")
                    break
            else: raise SerialCommunicationError("Cannot find header in datastream, too many attempts...")

        nativePacket = startByte + com.readSimple(self.APP_PACKET_SIZE - 1)
        if len(nativePacket) != self.APP_PACKET_SIZE:
            raise BadDataError(f"Bad packet (data too small, [{len(nativePacket)}] out of [{self.APP_PACKET_SIZE}])",
                               dataname="Packet", data=nativePacket)
        if (int.from_bytes(rfc1071(nativePacket), byteorder='big') != 0):
            raise BadCrcError(f"Bad packet checksum (expected '{bytewise(rfc1071(nativePacket[:-2]))}', "
                              f"got '{bytewise(nativePacket[-2:])}'). Packet discarded",
                              dataname="Packet", data=nativePacket)
        self.IDLE_PAYLOAD = nativePacket[1:-2]
        return self.IDLE_PAYLOAD

    def validateReply(self, reply: bytes):
        if (len(reply) != 18): raise DataInvalidError(f"Invalid reply packet size (expected 18, "
                                                      f"got {len(reply)})")
