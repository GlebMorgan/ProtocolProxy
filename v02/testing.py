import threading
import time
import unittest

from utils import Logger, auto_repr, bytewise

import serial_transceiver
from serial_transceiver import SerialError, PelengTransceiver, SerialTransceiver

log = Logger("Tests")


def testRaiseRuntimeError():
    raise RuntimeError("Test")


class DeviceMock:
    def __init__(self, adr, commandsAndReplies, stopEvent):
        try: self.tr = SerialTransceiver(port='COM11')
        except SerialError as e: log.warn(e.args[0])
        else: self.tr.close()

        self.commandsAndReplies = commandsAndReplies
        self.stopEvent = stopEvent
        self.thread = threading.Thread(name="DeviceMockThread", target=self.commLoop)

        self.chchreply = bytes.fromhex('01 01 A8 AB AF AA AC AB A3 AA 08')

    def start(self):
        self.thread.start()
        print("Starting Device Mock transceiver")

    def commLoop(self):
        with self.tr:
            msgs = iter(self.commandsAndReplies)
            for i in range(100_000):
                if self.stopEvent.is_set():
                    print("Stopping Device Mock transceiver")
                    return
                if (self.tr.in_waiting):
                    log.info(f"Detected packet, {self.tr.in_waiting} bytes")
                    command = self.tr.read(1)
                    log.info(f"Command received: {bytewise(command)}")
                    reply = next(msgs)[1]
                    self.tr.write(reply)

                elif self.stopEvent.wait(0.1):
                    return
            else: log.warning("DeviceMock transceiver communication loop - too many iterations")
        self.stopEvent.clear()

    def __repr__(self):
        return auto_repr(self, f"{{port={self.tr.port}({'open' if self.tr.is_open else 'closed'}), "
                               f"running={self.thread.is_alive()}}}")


