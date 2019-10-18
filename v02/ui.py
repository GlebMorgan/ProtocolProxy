from functools import partial
from typing import Tuple, Iterable

from PyQt5.QtCore import pyqtSignal, QRegularExpression as QRegex, QTimer
from PyQt5.QtGui import QRegularExpressionValidator as QRegexValidator, QIcon
from PyQt5.QtWidgets import QApplication, QMainWindow, QWidget, QSizePolicy, QVBoxLayout, QStackedWidget
from PyQt5.QtWidgets import QPushButton, QComboBox, QLabel
from PyQt5Utils import Block, blockedSignals, setFocusChain
from PyQt5Utils import SerialCommPanel, QHoldFocusComboBox, QAutoSelectLineEdit, Colorer, DisplayColor
from PyQt5Utils.extended_widgets import QFixLabel
from Utils import Logger, formatDict
from pkg_resources import resource_filename

from app import ApplicationError, CONFIG
from device import Device
from entry import Entry

# ✓ Tab order

# ✗ New protocol adding

# ✓ Return exit status from app.commLoop somehow (from another thread)

# ✓ window icon

# TODO: Put maximum amount of parameters in CONFIG

# ✓ Fix window icon

# TODO: Communicate with NCS checkbox

# ✓ Some where-to-connect NCS UI hint

# TODO: Smart comm mode: trigger transaction on data from NCS and 'altered' events from Device

# TODO: Manual mode binding

# CONSIDER: help functionality: tooltips, dedicated button (QT 'whatsThis' built-in), etc.

# CONSIDER: disable animation

# CONSIDER: ui.py is launched - do not initialize protocol ui panel until user sets protocol explicitly
#           some_protocol.ui is launched - pull up main ui and init with executed protocol ui

log = Logger("UI")

ICON = resource_filename(__name__, 'res/icon_r.png')


class ControlPanel(QStackedWidget):
    def __init__(self, *args):
        super().__init__(*args)
        self.panels = {}

    def switch(self, device: Device):
        name = device.name.lower()
        if name not in self.panels.keys():
            self.panels[name] = self.newPanel(device)
        self.setCurrentWidget(self.panels[name])
        self.setMaximumHeight(self.panels[name].sizeHint().height())
        # return self.setCurrentIndex(0)

    def newPanel(self, params: Iterable):
        container = QWidget(self)
        container.entries = {}
        layout = QVBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        for par in params:
            entry = Entry(par, container)
            container.entries[par.name.lower()] = entry
            layout.addWidget(entry)
        container.setLayout(layout)
        self.addWidget(container)
        return container


