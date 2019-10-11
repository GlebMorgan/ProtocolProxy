from functools import partial

from PyQt5.QtCore import pyqtSignal, QRegularExpression as QRegex, QTimer
from PyQt5.QtGui import QRegularExpressionValidator as QRegexValidator, QIcon
from PyQt5.QtWidgets import QApplication, QMainWindow, QWidget, QSizePolicy
from PyQt5.QtWidgets import QPushButton, QComboBox, QLabel
from PyQt5Utils import Block, blockedSignals, setFocusChain
from PyQt5Utils import SerialCommPanel, QHoldFocusComboBox, QAutoSelectLineEdit, Colorer, DisplayColor
from Utils import Logger, formatDict
from pkg_resources import resource_filename

from app import ApplicationError

# ✓ Tab order

# TODO: New protocol adding

# ✓ Return exit status from app.commLoop somehow (from another thread)

# ✓ window icon

# CONSIDER: help functionality: tooltips, dedicated button (QT 'whatsThis' built-in), etc.

# CONSIDER: disable animation

# CONSIDER: ui.py is launched - do not initialize protocol ui panel until user sets protocol explicitly
#           some_protocol.ui is launched - pull up main ui and init with executed protocol ui

log = Logger("UI")

ICON = resource_filename(__name__, 'res/icon.png')


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

        self.commPanel.bind(SerialCommPanel.Mode.Continuous, self.triggerContComm)
        self.commPanel.bind(SerialCommPanel.Mode.Manual, self.testSendPacketMock)  # TODO: manual mode binding

        self.protocolChanged.connect(lambda: self.commPanel.setInterface(self.app.devInt))
        self.protocolChanged.connect(self.commPanel.updateSerialConfig)
        self.commFailed.connect(partial(self.commPanel.commButton.colorer.setBaseColor, DisplayColor.Red))

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
            with blockedSignals(this):
                this.clear()
                this.addItems(protocols)
            this.contents = protocols
            this.setValidator(QRegexValidator(QRegex('|'.join(this.contents), options=QRegex.CaseInsensitiveOption)))
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

    def newTestButton(self, parent, n:int):
        this = QPushButton(f"Test{n}", parent)
        this.clicked.connect(getattr(self, f'testSlot{n}'))
        return this

    def changeProtocol(self):
        protocol = self.deviceCombobox.currentText().upper()
        if protocol.strip() == '': return None
        if self.app.device is None:
            QTimer.singleShot(0, partial(self.commPanel.setDisabled, False))
            QTimer.singleShot(0, self.commPanel.setFocus)
        elif protocol == self.app.device.name:
            log.debug(f"Protocol '{protocol}' is already set — cancelling")
            return None
        try:
            self.app.setProtocol(protocol.lower())
        except ApplicationError as e:
            log.error(e)
            return False
        self.deviceCombobox.colorer.blink(DisplayColor.Green)
        return True

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
        self.commPanel.comCombobox.currentIndexChanged.connect(lambda idx: print(f'Changed {idx}'))

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