class Test_PelengTransceiver(unittest.TestCase):

    # FIXME: terrible test design - refactor everything :(

    def test_receivePacket(self):
        tr = PelengTransceiver(device=12, port='COM10', timeout=0.5)
        stopEvent = threading.Event()

        chch_command = '5A 0C 06 80 9F 73 01 01 A8 AB AF AA AC AB A3 AA 08 00 4E 52'
        chch_reply = '5A 00 06 80 9F 7F 01 01 A8 AB AF AA AC AB A3 AA 08 00 4E 52'

        msgs = [
            ('chch', '5A 00 06 80 9F 7F 01 01 A8 AB AF AA AC AB A3 AA 08 00 4E 52'),
            ('bad_rfc', '5A 00 06 80 9F 7F 01 01 A8 AB AF AA AC AB A3 AA 08 00 4E 51'),
            ('rev_rfc', '5A 00 06 80 9F 7F 01 01 A8 AB AF AA AC AB A3 AA 08 00 52 4E'),
            ('no_zerobyte', '5A 00 06 80 9F 7F 01 01 A8 AB AF AA AC AB A3 AA 08 4E 52'),
            ('bad_startbyte', 'A5 00 06 80 54 7F 01 01 A8 AB AF AA AC AB A3 AA 08 00 4E 52'),
            ('chch', '5A 00 06 80 9F 7F 01 01 A8 AB AF AA AC AB A3 AA 08 00 4E 52'),
            ('bad_header_and_rfc', 'A5 00 06 80 9F 7F 01 01 A8 AB AF AA AC AB A3 AA 08 00 4E 52'),
            ('bad_adr', '5A 0C 06 80 9F 73 01 01 A8 AB AF AA AC AB A3 AA 08 00 4E 52'),
            ('bad_adr_and_rfc', '5A 0C 06 80 9F 7F 01 01 A8 AB AF AA AC AB A3 AA 08 00 4E 52'),
            ('bad_len', '5A 00 09 00 9C FF 01 01 A8 AB AF AA AC AB A3 AA 08 00 4E 52'),
            ('bad_len_and_rfc', '5A 00 09 00 9F 7F 01 01 A8 AB AF AA AC AB A3 AA 08 00 4E 52'),
            ('bad_header_rfc', '5A 00 06 80 9F 80 01 01 A8 AB AF AA AC AB A3 AA 08 00 4E 52'),
            # ('bad_header_rfc_clean', '5A 00 06 80 9F 80 01 01 A8 AB AF AA AC AB A3 AA 08 00 4E 52'),
            ('rev_header_rfc', '5A 00 06 80 7F 9F 01 01 A8 AB AF AA AC AB A3 AA 08 00 4E 52'),
            ('double_chch', '5A 00 06 80 9F 7F 01 01 A8 AB AF AA AC AB A3 AA 08 00 4E 52 '*2),
            ('chch', '5A 00 06 80 9F 7F 01 01 A8 AB AF AA AC AB A3 AA 08 00 4E 52'),
            ('chch_x10', '5A 00 06 80 9F 7F 01 01 A8 AB AF AA AC AB A3 AA 08 00 4E 52 '*10),
            ('no_data', '5A 00 00 00 A5 FF 00 00'),
            ('no_data_no_zerobyte', '5A 00 01 80 A4 7F FF 00 FF'),
            ('one_byte_valid_data', '5A 00 01 80 A4 7F FF 00 00 FF'),
            ('chch', '5A 00 06 80 9F 7F 01 01 A8 AB AF AA AC AB A3 AA 08 00 4E 52'),
        ]
        for i, (command, expReply) in enumerate(msgs):
            msgs[i] = command, bytes.fromhex(expReply)

        dev = DeviceMock(12, msgs, stopEvent)

        def sendCommand():
            tr.write(b'!')
            print()
            return tr.receivePacket()

        try:

            dev.start()
            time.sleep(0.5)
            print(dev)

            input('Press smth to start! >>>')

            self.assertEqual(bytes.fromhex('01 01 A8 AB AF AA AC AB A3 AA 08'), sendCommand())  # 'chch'
            self.assertRaises(serial_transceiver.BadRfcError, sendCommand)  # 'bad_rfc'
            self.assertRaises(serial_transceiver.BadRfcError, sendCommand)  # 'rev_rfc'
            self.assertRaises(serial_transceiver.BadDataError, sendCommand)  # 'no_zerobyte'
            self.assertRaises(serial_transceiver.BadDataError, sendCommand)  # 'bad_startbyte'
            self.assertEqual(bytes.fromhex('01 01 A8 AB AF AA AC AB A3 AA 08'), sendCommand())  # 'chch'
            self.assertRaises(serial_transceiver.BadDataError, sendCommand)  # 'bad_header_and_rfc'
            self.assertRaises(ValueError, sendCommand)  # 'bad_adr'
            self.assertRaises(serial_transceiver.BadDataError, sendCommand)  # 'bad_adr_and_rfc'
            self.assertRaises(serial_transceiver.BadDataError, sendCommand)  # 'bad_len'
            self.assertRaises(serial_transceiver.BadDataError, sendCommand)  # 'bad_len_and_rfc'
            self.assertRaises(serial_transceiver.BadDataError, sendCommand)  # 'bad_header_rfc'
            # dev.tr.reset_input_buffer()
            # self.assertRaises(serial_transceiver.BadDataError, sendCommand)  # 'bad_header_rfc_clean'
            self.assertRaises(serial_transceiver.BadDataError, sendCommand)  # 'rev_header_rfc'
            self.assertEqual(bytes.fromhex('01 01 A8 AB AF AA AC AB A3 AA 08'), sendCommand())  # ▼ 'double_chch'
            self.assertEqual(bytes.fromhex('01 01 A8 AB AF AA AC AB A3 AA 08'), sendCommand())
            self.assertEqual(bytes.fromhex('01 01 A8 AB AF AA AC AB A3 AA 08'), sendCommand())  # 'chch'
            for i in range(10):
                print(f' i={i}')
                self.assertEqual(bytes.fromhex('01 01 A8 AB AF AA AC AB A3 AA 08'), sendCommand())  # 'chch_x10'
            self.assertEqual(b'', sendCommand())  # 'no_data'
            self.assertRaises(serial_transceiver.BadDataError, sendCommand)  # 'no_data_no_zerobyte'
            self.assertEqual(b'\xFF', sendCommand())  # 'no_data'
            self.assertEqual(bytes.fromhex('01 01 A8 AB AF AA AC AB A3 AA 08'), sendCommand())  # 'chch'

        except serial_transceiver.BadDataError as e: log.showStackTrace(e)
        finally:
            stopEvent.set()
            dev.thread.join()
            time.sleep(0.01)


if __name__ == '__main__':
    unittest.main()
    exit()