class UI(QApplication):
    protocolChanged = pyqtSignal(str)
    commStarted = pyqtSignal()
    commDropped = pyqtSignal()
    commFailed = pyqtSignal()
    commStopped = pyqtSignal()
    commError = pyqtSignal()
    commTimeout = pyqtSignal()
    commOk = pyqtSignal()

    def __init__(self, app, argv):
        super().__init__(argv)

        self.title = f"{app.PROJECT_NAME} v{app.VERSION} © 2019 GlebMorgan"
        self.app = app

        self.window = self.setUiWindow()
        self.root = QWidget(self.window)
        self.root.spacing = self.font().pointSize()

        self.commPanel = SerialCommPanel(self.root, app.devInt)
        self.deviceCombobox = self.newDeviceCombobox(self.root)
        self.controlPanel = ControlPanel(self.root)
        self.ncsPortHint = self.newPortHintLabel(self.root)

        for i in range(1, 5):
            setattr(self, f'testButton{i}', self.newTestButton(self.root, i))

        self.parseArgv(argv)
        self.setup()
        self.bindSignals()

    def setup(self):
        self.setStyle('fusion')
        self.initLayout(self.root)
        self.window.setCentralWidget(self.root)
        if self.app.device is None:
            self.commPanel.setDisabled(True)
        else:
            self.changeProtocol(self.app.device.name)
        self.app.init()
        self.deviceCombobox.updateContents()
        setFocusChain(self.root, self.deviceCombobox, self.commPanel,
                      self.testButton1, self.testButton2, self.testButton3, self.testButton4)
        self.deviceCombobox.setFocus()
        self.window.show()

    def bindSignals(self):
        self.app.addHandler('comm started', self.commStarted.emit)
        self.app.addHandler('comm dropped', self.commDropped.emit)
        self.app.addHandler('comm ok', self.commOk.emit)
        self.app.addHandler('comm timeout', self.commTimeout.emit)
        self.app.addHandler('comm error', self.commError.emit)
        self.app.addHandler('comm failed', self.commFailed.emit)
        self.app.addHandler('comm stopped', self.commStopped.emit)
        self.app.addHandler('protocol changed', self.protocolChanged.emit)
        self.app.addHandler('quit', self.quit)

        # Communication bindings
        self.commPanel.bind(SerialCommPanel.Mode.Continuous, self.triggerContComm)
        self.commPanel.bind(SerialCommPanel.Mode.Manual, self.testSendPacketMock)

        # Update commPanel interface
        self.protocolChanged.connect(lambda: self.commPanel.setInterface(self.app.devInt))
        self.protocolChanged.connect(partial(self.ncsPortHint.setVisible, True))

        # Indicate communication failure
        self.commFailed.connect(partial(self.commPanel.commButton.colorer.setBaseColor, DisplayColor.Red))

        # Indicator blinking
        self.commOk.connect(partial(self.commPanel.indicator.blink, DisplayColor.Green))
        self.commTimeout.connect(partial(self.commPanel.indicator.blink, DisplayColor.Orange))
        self.commError.connect(partial(self.commPanel.indicator.blink, DisplayColor.Red))
        self.commFailed.connect(partial(self.commPanel.indicator.blink, DisplayColor.Red))

    def parseArgv(self, argv):
        if '-cmd' in argv: self.app.startCmdThread()

    def setUiWindow(self):
        this = QMainWindow()
        # self.centerWindowOnScreen(this)
        this.move(1200, 200)  # TEMP
        this.setWindowTitle(self.title)
        this.setWindowIcon(QIcon(ICON))
        return this

    def initLayout(self, parent):
        spacing = self.root.spacing
        with Block(parent, layout='v', spacing=spacing, margins=spacing, attr='mainLayout') as main:
            with Block(main, layout='h', spacing=0, attr='toolLayout') as tools:
                tools.addWidget(QFixLabel("Device", self.root))
                tools.addWidget(self.deviceCombobox)
                tools.addStretch(3)
                tools.addSpacing(spacing)
                tools.addWidget(self.commPanel)
            with Block(main, layout='v', spacing=spacing, attr='entriesLayout') as controls:
                controls.addWidget(self.ncsPortHint)
                controls.addWidget(self.controlPanel)
                controls.addStretch()
            with Block(main, layout='h', spacing=spacing, attr='testLayout') as test:
                test.addWidget(self.testButton1)
                test.addWidget(self.testButton2)
                test.addWidget(self.testButton3)
                test.addWidget(self.testButton4)

    def newDeviceCombobox(self, parent):
        def updateContents(this):
            savedText = this.currentText()
            protocols = tuple(name.upper() for name in self.app.protocols.keys())
            with blockedSignals(this):
                this.clear()
                this.addItems(protocols)
            this.contents = protocols
            this.setValidator(QRegexValidator(
                    QRegex('|'.join(this.contents), options=QRegex.CaseInsensitiveOption)))
            this.colorer.patchValidator()
            this.setCurrentIndex(this.findText(savedText))

        this = QHoldFocusComboBox(parent=parent)
        this.setLineEdit(QAutoSelectLineEdit())
        this.setEditable(True)
        this.colorer = Colorer(widget=this, base=this.lineEdit())
        this.contents = ()

        this.setInsertPolicy(QComboBox.NoInsert)
        this.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Maximum)

        this.updateContents = updateContents.__get__(this, this.__class__)
        this.triggered.connect(self.changeProtocol)
        this.lineEdit().textEdited.connect(lambda text: this.setText(text.upper()))

        this.setToolTip("Device")
        return this

    def newPortHintLabel(self, parent):
        this = QLabel(f"Connect native control soft to <b>{CONFIG.NATIVE_COM_PORT}</b>", parent)
        this.setVisible(False)
        return this

    def newTestButton(self, parent, n:int):
        this = QPushButton(f"Test{n}", parent)
        this.clicked.connect(getattr(self, f'testSlot{n}'))
        return this

    def changeProtocol(self, protocol=None):
        if protocol is None:
            protocol = self.deviceCombobox.currentText().upper()
        if protocol.strip() == '':
            return None

        if self.app.device is None:
            self.commPanel.setDisabled(False)
            self.commPanel.setFocus()
        elif protocol == self.app.device.name:
            log.debug(f"Protocol '{protocol}' is already set — cancelling")
            return None

        try:
            self.app.setProtocol(protocol.lower())
        except ApplicationError as e:
            log.error(e)
            return False

        self.controlPanel.switch(self.app.device)
        self.deviceCombobox.colorer.blink(DisplayColor.Green)
        return True

    def triggerContComm(self, state):
        if state is False:
            status = self.app.start()
        else:
            status = self.app.stop()
        self.deviceCombobox.setDisabled(status)
        return status

    def testSlot1(self):
        print(formatDict(self.app.events))
        self.commPanel.comCombobox.currentIndexChanged.connect(lambda idx: print(f'Changed {idx}'))

    def testSlot2(self):
        print(self.controlPanel.panels['sony'].layout().itemAt(0).widget().input.colorer.blinking)

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
