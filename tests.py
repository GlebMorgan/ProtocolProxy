import logging
import threading

import serial
from colored_logger import ColorHandler

from fcb_protocol import SONY
from mwxc_protocol import MWXC
from serial_transceiver import SerialTransceiver, SerialError, SerialCommunicationError, DeviceError

log = logging.getLogger(__name__ + ":main")
log.setLevel(logging.DEBUG)
log.addHandler(ColorHandler())
log.disabled = False


# This is what FCB Control software is sending as first packet to the device (network change command)
#  88 30 01 FF

#                SONY soft  <———>  COM10 ================== COM11  <———>   script  <———>  COM1 <———> MOXA

# [Native control software] <———> [COM_PROXY_IN]===[COM_PROXY_OUT] <———> [pyProxy] <———> [COM] <———> [DEVICE]


def main():
    COM = 'COM1'
    COM_PROXY_IN = 'COM10'
    COM_PROXY_OUT = 'COM11'

    def initCommunication(stopEvent):
        appCom = serial.Serial(port=COM_PROXY_OUT, timeout=0.5, write_timeout=0.5,
                               baudrate=protocol.PARAMS.BAUDRATE, parity=protocol.PARAMS.PARITY)

        devCom = SerialTransceiver(devAddr=protocol.PARAMS.DEVICE_ADDRESS, port=COM, parity=serial.PARITY_NONE)

        print("Start communication")
        protocol.communicate(devCom, appCom, stopEvent)

        # TODO: pull internal protocol parameters from reply message
        #       and assign (create prior to) them to corresponding protocol class object

    def initThread(stopEvent):
        commThread = threading.Thread(name="DeviceCommunicationLoop", target=initCommunication, args=(stopEvent,))
        commThread.start()
        return commThread

    protocols = {'sony': SONY, 'mwxc': MWXC}
    protocol = protocols['sony']

    stopEvent = threading.Event()
    commThread = initThread(stopEvent)

    for i in range(10_000):
        serial.time.sleep(0.1)
        try:
            userinput = input('--> ')
            if (userinput.strip() == ''): continue
            params = userinput.strip().split()
            command = params[0]

            with protocol.lock:
                if (command == 'e'):
                    stopEvent.set()
                    commThread.join()
                    print("Terminated :)")
                    break

                # TODO: consider protocol change (with communication loop restart)

                if (command == 'comin'):
                    COM_PROXY_IN = f'COM{params[1]}'

                if (command == 'comout'):
                    COM_PROXY_OUT = f'COM{params[1]}'

                if (command == 'com'):
                    COM = f'COM{params[1]}'

                if (command in protocols):
                    protocol = protocols[command]
                    stopEvent.set()
                    commThread.join()
                    stopEvent.clear()
                    commThread = initThread(stopEvent)

                if (command in protocol.PARAMS.flagAliases):
                    nicks = protocol.PARAMS.flagAliases
                    setattr(protocol, nicks[command], not getattr(protocol, nicks[command]))
                    print(f"{protocol.__name__} '{nicks[command]}' is "
                          f"{'on' if getattr(protocol, nicks[command]) else 'off'}")

                if (command == 'stat'):
                    protocol.sendNoDataPacket(protocol)
                    print(protocol)


        except SerialCommunicationError as e: print(e)
        except SerialError as e: print(e)
        except DeviceError as e: print(e)
        except NotImplementedError as e: print(e)


if (__name__ == '__main__'):
    main()
