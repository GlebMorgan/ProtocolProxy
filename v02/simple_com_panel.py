from __future__ import annotations as annotations_feature

from enum import Enum
from functools import partial
from random import randint
import sys
from threading import Thread
from time import sleep
from typing import Union, Callable, NewType, Tuple, List, Optional

from PyQt5.QtCore import Qt, QStringListModel, pyqtSignal, QPoint, QSize, QObject, QThread, pyqtSlot, QTimer, \
    QRegularExpression as QRegex, QEvent
from PyQt5.QtGui import QFont, QFontMetrics, QIcon, QMovie, QColor, QKeySequence, QIntValidator, \
    QRegularExpressionValidator as QRegexValidator
from PyQt5.QtWidgets import QWidget, QApplication, QHBoxLayout, QComboBox, QAction, QPushButton, QMenu, QLabel, \
    QToolButton, QSizePolicy, QLineEdit, QActionGroup, QGraphicsDropShadowEffect

from Utils import Logger, legacy, formatList, ignoreErrors
from Transceiver import SerialTransceiver, SerialError
from serial.tools.list_ports_common import ListPortInfo as ComPortInfo
from serial.tools.list_ports_windows import comports

from src.Experiments.colorer import Colorer, DisplayColor

# ———————————————————————————————————————————————————————————————————————————————————————————————————————————————————— #
# TEMP TESTME TODO FIXME NOTE CONSIDER

# ✓ Tooltips

# ? TODO: Check for actions() to be updated when I .addAction() to widget

# TODO: Add sub-loggers to enable/disable logging of specific parts of code

# TODO: Keyboard-layout independence option

# ✓ Do not accept and apply value in combobox's lineEdit when drop-down is triggered

# ———————————————————————————————————————————————————————————————————————————————————————————————————————————————————— #


# Default layout spacing = 5
# Default ContentsMargins = 12

log = Logger("ComPanel")


def trap_exc_during_debug(*args):
    raise RuntimeError(f'PyQt5 says "{args[1]}"')
sys.excepthook = trap_exc_during_debug


@legacy
class QAutoSelect(QWidget):
    def focusInEvent(self, QFocusEvent):
        self.selectInput()
        return super().focusInEvent(QFocusEvent)

    def mouseReleaseEvent(self, qMouseEvent):
        self.selectInput()
        return super().mouseReleaseEvent(qMouseEvent)

    def selectInput(self):
        try:
            QTimer().singleShot(0, self.selectAll)
        except AttributeError:
            QTimer().singleShot(0, self.lineEdit().selectAll)


@legacy
class QKeyModifierEventFilter(QObject):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.keysDown = set()

    def eventFilter(self, qObject, qEvent):
        print(qEvent)
        if qEvent.type() == QEvent.KeyPress:
            self.keysDown.add(qEvent.key())
            print(f"Key {qEvent.key().text()} ▼")
        if qEvent.type() == QEvent.KeyRelease:
            self.keysDown.remove(qEvent.key())
            print(f"Key {qEvent.key().text()} ▲")
        return super().eventFilter(qObject, qEvent)


class QDataAction(QAction):
    def triggerWithData(self, data):
        self.setData(data)
        self.trigger()


class WidgetActions(dict):
    def __init__(self, owner: QWidget):
        super().__init__()
        self.owner: QWidget = owner

    def addAction(self, action: QAction):
        self.owner.addAction(action)
        setattr(self, action.text().lower(), action)
        log.debug(f"Action '{action.text()}' created, id={action.text().lower()}")

    def add(self, id: str, *args, **kwargs):
        this = self.new(*args, **kwargs)
        setattr(self, id, this)

    def new(self, name: str, slot: Callable = None,
            shortcut: str = None, context: Qt.ShortcutContext = Qt.WindowShortcut):
        this = QDataAction(name, self.owner)
        if slot:
            this.slot = slot
            this.triggered.connect(slot)
        if shortcut:
            this.setShortcut(QKeySequence(shortcut))
            this.setShortcutContext(context)
        self.owner.addAction(this)
        self[name] = this
        return this

    def __getattr__(self, item):
        """ Mock for pyCharm syntax highlighter """
        raise AttributeError(f"Action '{item}' does not exist")


