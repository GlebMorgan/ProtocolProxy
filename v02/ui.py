from functools import partial
from sys import argv, stdout, exit as sys_exit
from os.path import join as joinpath, expandvars as envar
from typing import Union

from PyQt5.QtCore import Qt, QSize, QStringListModel, pyqtSignal, QRegExp, QTimer
from PyQt5.QtGui import QValidator, QFontMetrics, QPalette, QRegExpValidator
from PyQt5.QtWidgets import QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QDesktopWidget, QPushButton, \
    QComboBox, QAction, QLineEdit, QBoxLayout, QLabel, QLayout, QSizePolicy
from PyQt5Utils import ActionButton, ColoredComboBox, Validator, Colorer, ActionComboBox, ActionLineEdit, CommMode
from PyQt5Utils.colorer import DisplayColor
from Utils import Logger, memoLastPosArgs, ConfigLoader, formatDict
from PyQt5Utils import SerialCommPanel
from app import App, ProtocolLoader, ApplicationError


# TODO: help functionality: tooltips, dedicated button (QT 'whatsThis' built-in), etc.

# TODO: Tab order

# TODO: New protocol adding

# ✓ Return exit status from app.commLoop somehow (from another thread)

# TODO: Move Extended widgets classes from CommPanel to PyQt5Utils.ExtendedWidgets
#       + Block class from ui.py

# TODO: window icon

# CONSIDER: disable animation

# CONSIDER: ui.py is launched - do not initialize protocol ui panel until user sets protocol explicitly
#           some_protocol.ui is launched - pull up main ui and init with executed protocol ui

log = Logger("UI")


class Block:
    def __init__(self, owner: Union[QLayout, QWidget], *, layout: Union[QLayout, str], spacing=None, margins=0):
        if isinstance(layout, str):
            if layout == 'v': layout = QVBoxLayout()
            if layout == 'h': layout = QHBoxLayout()
        self.layout = layout
        self.layout.setContentsMargins(*(margins,)*4)
        if spacing: self.layout.setSpacing(spacing)
        self.owner = owner

    def __enter__(self):
        return self.layout

    def __exit__(self, exc_type, exc_val, exc_tb):
        if isinstance(self.owner, QWidget):
            self.owner.setLayout(self.layout)
        elif isinstance(self.owner, QLayout):
            self.owner.addLayout(self.layout)


