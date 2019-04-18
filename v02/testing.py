import threading
import time
import unittest
from logger import Logger

from utils import auto_repr, bytewise

import serial_transceiver
from device import DeviceError
from devices.sony import DataInvalidError
from serial_transceiver import SerialError, PelengTransceiver, SerialTransceiver

log = Logger("Tests")


def testRaiseRuntimeError():
    raise RuntimeError("Test")


class DeviceMock:
    def __init__(self, adr, commandsAndReplies, stopEvent):
        try: self.tr = SerialTransceiver(port='COM11')
        except SerialError as e: print("WARNING!" + e.args[0])
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
                    command = self.tr.read(1)
                    print(f"Command received: {bytewise(command)}")
                    try: reply = next(msgs)[1]
                    except StopIteration: return
                    self.tr.write(reply)

                elif self.stopEvent.wait(0.1):
                    return
            else: print("ERROR!: DeviceMock transceiver communication loop - too many iterations")
        self.stopEvent.clear()

    def __repr__(self):
        return auto_repr(self, f"{{port={self.tr.port}({'open' if self.tr.is_open else 'closed'}), "
                               f"running={self.thread.is_alive()}}}")


class Test(unittest.TestCase):

    # FIXME: terrible test design - refactor everything :(

    def test_receivePacket(self):
        tr = PelengTransceiver(device=12, port='COM10', timeout=0.2)
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
            ('bad_adr', '5A 0C 06 80 9F 73 01 01 A8 AB AF AA AC AB A3 AA 08 00 4E 52' +
                        '5A 00 06 80 9F 7F 01 01 A8 AB AF AA AC AB A3 AA 08 00 4E 52'),
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
            # ('no_data_no_zerobyte', '5A 00 01 80 A4 7F FF 00 FF'),
            ('completely_bad_data', '5A '*25 + '5A 00 06 80 9F 7F 01 01 A8 AB AF AA AC AB A3 AA 08 00 4E 52'),
            ('one_byte_valid_data', '5A 00 01 80 A4 7F FF 00 00 FF'),
            ('chch', '5A 00 06 80 9F 7F 01 01 A8 AB AF AA AC AB A3 AA 08 00 4E 52'),
        ]
        for i, (command, expReply) in enumerate(msgs):
            msgs[i] = command, bytes.fromhex(expReply)

        dev = DeviceMock(12, msgs, stopEvent)

        def sendCommand():
            tr.write(b'!')
            print('sendCommand')
            res = tr.receivePacket()
            return res

        try:

            dev.start()
            time.sleep(0.2)
            Logger.LOGGERS['Serial'].setLevel('DEBUG')

            print(Logger.LOGGERS['Serial'].levelName)

            # input('Press smth to start! >>>')

            self.assertEqual(bytes.fromhex('01 01 A8 AB AF AA AC AB A3 AA 08'), sendCommand())  # 'chch'
            self.assertRaises(serial_transceiver.BadRfcError, sendCommand)  # 'bad_rfc'
            self.assertRaises(serial_transceiver.BadRfcError, sendCommand)  # 'rev_rfc'
            self.assertRaises(serial_transceiver.BadDataError, sendCommand)  # 'no_zerobyte'
            self.assertRaises(serial_transceiver.BadDataError, sendCommand)  # 'bad_startbyte'
            self.assertEqual(bytes.fromhex('01 01 A8 AB AF AA AC AB A3 AA 08'), sendCommand())  # 'chch'
            self.assertRaises(serial_transceiver.BadDataError, sendCommand)  # 'bad_header_and_rfc'
            self.assertEqual(bytes.fromhex('01 01 A8 AB AF AA AC AB A3 AA 08'), sendCommand())  # 'bad_adr'
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
            # self.assertRaises(serial_transceiver.BadDataError, sendCommand)  # 'no_data_no_zerobyte'
            self.assertEqual(bytes.fromhex('01 01 A8 AB AF AA AC AB A3 AA 08'), sendCommand())  # completely_bad_data
            self.assertEqual(b'\xFF', sendCommand())  # 'no_data'
            self.assertEqual(bytes.fromhex('01 01 A8 AB AF AA AC AB A3 AA 08'), sendCommand())  # 'chch'

        except Exception as e:
            log.showStackTrace(e)
            raise
        finally:
            stopEvent.set()
            dev.thread.join()
            time.sleep(0.01)


    def test_SONY_tx_rx(self):
        print("\nTest_receiveNative")

        class MockSerialResource():
            def __init__(self, data:bytes):
                self.data = data
                self.received = None

            @property
            def in_waiting(self):
                return len(self.data)

            def read(self, size=1):
                if size > 0 and self.data:
                    result = self.data[:size]
                    self.data = self.data[size:]
                    # if size == 1: result = result.to_bytes(1, 'big')
                    return result
                return b''

            def write(self, data):
                print(f"Written {len(data)} bytes: {bytewise(data)} to MockSerialResource")
                self.received = data
                return len(data)

        from devices.sony import SONY
        d = SONY()

        packets = (
            '88 30 01 FF',
            '80 38 FF',
            'FF FF 81 01 00 01 FF',
            '88 01 00 01 FF 32',
            '81 09 00 02 FF',
            '81 22 FF',
            '81 01 04 47 01 02 03 04 01 02 03 04 FF',
            'FF FF FF FF FF FF FF FF FF FF FF FF FF FF FF 81 81 81 81 FF 56',
        )

        answers = (
            '88 30 01 FF',
            '80 38 FF',
            '81 01 00 01 FF',
            '88 01 00 01 FF',
            '81 09 00 02 FF',
            '81 22 FF',
            '81 01 04 47 01 02 03 04 01 02 03 04 FF',
            '81 81 81 81 FF',
        )

        badPackets = (
            '78 30 01 FF',
            '00 FF',
            '81 00 00 00'
        )

        packets = tuple(bytes.fromhex(msg) for msg in packets)
        answers = tuple(bytes.fromhex(msg) for msg in answers)
        badPackets = tuple(bytes.fromhex(msg) for msg in badPackets)

        for packet, answer in zip(packets, answers):
            print(f"Packet: {bytewise(packet)}")
            self.assertEqual(d.receiveNative(MockSerialResource(packet)), answer)

        with self.assertRaises(DataInvalidError):
            d.receiveNative(MockSerialResource(badPackets[0]))
        with self.assertRaises(DataInvalidError):
            d.receiveNative(MockSerialResource(badPackets[1]))
        with self.assertRaises(DataInvalidError):
            d.receiveNative(MockSerialResource(badPackets[2]))

        print()
        print("End testing SONY RX")
        print('—'*80)

        # —————————————————————————————————————————————————————————————————————————————————— #

        print("\nTest_sendNative")

        packets = (
            '00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00',  # 0
            '01 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00',  # 1
            '00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00',  # 2
            '00 01 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00',  # 3
            '01 02 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00',  # 4
            '01 03 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00',  # 5
            '',  # 6
            'FF '*40,  # 7
            '01 00 80 99 DD AA BB EE CC 33 11 22 88 44 66 11 55 FF',  # 8
            '01 00 80 FF DD 00 00 00 00 00 00 00 00 00 00 00 00 00',  # 9
            '01 00 FF FF FF FF FF FF FF FF FF FF FF FF FF FF FF FF',  # 10
        )

        def tx(i):
            p = packets[i]
            print(f'Packet #{i}: {p}')
            r = MockSerialResource(bytes.fromhex(p))
            toSend = d.unwrap(r.data)
            d.sendNative(r, toSend)
            print()
            return r.received

        self.assertEqual(d.__class__.POWER.inSync, False)
        self.assertEqual(b'\xFF', tx(0))
        self.assertEqual(d.__class__.POWER.inSync, True)
        with self.assertRaises(DeviceError): tx(1)
        self.assertEqual(b'\xFF', tx(2))
        self.assertEqual(b'\xFF', tx(3))
        self.assertEqual(d.CNT_OUT, 1)
        d.POWER = True
        self.assertEqual(d.__class__.POWER.inSync, False)
        tx(4)
        self.assertEqual(d.POWER, True)
        self.assertEqual(d.__class__.POWER.inSync, True)
        with self.assertRaises(DataInvalidError): tx(5)
        with self.assertRaises(DataInvalidError): tx(6)
        with self.assertRaises(DataInvalidError): tx(7)
        self.assertEqual(bytes.fromhex('80 99 DD AA BB EE CC 33 11 22 88 44 66 11 55 FF'), tx(8))
        self.assertEqual(bytes.fromhex('80 FF'), tx(9))
        self.assertEqual(bytes.fromhex('FF'), tx(10))

        print()
        print("End testing SONY TX")
        print('—'*80)
        del SONY


    def test_SONY_wrap(self):
        print("\nTest_wrap")

        from devices.sony import SONY
        d = SONY()
        d.POWER = False  # SONY parameters are class attrs :/

        self.assertEqual(d.CNT_IN, 0)
        self.assertEqual(bytes.fromhex('00 00')+d.IDLE_PAYLOAD, d.wrap(d.IDLE_PAYLOAD))
        self.assertEqual(d.CNT_IN, 0)
        self.assertEqual(bytes.fromhex('00 01 88 30 01 FF'), d.wrap(bytes.fromhex('88 30 01 FF')))
        self.assertEqual(d.CNT_IN, 1)
        self.assertEqual(bytes.fromhex('00 01')+d.IDLE_PAYLOAD, d.wrap(d.IDLE_PAYLOAD))
        self.assertEqual(d.CNT_IN, 1)

        print()
        print("End testing SONY wrap")
        print('—'*80)

        del SONY


if __name__ == '__main__':
    unittest.main()
    exit()
