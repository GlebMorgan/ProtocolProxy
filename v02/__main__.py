import ctypes
from os.path import abspath, dirname
from os.path import join as joinpath, expandvars as envar
from pathlib import Path
from sys import argv, exit as sys_exit, modules

from Utils import ConfigLoader

from app import App, ProtocolLoader
from ui import UI

__version__ = '2.0.dev1'


if __name__ == '__main__':

    print(f"Launched from: {abspath(__file__)}")
    print(f"Launched with args: [{', '.join(argv)}]")

    ConfigLoader.path = joinpath(envar('%APPDATA%'), '.PelengTools\\Tests\\ProtocolProxy')
    ProtocolLoader.path = joinpath(envar('%APPDATA%'), '.PelengTools\\Tests\\ProtocolProxy', 'devices')

    INFO = {
        'version': __version__,
        'projectname': 'ProtocolProxy',
        'projectdir': dirname(abspath(__file__).strip('.pyz')),
    }

    app = App(INFO)
    ui = UI(app, argv)

    with app:
        app.init()
        exit_msg = ui.exec()
        sys_exit(exit_msg)