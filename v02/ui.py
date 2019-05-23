# CONSIDER: ui.py is launched - do not initialize protocol ui panel until user sets protocol explicitly
#           some_protocol.ui is launched - pull up main ui and init with executed protocol ui

# TODO: help functionality: tooltips, dedicated button (QT 'whatsThis' built-in), etc.

from sys import argv, stdout, exit as sys_exit

from PyQt5.QtCore import QSize, QStringListModel, pyqtSignal
from PyQt5.QtGui import QValidator, QFontMetrics
from PyQt5.QtWidgets import QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QDesktopWidget, QPushButton, \
    QComboBox, QAction
from PyQt5Utils import ActionButton, ValidatingComboBox
from logger import Logger
from utils import memoLastPosArgs

from app import App


log = Logger("UI")


class UI(QApplication):

    def __init__(self, app, argv, *args):
        super().__init__(argv)
        self.app = app

        self.window = self.setUiWindow()
        self.test_addWidgets()

        self.settingsPane = self.setSettingsPane()

        self.parseArgv(argv)
        self.app.addHandler('quit', self.quit)
        self.app.init()

    def parseArgv(self, argv):
        if 'cmd' in argv: self.app.startCmdThread()

    def setUiWindow(self):
        this = QMainWindow()
        this.resize(800, 600)
        # self.centerWindowOnScreen(this)
        this.move(1050, 250)
        this.setWindowTitle(f"ProtocolProxy - v{self.app.VERSION} © GlebMorgan")
        # this.setWindowIcon(QIcon("sampleIcon.jpg"))
        this.show()
        return this

    def setSettingsPane(self):
        this = QWidget(self.window)
        toolpaneLayout = QHBoxLayout()

        toolpaneLayout.addStretch(1)

        this.setLayout(toolpaneLayout)
        this.resize(this.sizeHint())
        this.show()
        return this

    @staticmethod
    def centerWindowOnScreen(window):
        #                   ▼ ————— that is whole screen ————— ▼
        screenCenterPoint = QDesktopWidget().availableGeometry().center()
        windowFrame = window.frameGeometry()
        windowFrame.moveCenter(screenCenterPoint)
        window.move(windowFrame.topLeft())

# ———————————————————————————————————————————————————————————————————————————————————————————————————————————————————— #

    @staticmethod
    def test_newAction(name, slot, shortcut=None):
        this = QAction(name)  # parent=self.window?
        if shortcut: this.setShortcut(shortcut)
        this.triggered.connect(slot)
        log.debug(f"Action {name} created: {this}")
        return this

    def test_addWidgets(self):
        self.testButton1 = ActionButton("ActionButtonTest", self.window)
        self.testButton1.move(50, 0)
        self.testButton2 = ActionButton("&Test2", self.window)
        self.testButton2.move(200, 0)
        self.testCombobox = self.test_setTestCombobox()
        self.testCombobox.move(300, 0)
        self.testComPanel = self.setTestComPanel()
        self.testComPanel.move(500, 0)

        self.testButton2.clicked.connect(self.test)

    def setTestComPanel(self):
        from serial_transceiver import PelengTransceiver
        from test_com_panel import SerialCommPanel

        this = SerialCommPanel(self.window, devInt=PelengTransceiver())
        return this

    def test_setTestCombobox(self):
        this = ValidatingComboBox(self.window, action=self.test_newAction("TestComboBox", self.testComboboxActionTriggered))
        this.setValidator(Test_ProtocolValidator(this))
        this.addItems((pName.upper() for pName in self.app.protocols if len(pName) < 8))
        this.addItems(('TK-275', 'SMTH'))

        # CONSIDER: drop-down on hover
        return this

    def test_setComSettingsCombobox(self):
        return QWidget(self.window)

    def testComboboxActionTriggered(self):
        print(self.sender().data())

    def test(self):
        print(QValidator.Acceptable is 2, QValidator.Acceptable == 2)

    def test_ComboBox(self, par='none'):
        print(par)


class Test_ProtocolValidator(QValidator):

    validationStateChanged = pyqtSignal(QValidator.State)

    def __init__(self, target, *args):
        super().__init__(*args)
        self.target = target
        self.items = self.target.model().stringList
        self.state = None
        print(f"Protocols in ComboBox: {self.items()}")

    @memoLastPosArgs
    def validate(self, text, pos):  # FIXME: debug fully, fix error when 1st digit lost when replacing selected text
        text = text.upper()

        if text.strip() in self.items():
            newState = self.Acceptable
        elif any(protocolName.startswith(text.strip()) for protocolName in self.items()):
            newState = self.Intermediate
        else:
            newState = self.Invalid
            self.target.lineEdit().setText(text)
            self.target.lineEdit().setCursorPosition(pos)

        if self.state != newState:
            self.state = newState
            self.validationStateChanged.emit(newState)

        return self.state, text, pos



if __name__ == '__main__':
    print(f"Launched with args: [{', '.join(argv)}]")
    # if not stdout.isatty() and 'cmd' not in argv: argv.append('cmd')

    with App() as core:
        ui = UI(core, argv)
        exitCode = ui.exec_()
        sys_exit(exitCode)
    # sys.kill(sys.getpid(), signal.SIGTERM)
