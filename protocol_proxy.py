import logging
import sys
import threading

import serial
import utils
from colored_logger import ColorHandler

from fcb_protocol import SONY
from fcb_ui import SonyUI
from mwxc_protocol import MWXC
from protocol import Protocol
from serial_transceiver import SerialTransceiver, SerialError, SerialCommunicationError, DeviceError
from ui import App

log = utils.getLogger(__name__)

# TODO: synchronize UI and device object automatically

# TODO: add IGNORE_RFC flag

# TODO: add functionality to ask user for a interruption if one-and-the-same error appears over&over successively

# NOTE: For SONY protocol, do not handle CNT_IN and CNT_OUT, just pass them to UI

# FIXME: Ask why CNY_IN == 0 is not accepted by SONY module of MPOS (not taking into consideration first packets)


class ProtocolProxy:
    class CONFIG:
        COM = 'COM1'
        COM_PROXY_IN = 'COM10'
        COM_PROXY_OUT = 'COM11'
        PROTOCOLS = {'sony': SONY, 'mwxc': MWXC}

    def __init__(self):
        self.protocol: Protocol = None
        self.appCom = serial.Serial(port=self.CONFIG.COM_PROXY_OUT, timeout=0.5, write_timeout=0.5)
        self.devCom = SerialTransceiver(port=self.CONFIG.COM, devAddr=...)

        # TODO: add crash protection: periodically quiery main thread and exit if no reply.
        #   For now, just let the cmd thread die when main thread is over

        self.swapProtocol(self.CONFIG.PROTOCOLS['sony'](self.devCom, self.appCom))

        self.stopEvent = threading.Event()
        self.nThreadsStarted = 0
        self.cmdThread = self.newCmdThread()
        self.commThread = self.newCommunicationThread()

        # TODO: add dynamic ui swaps
        # self.ui = App(SonyUI(self.protocol), sys.argv)

    def newCmdThread(self):
        thread = threading.Thread(
                name="CommandLineThread",
                target=self.cmdInterface,
        )
        thread.start()
        return thread

    def newCommunicationThread(self):
        while True:
            self.nThreadsStarted += 1
            thread = threading.Thread(
                    name=f"DeviceCommunicationLoop#{self.nThreadsStarted}",
                    target=self.protocol.communicate,
                    args=(self.stopEvent,)
            )
            thread.start()
            return thread

    def swapProtocol(self, newProtocol: Protocol):
        self.appCom.close()
        self.devCom.close()

        self.appCom.baudrate = newProtocol.BAUDRATE
        self.appCom.parity = newProtocol.PARITY
        self.devCom.deviceAddress = newProtocol.DEVICE_ADDRESS

        self.appCom.open()
        self.devCom.open()

        self.protocol = newProtocol
        log.debug(f"Current protocol: {self.protocol}")

    def cmdInterface(self):
        while True:
            serial.time.sleep(0.1)
            try:
                userinput = input('--> ')
                if (userinput.strip() == ''): continue
                params = userinput.strip().split()
                command = params[0]

                with self.protocol.lock:
                    if (command == 'e'):
                        self.stopEvent.set()
                        self.commThread.join()
                        print("Terminated :)")
                        break

                    # TODO: consider protocol change (with communication loop restart)

                    if (command == 'comin'):
                        self.CONFIG.COM_PROXY_IN = f'COM{params[1]}'

                    if (command == 'comout'):
                        self.CONFIG.COM_PROXY_OUT = f'COM{params[1]}'

                    if (command == 'com'):
                        self.CONFIG.COM = f'COM{params[1]}'

                    if (command in self.CONFIG.PROTOCOLS):
                        self.stopEvent.set()
                        self.commThread.join()
                        self.swapProtocol(self.CONFIG.PROTOCOLS[command](self.appCom, self.devCom, self.stopEvent))
                        self.stopEvent.clear()
                        self.commThread = self.newCommunicationThread()

                    if (command in self.protocol.flagAliases):
                        attr = self.protocol.flagAliases[command]
                        setattr(self.protocol, attr, not getattr(self.protocol, attr))
                        print(f"{self.protocol.__class__.__name__} '{attr}' is "
                              f"{'on' if getattr(self.protocol, attr) else 'off'}")
                        print("Why 'not None' evaluates to 'False' here???")
                    if (command == 'stat'):
                        print(self.protocol)


            except SerialCommunicationError as e: print(e)
            except SerialError as e: print(e)
            except DeviceError as e: print(e)
            except NotImplementedError as e: print(e)


if __name__ == '__main__':
    app = ProtocolProxy()
    # exitcode = app.ui.exec_()
    # sys.exit(exitcode)