class UI(QApplication):
    protocolChanged = pyqtSignal(str)
    commStarted = pyqtSignal()
    commDropped = pyqtSignal()
    commFailed = pyqtSignal()
    commStopped = pyqtSignal()
    commError = pyqtSignal()
    commTimeout = pyqtSignal()

    def __init__(self, app, argv):
        super().__init__(argv)
        self.title = f"{app.PROJECT_NAME} v{app.VERSION} © 2019 GlebMorgan"
        self.app = app

        self.window = self.setUiWindow()
        self.root = QWidget(self.window)
        self.commPanel = SerialCommPanel(self.root, app.devInt)
        self.deviceCombobox = self.newDeviceCombobox(self.root)
        self.testButton1 = self.newTestButton(self.root, 1)
        self.testButton2 = self.newTestButton(self.root, 2)
        self.testButton3 = self.newTestButton(self.root, 3)
        self.testButton4 = self.newTestButton(self.root, 4)

        self.parseArgv(argv)
        self.setup()
        self.bindSignals()

    def setup(self):
        self.setStyle('fusion')
        self.initLayout(self.root)
        self.window.setCentralWidget(self.root)
        if self.app.device is None:
            self.commPanel.setDisabled(True)
        self.app.init()
        self.deviceCombobox.updateContents()
        self.window.show()

    def bindSignals(self):
        self.app.addHandler('comm started', self.commStarted.emit)
        self.app.addHandler('comm dropped', self.commDropped.emit)
        self.app.addHandler('comm timeout', self.commTimeout.emit)
        self.app.addHandler('comm error', self.commError.emit)
        self.app.addHandler('comm failed', self.commFailed.emit)
        self.app.addHandler('comm stopped', self.commStopped.emit)
        self.app.addHandler('protocol changed', self.protocolChanged.emit)
        self.app.addHandler('quit', self.quit)

        self.commPanel.bind(CommMode.Continuous, self.triggerContComm)
        self.commPanel.bind(CommMode.Manual, self.testSendPacketMock)
        # self.commPanel.bind(CommMode.Smart, self.testSendPacketMock)  # TEMP: uncomment in prod

        self.protocolChanged.connect(lambda: self.commPanel.setInterface(self.app.devInt))
        self.protocolChanged.connect(self.commPanel.updateSerialConfig)
        self.commFailed.connect(partial(self.commPanel.commButton.colorer.setBaseColor, DisplayColor.Red))

    def parseArgv(self, argv):
        if '-cmd' in argv: self.app.startCmdThread()

    def setUiWindow(self):
        this = QMainWindow()
        # self.centerWindowOnScreen(this)
        this.move(1200, 200)  # TEMP
        this.setWindowTitle(self.title)
        # this.setWindowIcon(QIcon("sampleIcon.jpg"))
        return this

    def initLayout(self, parent):
        fontSpacing = self.font().pointSize()
        with Block(parent, layout='v', spacing=fontSpacing, margins=fontSpacing) as main:
            with Block(main, layout='h', spacing=0) as toolpanel:
                toolpanel.addWidget(QLabel("Device", self.root))
                toolpanel.addWidget(self.deviceCombobox)
                toolpanel.addSpacing(fontSpacing)
                toolpanel.addWidget(self.commPanel)
                toolpanel.addStretch()
            with Block(main, layout='h', spacing=fontSpacing) as testpanel:
                testpanel.addWidget(self.testButton1)
                testpanel.addWidget(self.testButton2)
                testpanel.addWidget(self.testButton3)
                testpanel.addWidget(self.testButton4)
            main.addStretch()

    def newDeviceCombobox(self, parent):
        def updateContents(this):
            savedText = this.currentText()
            protocols = tuple(name.upper() for name in self.app.protocols.keys())
            self.deviceCombobox.addItems(protocols)
            self.deviceCombobox.setCurrentIndex(this.findText(savedText))

        this = QComboBox(parent=parent)  # TODO: QHoldFocusComboBox
        # TODO: this.setLineEdit(QAutoSelectLineEdit())
        this.setEditable(True)
        this.setInsertPolicy(QComboBox.NoInsert)
        this.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Maximum)

        this.updateContents = updateContents.__get__(this, this.__class__)
        this.lineEdit().editingFinished.connect(self.changeProtocol)  # TEMP: replace with this.triggered.<...>

        this.setToolTip("Device")
        return this

    def newTestButton(self, parent, n:int):
        this = QPushButton(f"Test{n}", parent)
        this.clicked.connect(getattr(self, f'testSlot{n}'))
        return this

    def changeProtocol(self):
        protocol = self.deviceCombobox.currentText().lower()
        if protocol == '': return None
        self.app.setProtocol(protocol)
        if self.app.device is not None:
            self.commPanel.setDisabled(False)

    def triggerContComm(self, state):
        if state is False:
            self.deviceCombobox.setDisabled(True)
            status = self.app.start()
        else:
            status = self.app.stop()
            self.deviceCombobox.setDisabled(False)
        return status

    def testSlot1(self):
        print(formatDict(self.app.events))

    def testSlot2(self):
        self.app.addHandler('updated', self.commPanel.testSlotL)

    def testSlot3(self):
        self.focusChanged.connect(lambda *args: print(f"Focus changed: {args}"))

    def testSlot4(self):
        self.commPanel.commButton.colorer.blink(DisplayColor.Red)
        print(self.commPanel.baudCombobox.lineEdit().setSelection(-1, 0))

    def testSendPacketMock(self):
        from random import randint
        fail = randint(0,1) == 0
        if fail:
            print('Emulate packet sent failure')
            return False
        else:
            print('Emulate packet sent success')
            return True

