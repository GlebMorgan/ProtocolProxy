import sys
from os.path import abspath, dirname
from os.path import join as joinpath, expandvars as envar

from PyQt5Utils import install_exhook
from Utils import ConfigLoader

from app import App, ProtocolLoader
from ui import UI

# TODO: packaging

__version__ = '2.0.dev1'


if __name__ == '__main__':

    install_exhook()

    print(f"Launched from: {abspath(__file__)}")
    print(f"Launched with args: [{', '.join(sys.argv)}]")

    ConfigLoader.path = joinpath(envar('%APPDATA%'), '.PelengTools\\Tests\\ProtocolProxy')
    ProtocolLoader.path = joinpath(envar('%APPDATA%'), '.PelengTools\\Tests\\ProtocolProxy', 'devices')

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