class QRightclickButton(QPushButton):
    rclicked = pyqtSignal()
    lclicked = pyqtSignal()

    def mouseReleaseEvent(self, qMouseEvent):
        if qMouseEvent.button() == Qt.RightButton:
            self.animateClick()
            self.rclicked.emit()
        elif qMouseEvent.button() == Qt.LeftButton:
            self.lclicked.emit()
        super().mouseReleaseEvent(qMouseEvent)


class QSqButton(QPushButton):
    def __init__(self, *args):
        super().__init__(*args)
        self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)

    def sizeHint(self):
        height = super().sizeHint().height()
        return QSize(height, height)


class QAutoSelectLineEdit(QLineEdit):
    def mouseReleaseEvent(self, qMouseEvent):
        if qMouseEvent.button() == Qt.LeftButton and QApplication.keyboardModifiers() & Qt.ControlModifier:
            QTimer().singleShot(0, self.selectAll)
        elif qMouseEvent.button() == Qt.MiddleButton:
            QTimer().singleShot(0, self.selectAll)
        return super().mouseReleaseEvent(qMouseEvent)


class QSymbolLineEdit(QAutoSelectLineEdit):
    def __init__(self, *args, symbols, **kwargs):
        super().__init__(*args, **kwargs)
        self.symbols = tuple(str(item) for item in symbols)

    def sizeHint(self):
        if isinstance(self.symbols, str):
            width = QFontMetrics(self.font()).horizontalAdvance(self.symbols)
        else:
            width = max(QFontMetrics(self.font()).horizontalAdvance(ch) for ch in self.symbols)
        height = super().sizeHint().height()
        self.setMaximumWidth(width+height/2)
        return QSize(width+height/2, super().sizeHint().height())


class ComPortUpdater(QObject):
    done = pyqtSignal()

    def __init__(self, comPanel: SerialCommPanel, *args):
        super().__init__(*args)
        self.target: SerialCommPanel = comPanel

    def getComPortsList(self):
        log.debug("Fetching com ports...")
        newComPortsList = []
        for i, port in enumerate(comports()):
            newComPortsList.append(port.device.strip('COM'))
            self.combobox.setItemData(i, port.description, Qt.ToolTipRole)
        log.debug(f"New COM ports list: {newComPortsList} ({len(newComPortsList)} items)")
        return newComPortsList

    def run(self):
        log.debug(f"Updating COM ports...")
        ports = self.getComPortsList()
        if ports != self.combobox.model().stringList():
            self.combobox.clear()
            self.combobox.addItems(ports)
        log.info(f"COM ports updated: {', '.join('COM' + str(port) for port in ports)}")

    def blockingTest(self):
        print(f"Updater thread ID: {int(QThread.currentThreadId())}")
        QApplication.instance().processEvents()
        for i in range(4):
            print(f"Com updater - iteration {i}")
            sleep(0.5)
        self.done.emit()


class QWorkerThread(QThread):
    done = pyqtSignal(object)

    def __init__(self, *args, name=None, target):
        super().__init__(*args)
        self.function = target
        if name is not None: self.setObjectName(name)

    def run(self):
        log.debug(f"Test thread ID: {int(QThread.currentThreadId())}")
        self.done.emit(self.function())


class CommMode(Enum):
    Continuous = 0
    Manual = 1
    Smart = 2


