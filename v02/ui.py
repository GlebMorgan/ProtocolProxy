# CONSIDER: ui.py is launched - do not initialize protocol ui panel until user sets protocol explicitly
#           some_protocol.ui is launched - pull up main ui and init with executed protocol ui
from os import linesep
from sys import exit, argv, stdin

from PyQt5.QtWidgets import QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QDesktopWidget, QPushButton
from PyQt5Utils import ActionButton

from app import App


class UI(QApplication):

    def __init__(self, app, argv, *args):
        super().__init__(argv)
        self.app = app

        self.window = self.setUiWindow()
        self.testButton1 = ActionButton("ActionButtonTest", self.window)
        self.testButton2 = ActionButton("&Test2", self.window)
        # self.settingsPane = self.setSettingsPane()

        self.parseArgv(argv)
        self.app.addHandler('quit', self.quit)
        self.app.init()

    def parseArgv(self, argv):
        if 'cmd' in argv: self.app.startCmdThread()

    def setUiWindow(self):
        this = QMainWindow()
        this.resize(800, 600)
        self.centerWindowOnScreen(this)
        this.setWindowTitle(f"ProtocolProxy - v{self.app.VERSION} © GlebMorgan")
        # this.setWindowIcon(QIcon("sampleIcon.jpg"))
        this.show()
        return this

    def setSettingsPane(self):
        this = QWidget(self.window)
        toolpaneLayout = QHBoxLayout()

        toolpaneLayout.addWidget(self.testButton1)
        toolpaneLayout.addWidget(self.testButton1)
        toolpaneLayout.addStretch(1)

        this.setLayout(toolpaneLayout)
        return this

    @staticmethod
    def centerWindowOnScreen(window):
        #                   ▼ ————— that is whole screen ————— ▼
        screenCenterPoint = QDesktopWidget().availableGeometry().center()
        windowFrame = window.frameGeometry()
        windowFrame.moveCenter(screenCenterPoint)
        window.move(windowFrame.topLeft())


if __name__ == '__main__':
    print(f"Launched with args: [{', '.join(argv)}]")
    if 'cmd' not in argv: argv.append('cmd')

    with App() as core:
        ui = UI(core, argv)
        exit(ui.exec_())
