import struct

from bits import bitsarray, flags
from checksums import rfc1071
from logger import Logger
from utils import bytewise
from device import Device, Par, Prop
from serial_transceiver import BadDataError, SerialCommunicationError, BadRfcError

log = Logger("MWXC")

# TODO: test all this class


class MWXC(Device):
    COMMUNICATION_INTERFACE: str = 'serial'
    DEVICE_ADDRESS: int = 14
    NATIVE_TIMEOUT: float = 0.2
    NATIVE_PARITY: str = 'O'
    NATIVE_BAUDRATE: int = 115200
    DEFAULT_PAYLOAD: bytes = bytes.fromhex('00 85 43 00 04 00 04 00 00 00 00')
    IDLE_PAYLOAD: bytes = DEFAULT_PAYLOAD  # TODO: IDLE_PAYLOAD not the same as DEFAULT_PAYLOAD

    # internal service attrs
    NATIVE_STARTBYTE_COMMAND: bytes = b'\xA0'
    NATIVE_STARTBYTE_REPLY: bytes = b'\x50'
    NATIVE_PACKET_SIZE: int = 13

    # master-driven parameters
    POWER = Par('POWER', 'p', bool)  # ack by POWER_STATE device property
    VIDEO_OUT = Par('VIDEO_OUT_EN', 'vout', bool)  # ack by VIDEO_OUT_STATE device property

    # device-driven properties
    VIDEO_IN = Prop('VIDEO_IN_STATE', 'vin', bool)
    CTRL = Prop('CTRL_CHNL_STATE', 'c', bool)

    def wrap(self, data: bytes) -> bytes:
        with self.lock:
            return struct.pack('< B', bitsarray(self.POWER, self.VIDEO_OUT)) + data

    def unwrap(self, packet: bytes) -> bytes:
        self.validateReply(packet)
        cls = self.__class__
        POWER_STATE, VIDEO_IN_STATE, VIDEO_OUT_STATE, CTRL_CHNL_STATE = flags(packet[0], 4)
        # ▼ access parameters via class to get a descriptor, not parameter value
        cls.POWER.ack(POWER_STATE)
        cls.VIDEO_OUT.ack(VIDEO_OUT_STATE)
        cls.VIDEO_IN = VIDEO_IN_STATE
        cls.CTRL = CTRL_CHNL_STATE
        return packet[1:]

    def sendNative(self, com, data: bytes) -> int:
        data = self.NATIVE_STARTBYTE_REPLY + data
        return com.write(data + rfc1071(data))

    def receiveNative(self, com) -> bytes:
        startByte = com.read(1)
        if (startByte != self.NATIVE_STARTBYTE_COMMAND):
            log.warning(f"Bad data in front of the stream: {startByte:02X}. Searching for valid startbyte...")
            for i in range(1, self.NATIVE_PACKET_SIZE):
                startByte = com.simpleRead(1)
                if (not startByte):
                    raise BadDataError("No startbyte")
                if (startByte == self.NATIVE_STARTBYTE_COMMAND):
                    log.info(f"Found valid header at pos {i}")
                    break
            else: raise SerialCommunicationError("Cannot find header in datastream, too many attempts...")

        nativePacket = startByte + com.simpleRead(self.NATIVE_PACKET_SIZE - 1)
        if len(nativePacket) != self.NATIVE_PACKET_SIZE:
            raise BadDataError(f"Bad packet (data too small, [{len(nativePacket)}] out of [{self.NATIVE_PACKET_SIZE}])",
                               dataname="Packet", data=nativePacket)
        if (int.from_bytes(rfc1071(nativePacket), byteorder='big') != 0):
                raise BadRfcError(f"Bad packet checksum (expected '{bytewise(rfc1071(nativePacket[:-2]))}', "
                                  f"got '{bytewise(nativePacket[-2:])}'). Packet discarded",
                                  dataname="Packet", data=nativePacket)

        self.validateCommandNative(nativePacket)
        return nativePacket[1:-2]

    def validateCommandNative(self, packet: bytes):
        return True

    def validateReply(self, reply: bytes):
        return True
