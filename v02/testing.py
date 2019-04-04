import threading
import time
import unittest

from utils import Logger, auto_repr

from serial_transceiver import SerialError, PelengTransceiver

log = Logger("Tests")


def testRaiseRuntimeError():
    raise RuntimeError("Test")


class DeviceMock:
    def __init__(self, adr, stopEvent):
        try: self.tr = PelengTransceiver(device=0, master=adr, port='COM11')
        except SerialError as e: log.warn(e.args[0])
        self.tr.close()
        self.stopEvent = stopEvent
        self.thread = threading.Thread(name="DeviceMockThread", target=self.commLoop)

        self.chchreply = bytes.fromhex('01 01 A8 AB AF AA AC AB A3 AA 08')

    def start(self):
        self.thread.start()

    def commLoop(self):
        with self.tr:
            print("open?")
            while not self.stopEvent.is_set():
                if (self.tr.in_waiting):
                    print(f"Detected packet, {self.tr.in_waiting} bytes")
                    command = self.tr.receivePacket()
                    reply = 'FF FF'
                    if command.startswith(bytes.fromhex('01 01')):
                        reply = self.chchreply
                    self.tr.sendPacket(reply)

                elif self.stopEvent.wait(0.1):
                    return

        self.stopEvent.clear()

    def __repr__(self):
        return auto_repr(self, f"(port={self.tr.port}{{{'open' if self.tr.is_open else 'closed'}), "
                               f"adr={self.tr.masterAddress}, running={self.thread.is_alive()}}}")


class Test_PelengTransceiver(unittest.TestCase):

    def test_test(self):
        tr = PelengTransceiver(device=12, port='COM10')
        stopEvent = threading.Event()
        dev = DeviceMock(12, stopEvent)

        commands = {
            'chch': '5A 0C 06 80 9F 73 01 01 A8 AB AF AA AC AB A3 AA 08 00 4E 52',
            'badrfc': '5A 0C 06 80 9F 73 01 01 A8 AB AF AA AC AB A3 AA 08 00 4E 51',
            'revrfc': '5A 0C 06 80 9F 73 01 01 A8 AB AF AA AC AB A3 AA 08 00 52 4E',
            'nozb': '5A 0C 06 80 9F 73 01 01 A8 AB AF AA AC AB A3 AA 08 4E 52',
        }

        for command, value in commands.items():
            commands[command] = bytes.fromhex(value)

        def sendCommand(name):
            tr.sendPacket(commands[name])
            return tr.receivePacket()
        try:
            dev.start()
            time.sleep(0.1)
            print(dev)

            self.assertEqual(sendCommand('chch'), bytes.fromhex('01 01 A8 AB AF AA AC AB A3 AA 08'))

        except Exception as e:
            log.showStackTrace(e)
        finally:
            stopEvent.set()
            dev.thread.join()
            time.sleep(0.01)




if __name__ == '__main__':
    unittest.main()