# ———————————————————————————————————————————————————————————————————————————————————————————————————————————————————— #

    @staticmethod
    def test_newAction(name, parent, slot, shortcut=None):
        this = QAction(name, parent)
        if shortcut: this.setShortcut(shortcut)
        this.triggered.connect(slot)
        log.debug(f"Action {name} created: {this}")
        return this

    def test_addWidgets(self):
        self.testButton1 = ActionButton("ActionButtonTest", parent=self.window, resize=True, show=True)
        self.testButton1.move(50, 0)
        self.testButton2 = ActionButton("&Test2", parent=self.window, resize=True, show=True)
        self.testButton2.move(200, 0)
        self.testCombobox = self.test_setTestCombobox()
        self.testCombobox.move(300, 0)
        self.testActionCombobox = self.test_setActionCombobox()
        self.testActionCombobox.move(300, 100)
        self.testComPanel = self.test_setTestComPanel()
        self.testComPanel.move(380, 0)
        self.testInputMaskLineEdit = self.test_setInputMaskLineEdit()
        self.testInputMaskLineEdit.move(500, 0)
        self.testLineEdit = self.test_setLineEdit()
        self.testLineEdit.move(100, 100)

        self.testButton2.clicked.connect(self.test)

    def test_setInputMaskLineEdit(self):

        this = QLineEdit(self.window)
        this.setInputMask('0->A-0')
        this.setText('8-N-1')
        this.setValidator(QRegExpValidator(QRegExp('[6789]-[OEN]-[12]')))
        this.resize(this.sizeHint())
        this.setMaximumWidth(50)
        this.show()
        return this

    def test_setLineEdit(self):
        this = ActionLineEdit(parent=self.window)
        this.setAction(self.test_newAction("TestLineEdit", this, lambda: print("ActionLineEdit triggered")))
        this.resize(this.sizeHint())
        this.show()
        return this

    def test_setActionCombobox(self):
        this = ActionComboBox(parent=self.window, resize=True, show=True)  # NOTE: kwargs break super()!
        this.setAction(self.test_newAction("TestActionComboBox", this, lambda: print("ActionCombobox triggered")))
        this.setValidator(Validator(this, validate=self.testComboboxValidate))
        this.addItems(('1', '2', '3'))
        this.resize(this.sizeHint())
        # this.show()
        return this

    def test_setTestComPanel(self):
        from Transceiver import PelengTransceiver
        from PyQt5Utils import SerialCommPanel

        this = SerialCommPanel(self.window, devInt=PelengTransceiver())
        return this

    def test_setTestCombobox(self):
        this = QComboBox(parent=self.window)
        this.addAction(self.test_newAction("TestComboBox", this, self.testComboboxActionTriggered))
        this.addItems((pName.upper() for pName in self.app.protocols if len(pName) < 8))
        this.addItems(('TK-275', 'SMTH'))
        this.resize(this.sizeHint())
        this.show()
        return this

    def testComboboxActionTriggered(self):
        log.info(f"{self.sender().text()}: new value → {self.sender().data()}")
        self.sender().parent().ack(True)

    @staticmethod
    def testComboboxValidate(validator, text, pos):
        text = text.upper().strip()

        if any(char in text for char in r'<>:"/\|?*'): newState = validator.Invalid
        elif text.endswith('.'): newState = validator.Intermediate
        else: newState = validator.Acceptable

        validator.triggered.emit(newState)
        if validator.state != newState:
            validator.state = newState
            validator.validationStateChanged.emit(newState)

        return validator.state, text, pos

    @staticmethod
    def testComboboxColorize(colorer):
        role = QPalette.Text
        text = colorer.target.currentText()
        items = colorer.target.model().stringList()
        if text == colorer.target.activeValue:
            return colorer.ColorSetting(role, Colorer.DisplayColor.Black)
        if text not in items:
            if any(item.startswith(text) for item in items):
                return colorer.ColorSetting(role, Colorer.DisplayColor.Blue)
            else: return colorer.ColorSetting(role, Colorer.DisplayColor.Red)
        else: return colorer.ColorSetting(role, Colorer.DisplayColor.Green)

    @staticmethod
    def testLineEditValidate(validator):
        ...


    def test(self):
        ...
        from PyQt5.QtGui import QColor
        color = QColor("aqua")
        palette = self.testLineEdit.palette()
        palette.setColor(QPalette.Base, color)
        self.testLineEdit.setPalette(palette)
        # self.testCombobox.lineEdit().setSelection(3, -2)
        # print(type(self.testComPanel.comChooserCombobox.view()))
