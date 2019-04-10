import serial
from utils import bytewise
from logger import Logger

from app import ProtocolLoader
from serial_transceiver import SerialTransceiver, PelengTransceiver, SerialReadTimeoutError

s = PelengTransceiver(device=12, port='COM10', baudrate=921600, parity='N', timeout=0.5, write_timeout=0.5)
r = SerialTransceiver(port='COM11', baudrate=921600, parity='N', timeout=0.5, write_timeout=0.5)

# ▼ logging levels aliases
lvl = {
    'C': 50,
    'F': 50,
    'E': 40,
    'W': 30,
    'I': 20,
    'D': 10,
    'N': 0,
}

log = Logger("Testing")


def SONY_receiveNative():
    import devices.sony
    print('—' * 20 + " NOT FINISHED " + '—' * 20)
    # return

    d = devices.sony.SONY()
    msgs = (
        '88 30 01 FF',
        '88 30 01 FF FF FF FF FF',
        '88 30 01 FF FF',
        '',
        '88 '*15+'FF',
        'FF FF 88 30 01 FF FF',
        '88 30 01 FF',
    )
    commands = tuple(map(bytes.fromhex, msgs))

    s.reset_input_buffer()
    s.reset_output_buffer()
    r.reset_input_buffer()
    r.reset_output_buffer()

    devices.sony.log.setLevel(lvl['D'])
    with s, r:
        for c in commands:
            try:
                s.write(c)
                reply = d.receiveNative(r)
                print(f"Command [{len(c)} bytes]: {bytewise(c)}, reply [{len(reply)} bytes]: {bytewise(reply)}")
                # assert reply == bytes.fromhex('88 30 01 FF')
            except SerialReadTimeoutError as e: log.showError(e)


def SONY_unwrap():
    import devices.sony
    d = devices.sony.SONY()

    msgs = (
        '0F 01 88 30 01 FF',
        '03 00 88 31 01 FF',
        '01 04 88 32 01 FF',
        '00 01 88 33 01 FF',
        'F0 06 88 34 01 FF',
    )
    commands = tuple(map(bytes.fromhex, msgs))

    with s, r:
        print(f"Init: device: {d}, CNT_OUT: {d.CNT_OUT}")
        for i, c in enumerate(commands):
            payload = d.unwrap(c)
            print(f"Command [{len(c)} bytes]: {bytewise(c)}, "
                  f"device: {d}, "
                  f"payload: {bytewise(payload)}, "
                  f"CNT_OUT: {d.CNT_OUT}"
                  )
            if (i == 1): d.VIDEO_OUT = not d.VIDEO_OUT


def SONY_wrap():
    import devices.sony
    d = devices.sony.SONY()

    actions = (
        ('', ''),
        ('FF', ''),
        ('', 'for par in d: par.value = True'),
        ('', 'd.CNT_IN = 9'),
    )

    print(f"Init: device: {d}, CNT_OUT: {d.CNT_OUT}")
    for payload, modificationCode in actions:
        exec(modificationCode)
        result = d.wrap(bytes.fromhex(payload))
        print(f"Data [{len(bytes.fromhex(payload))} bytes]: {payload}, "
              f"device: {d}, "
              f"CNT_OUT: {d.CNT_OUT}, "
              f"result: {bytewise(result, collapseAfter=32)}"
              )


def _testUtf8Char():
    # code = 0x2982
    # print(chr(code))
    for code in range(0x2980, 0x3000):
        print(chr(code))


def test_protocolLoader():
    import importlib
    import os
    Logger.LOGGERS['Device'].disabled = True
    FOLDER = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    path = "devices"
    p = ProtocolLoader(FOLDER, path)
    print(p)
    print(p['invalid_class_test'])


if __name__ == '__main__':
    functions = tuple(
            member for name, member in locals().items() if
            callable(member) and not member.__name__.startswith('_') and member.__module__ == '__main__'
    )
    print('Testing functions:')
    for f in functions: print(f"{' ' * 4}{f}")
    print()

    functions[-1]()