class SerialCommPanel(QWidget):

    def __init__(self, parent, devInt, *args):
        super().__init__(parent, *args)

        # Core
        self.serialInt: SerialTransceiver = devInt
        self.actionList = super().actions
        self.comUpdaterThread: QThread = None
        self.commMode: CommMode = CommMode.Continuous
        self.actions = WidgetActions(self)
        self.setActions()

        # Bindings
        self.commButtonClicked: Callable = lambda: None  # active binding
        self.continuousCommBinding: Callable = None
        self.smartCommBinding: Callable = None
        self.manualCommBinding: Callable = None

        # Widgets
        self.testButton = self.newTestButton()  # TEMP
        self.commButton = self.newCommButton()
        self.commOptionsButton = self.newCommOptionsButton()
        self.commOptionsMenu = self.newCommOptionsMenu()
        self.comCombobox = self.newComCombobox()
        self.refreshPortsButton = self.newRefreshPortsButton()
        self.baudCombobox = self.newBaudCombobox()
        self.bytesizeEdit = self.newDataFrameEdit(name='bytesize', chars=self.serialInt.BYTESIZES)
        self.parityEdit = self.newDataFrameEdit(name='parity', chars=self.serialInt.PARITIES)
        self.stopbitsEdit = self.newDataFrameEdit(name='stopbits', chars=(1, 2))

        # Setup
        self.initLayout()
        self.changeCommMode(self.commMode)
        self.updateComPortsAsync()

        self.setFixedSize(self.sizeHint())  # CONSIDER: SizePolicy is not working
        # self.setStyleSheet('background-color: rgb(200, 255, 200)')

    def initLayout(self):
        spacing = self.font().pointSize()
        smallSpacing = spacing/4
        layout = QHBoxLayout()
        layout.setContentsMargins(*(smallSpacing,)*4)
        layout.setSpacing(0)
        layout.addWidget(self.commButton)
        layout.addWidget(self.commOptionsButton)
        layout.addSpacing(spacing)
        layout.addWidget(QLabel("COM", self))
        layout.addSpacing(smallSpacing)
        layout.addWidget(self.comCombobox)
        layout.addWidget(self.refreshPortsButton)
        layout.addSpacing(spacing)
        layout.addWidget(QLabel("BAUD", self))
        layout.addSpacing(smallSpacing)
        layout.addWidget(self.baudCombobox)
        layout.addSpacing(spacing)
        layout.addWidget(QLabel("FRAME", self))
        layout.addSpacing(smallSpacing)
        layout.addWidget(self.bytesizeEdit)
        layout.addWidget(QLabel("–", self))
        layout.addWidget(self.parityEdit)
        layout.addWidget(QLabel("–", self))
        layout.addWidget(self.stopbitsEdit)
        layout.addSpacing(spacing)
        layout.addWidget(self.testButton)
        self.setLayout(layout)

    def setActions(self):
        new = self.actions.new

        self.actions.test = new(name='Test',
                                slot=self.testSlot)
        self.actions.changePort = new(name='Change COM port',
                                      slot=lambda: self.changeSerialConfig('port', self.comCombobox))
        self.actions.refreshPorts = new(name='Refresh COM ports',
                                        slot=self.updateComPortsAsync, shortcut=QKeySequence("Ctrl+R"))
        self.actions.changeBaud = new(name='Change COM baudrate',
                                      slot=lambda: self.changeSerialConfig('baudrate', self.baudCombobox))
        self.actions.changeBytesize = new(name='Change COM bytesize',
                                          slot=lambda: self.changeSerialConfig('bytesize', self.bytesizeEdit))
        self.actions.changeParity = new(name='Change COM parity',
                                        slot=lambda: self.changeSerialConfig('parity', self.parityEdit))
        self.actions.changeStopbits = new(name='Change COM stopbits',
                                          slot=lambda: self.changeSerialConfig('stopbits', self.stopbitsEdit))

        log.debug(f"Actions:\n{formatList(action.text() for action in self.actions.values())}")

    def newCommButton(self):
        def setName(this: QRightclickButton, mode=self.commMode):
            if mode == CommMode.Continuous:
                this.setText('Start' if self.serialInt.is_open else 'Stop')  # TEMP - consider passing parameter
                this.setToolTip("Start/Stop communication loop")
            elif mode == CommMode.Smart:
                this.setText('Send/Auto')
                this.setToolTip("Packets are sent automatically + on button click")
            elif mode == CommMode.Manual:
                this.setText('Send')
                this.setToolTip("Send single packet")
            else: raise AttributeError(f"Unsupported mode '{mode.name}'")

        this = QRightclickButton('Communication', self)
        this.setName = setName.__get__(this, this.__class__)
        this.rclicked.connect(partial(self.dropStartButtonMenuBelow, this))
        this.lclicked.connect(self.commButtonClicked)
        this.lclicked.connect(this.setName)  # TEMP - connect this slot later to a result of self.commButtonClicked
        this.lclicked.connect(
                lambda: self.serialInt.close() if self.serialInt.is_open else self.serialInt.open())  # TEMP
        this.setName()
        return this

    def newCommOptionsMenu(self):
        # CONSIDER: Radio button options are displayed as ✓ instead of • when using .setStyleSheet() on parent
        this = QMenu("Communication mode", self)
        actionGroup = QActionGroup(self)
        for mode in CommMode.__members__:
            action = actionGroup.addAction(QAction(f'{mode} mode', self))
            action.setCheckable(True)
            action.mode = CommMode[mode]
            action.triggered.connect(partial(setattr, self, 'commMode', CommMode[mode]))
            this.addAction(action)
            if mode == self.commMode.name: action.setChecked(True)
        actionGroup.triggered.connect(self.changeCommMode)
        this.group = actionGroup
        return this

    def newCommOptionsButton(self):
        this = QSqButton('▼', self)  # CONSIDER: increases height with '🞃'
        this.clicked.connect(partial(self.dropStartButtonMenuBelow, self.commButton))
        this.setToolTip("Communication mode")
        return this

    def newComCombobox(self):
        this = QComboBox(parent=self)
        this.contents = ()
        this.setLineEdit(QAutoSelectLineEdit())
        this.setEditable(True)
        this.setInsertPolicy(QComboBox.NoInsert)
        # this.lineEdit().setStyleSheet('background-color: rgb(200, 255, 200)')
        this.setFixedWidth(QFontMetrics(self.font()).horizontalAdvance('000') + self.height())
        this.lineEdit().editingFinished.connect(self.actions.changePort.trigger)
        this.setToolTip("COM port")
        # NOTE: .validator and .colorer are set in updateComCombobox()
        return this

    def newRefreshPortsButton(self):
        this = QSqButton(self)
        this.clicked.connect(self.actions.refreshPorts.trigger)
        this.setIcon(QIcon(r"D:\GLEB\Python\refresh-gif-2.gif"))  # TODO: manage ui resources
        this.setIconSize(this.sizeHint() - QSize(10,10))
        this.anim = QMovie(r"D:\GLEB\Python\refresh-gif-2.gif")
        this.anim.frameChanged.connect(lambda: this.setIcon(QIcon(this.anim.currentPixmap())))
        this.setToolTip("Refresh COM ports list")
        return this

    def newBaudCombobox(self):
        MAX_DIGITS = 7
        this = QComboBox(parent=self)
        this.maxChars = MAX_DIGITS
        this.setLineEdit(QAutoSelectLineEdit())
        this.setEditable(True)
        this.setInsertPolicy(QComboBox.NoInsert)
        this.setSizeAdjustPolicy(this.AdjustToContents)
        # this.lineEdit().setStyleSheet('background-color: rgb(200, 200, 255)')
        items = self.serialInt.BAUDRATES[self.serialInt.BAUDRATES.index(9600): self.serialInt.BAUDRATES.index(921600)+1]
        this.addItems((str(num) for num in items))
        this.setMaxVisibleItems(len(items))
        with ignoreErrors(): this.setCurrentIndex(items.index(self.serialInt.DEFAULT_CONFIG['baudrate']))
        this.setFixedWidth(QFontMetrics(self.font()).horizontalAdvance('0'*MAX_DIGITS) + self.height())
        log.debug(f"BaudCombobox: max items = {this.maxVisibleItems()}")
        this.lineEdit().editingFinished.connect(self.actions.changeBaud.trigger)
        this.setValidator(QRegexValidator(QRegex(rf"[1-9]{{1}}[0-9]{{0,{MAX_DIGITS-1}}}"), this))
        this.colorer = Colorer(widget=this, base=this.lineEdit())
        this.setToolTip("Baudrate (speed)")
        return this

    def newDataFrameEdit(self, name, chars):
        chars = tuple(str(ch) for ch in chars)
        this = QSymbolLineEdit("X", self, symbols=chars)
        this.setAlignment(Qt.AlignCenter)
        this.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        this.setText(str(self.serialInt.DEFAULT_CONFIG[name]))
        this.textEdited.connect(lambda text: this.setText(text.upper()))
        this.setValidator(QRegexValidator(QRegex('|'.join(chars), options=QRegex.CaseInsensitiveOption)))
        this.colorer = Colorer(this)
        this.editingFinished.connect(getattr(self.actions, f'change{name.capitalize()}').trigger)
        # this.setStyleSheet('background-color: rgb(255, 200, 200)')
        this.setToolTip(name.capitalize())
        return this

    def newTestButton(self):
        this = QRightclickButton('Test', self)
        this.clicked.connect(lambda: print("click on button!"))
        this.lclicked.connect(self.actions.test.trigger)
        this.setProperty('testField', True)
        this.setStyleSheet('*[testField="false"] {border-width: 2px; border-color: red;}')
        this.setToolTip("Test")
        return this

    def dropStartButtonMenuBelow(self, qWidget):
        self.commOptionsMenu.exec(self.mapToGlobal(qWidget.geometry().bottomLeft()))

    def changeCommMode(self, action: Union[QAction, CommMode]):
        if isinstance(action, CommMode): mode = action
        else: mode = action.mode
        log.debug(f"Changing communication mode to {mode}...")
        self.commMode = mode
        self.commButtonClicked = getattr(self, f'{mode.name.lower()}CommBinding')
        self.commButton.setName(mode)
        log.info(f"Communication mode ——► {mode.name}")

    @staticmethod
    def getComPortsList():
        log.debug("Fetching com ports...")
        newComPorts: List[ComPortInfo] = comports()
        log.debug(f"New com ports list: {', '.join(port.device for port in newComPorts)} ({len(newComPorts)} items)")
        return newComPorts

    def updateComPortsAsync(self):
        if self.comUpdaterThread is not None:
            log.debug("Update is already running - cancelled")
            return
        log.debug(f"Updating COM ports...")
        thread = QWorkerThread(self, name="Com ports refresh", target=self.getComPortsList)
        thread.done.connect(self.updateComCombobox)
        thread.started.connect(self.refreshPortsButton.anim.start)
        thread.finished.connect(self.finishUpdateComPorts)
        self.comUpdaterThread = thread
        log.debug(f"Main thread ID: {int(QThread.currentThreadId())}")
        thread.start()

    def finishUpdateComPorts(self):
        self.refreshPortsButton.anim.stop()
        self.refreshPortsButton.anim.jumpToFrame(0)
        self.comUpdaterThread = None
        log.debug(f"Updating com ports ——► DONE")

    def updateComCombobox(self, ports: List[ComPortInfo]):
        log.debug("Refreshing com ports combobox...")
        combobox = self.comCombobox
        currentPort = combobox.currentText()
        newPortNumbers = tuple((port.device.strip('COM') for port in ports))
        if combobox.contents != newPortNumbers:
            combobox.blockSignals(True)
            combobox.clear()
            combobox.addItems(newPortNumbers)
            combobox.blockSignals(False)
            for i, port in enumerate(ports):
                combobox.setItemData(i, port.description, Qt.ToolTipRole)
            combobox.setCurrentIndex(combobox.findText(currentPort))
            combobox.contents = newPortNumbers
            currentComPortsRegex = QRegex('|'.join(combobox.contents), options=QRegex.CaseInsensitiveOption)
            combobox.setValidator(QRegexValidator(currentComPortsRegex))
            combobox.colorer = Colorer(widget=combobox, base=combobox.lineEdit())  # TESTME: colorer
            combobox.validator().changed.connect(lambda: log.warning("Validator().changed() triggered"))  # TEMP
            if combobox.view().isVisible():
                combobox.hidePopup()
                combobox.showPopup()
            combobox.colorer.blink(DisplayColor.Blue)
            log.info(f"COM ports refreshed: {', '.join(f'COM{port}' for port in newPortNumbers)}")
        else:
            log.debug("Com ports refresh - no changes")

    def changeSerialConfig(self, setting: str, widget: Union[QComboBox, QLineEdit]) -> Optional[bool]:
        # FIXME: when caught error on open new port, lineEdit remains red even when port is made available
        try: value = widget.currentText()
        except AttributeError: value = widget.text()
        if setting == 'port' and self.comCombobox.view().hasFocus(): return None
        if value == '':
            log.debug(f"Serial {setting} is not chosen — cancelling")
            return None
        if setting == 'port': value = f'COM{value}'
        interface = self.serialInt
        if value.isdecimal(): value = int(value)
        currValue = getattr(interface, setting, None)
        if value == currValue:
            log.debug(f"{setting.capitalize()}={value} is already set — cancelling")
            return None
        try:
            setattr(interface, setting, value)
        except SerialError as e:
            log.error(e)
            widget.colorer.setBaseColor(DisplayColor.Red)
            return False
        else:
            log.info(f"Serial {setting} ——► {value}")
            widget.colorer.setBaseColor(DisplayColor.Background)
            widget.colorer.blink(DisplayColor.Green)
            return True

    def testSlot(self, par=...):
        if par is not ...: print(f"Par: {par}")
        print(f"Serial int: {self.serialInt}")
        print(f"Communication mode: {self.commMode.name}")
        # self.testButton.setProperty("testField", False)
        # self.testButton.setStyleSheet(self.testButton.styleSheet())
        # self.comCombobox.setStyleSheet('QComboBox:hover {color: hsv(120, 255, 255)}')
        effect = QGraphicsDropShadowEffect()
        effect.setOffset(0)
        effect.setBlurRadius(15)
        effect.setColor(Qt.green)
        QTimer().singleShot(500, lambda: self.testButton.setGraphicsEffect(effect))
        QTimer().singleShot(600, lambda: self.testButton.setGraphicsEffect(None))

