import sys

if sys.executable.endswith("pythonw.exe"):
    from os import devnull
    sys.stdout = sys.stderr = open(devnull, "w", encoding='utf-8')

from os.path import abspath, dirname
from os.path import join as joinpath, expandvars as envar

from PyQt5Utils import install_exhook
from Utils import ConfigLoader

from app import App
from ui import UI


__version__ = '2.1.0'


if __name__ == '__main__':

    install_exhook()

    print(f"Launched with args: [{', '.join(sys.argv)}]")

    ConfigLoader.path = joinpath(envar('%APPDATA%'), '.PelengTools\\ProtocolProxy')

    INFO = {
        'version': __version__,
        'projectname': 'ProtocolProxy',
        'projectdir': dirname(abspath(__file__).strip('.pyz')),
    }

    app = App(INFO)
    ui = UI(app, sys.argv)

    with app:
        exit_msg = ui.exec()
    sys.exit(exit_msg)