# ———————————————————————————————————————————————————————————————————————————————————————————————————————————————————— #

    @legacy
    def updateComPorts(self):
        log.debug(f"Updating com ports...")
        self.refreshPortsButton.anim.start()
        ports = self.getComPortsList()
        if ports != self.comCombobox.model().stringList():
            self.comCombobox.clear()
            self.comCombobox.addItems(ports)
        self.refreshPortsButton.anim.stop()
        log.debug(f"Com ports updated")

    @legacy
    def changeSerialPort(self, newPort: str):
        # newPort = self.sender().data()
        if newPort == '':
            log.debug(f"Serial port is not chosen — cancelling")
            return
        currPort = self.serialInt.port.strip('COM') if self.serialInt.port is not None else None
        if newPort == currPort:
            log.debug(f"Serial port {currPort} is already set — cancelling")
            return
        else: newPort = 'COM' + newPort
        log.debug(f"Changing serial port from {currPort} to {newPort}...")
        try:
            self.serialInt.port = newPort
        except SerialError as e:
            log.error(e)
        else: log.info(f"Serial port ––► {newPort}")

    @legacy
    def changeBaud(self, newBaud):
        # newBaud = self.sender().data()
        log.debug(f"Changing serial baudrate to {newBaud}...")
        try:
            self.serialInt.baudrate = newBaud
        except SerialError as e:
            log.error(e)
        else: log.info(f"Serial baudrate ––► {newBaud}")

    @legacy
    def testCustomQThread(self):
        class TestThread(QThread):
            done = pyqtSignal(object)
            def __init__(self, *args, name=None, target):
                super().__init__(*args)
                self.function = target
                if name is not None:
                    self.setObjectName(name)
            def run(self):
                print(f"Test thread ID: {int(QThread.currentThreadId())}")
                self.done.emit(self.function())
        th = TestThread(name="Test_CustomQThread", target=self.blockingTest)
        th.started.connect(lambda: print("Custom QThread started"))
        th.finished.connect(lambda: print("Custom QThread finished"))
        th.done.connect(lambda value: print(f"Custom QThread: done signal emitted: {value}"))
        print(f"Main thread ID: {int(QThread.currentThreadId())}")
        th.start()
        self.comUpdaterThread = th

    @legacy
    def testPythonThreads(self):
        comUpdateThread = Thread(name="TestUpdateComs", target=self.blockingTest)
        comUpdateThread.start()

    @legacy
    def testQThread(self):
        comUpdaterThread = QThread(self)
        comUpdaterThread.setObjectName('ComUpdaterThread')
        self.comUpdater.moveToThread(comUpdaterThread)
        comUpdaterThread.started.connect(lambda: print("Thread started"))
        comUpdaterThread.started.connect(self.comUpdater.blockingTest)
        self.comUpdater.done.connect(comUpdaterThread.quit)
        self.comUpdater.done.connect(lambda: print("Done signal emitted"))
        comUpdaterThread.finished.connect(lambda: print("Thread finished"))
        print(f"Main thread ID: {int(QThread.currentThreadId())}")
        self.th = comUpdaterThread
        comUpdaterThread.start()

    @staticmethod
    @legacy
    def blockingTest():
        for i in range(4):
            print(f"Iteration {i}")
            sleep(0.5)
        return [1,2,5]







if __name__ == '__main__':
    app = QApplication(sys.argv)
    app.setStyle('fusion')

    # print(app.font().pointSize)
    # app.setFont(Chain(app.font()).setPointSize(10).ok)
    p = QWidget()
    p.setWindowTitle('Simple COM Panel - dev')
    tr = SerialTransceiver()
    cp = SerialCommPanel(p, tr)
    cp.resize(100, 20)
    cp.move(300, 300)

    # test=QPushButton('TestShortcut', w)
    # action = QAction('Test Shortcut Action')
    # action.setShortcut(QKeySequence("Ctrl+E"))
    # action.setShortcutContext(Qt.ApplicationShortcut)
    # w.addAction(action)
    # action.triggered.connect(lambda: print("Shortcut action triggered"))
    # # test.addAction(action)
    # # test.setShortcut(QKeySequence("Ctrl+R"))
    # test.clicked.connect(action.trigger)
    l = QHBoxLayout()
    l.addWidget(cp)
    p.setLayout(l)
    p.show()
    sys.exit(app.exec())



    class TestWidget(QWidget):
        def __init__(self, *args):
            super().__init__(*args)
            self.b = QPushButton("...", self)
            self.b.move(40, 0)
            self.b.clicked.connect(lambda: self.cb.setItemData(0, 'tt1', Qt.ToolTipRole))
            self.cb = self.newCb()

        def newCb(self):
            this = QComboBox(parent=self)
            this.setModel(QStringListModel())
            this.setEditable(True)
            this.addItem('a')
            this.addItem('b')
            # this.setItemData(0, 'tt1', Qt.ToolTipRole)
            this.setItemData(1, 'tt2', Qt.ToolTipRole)
            return this

    w = TestWidget()
    w.show()

    sys.exit(app.exec())
