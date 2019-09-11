from __future__ import annotations as annotations_feature

from enum import Enum
from functools import partial
import sys
from threading import Thread
from time import sleep
from typing import Union, Callable, NewType, Tuple, List

from PyQt5.QtCore import Qt, QStringListModel, pyqtSignal, QPoint, QSize, QObject, QThread, pyqtSlot, QTimer
from PyQt5.QtGui import QFont, QFontMetrics, QIcon, QMovie, QColor, QKeySequence
from PyQt5.QtWidgets import QWidget, QApplication, QHBoxLayout, QComboBox, QAction, QPushButton, QMenu, QLabel, \
    QToolButton, QSizePolicy, QLineEdit, QActionGroup

from Utils import Logger, legacy, formatList
from Transceiver import SerialTransceiver
from serial.tools.list_ports_common import ListPortInfo as ComPortInfo
from serial.tools.list_ports_windows import comports


# Default layout spacing = 5
# Default ContentsMargins = 12

log = Logger("ComPanel")

def trap_exc_during_debug(*args):
    raise args[0]

sys.excepthook = trap_exc_during_debug

# ———————————————————————————————————————————————————————————————————————————————————————————————————————————————————— #
# TEMP TESTME TODO FIXME NOTE CONSIDER

# TODO: tooltips

# TODO: check for actions() to be updated when I .addAction() to widget

# TODO: add sub-loggers to enable/disable logging of specific parts of code

# ———————————————————————————————————————————————————————————————————————————————————————————————————————————————————— #


class Chain:
    def __init__(self, obj):
        self.target = obj
        self.methodname = None

    def __getitem__(self, item: str):
        """ getattribute() for internal use """
        return object.__getattribute__(self, item)

    def __getattribute__(self, item):
        if item in ('ok', 'end', 'apply'):
            return self['target']
        if item.startswith('__') and item.endswith('__'):
            return self[item]
        self.methodname = item
        method = getattr(self['target'], item)
        if not hasattr(method, '__call__'):
            raise TypeError(f"'{type(method).__name__}' object '{method}' is not callable")
        return self

    def __call__(self, *args, **kwargs):
        # if self['method'].__func__(self['target'], *args, **kwargs) is not None:
        if getattr(self['target'], self['methodname'])(*args, **kwargs) is not None:
            raise RuntimeError(f"Method '{self['methodname']}' returned non-None value, cannot use Chain")
        return self

    def __repr__(self): return f"Chain wrapper of {self['target']} object at {hex(id(self))}"


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
            this.triggered.connect(slot)
        if shortcut:
            this.setShortcut(QKeySequence(shortcut))
            this.setShortcutContext(context)
        self.owner.addAction(this)
        self[name] = this
        log.debug(f"Action '{name}' created")
        return this

    def __getattr__(self, item):
        """ Mock for pyCharm syntax highlighter """
        raise AttributeError(f"Action '{item}' does not exist")


class RightclickButton(QPushButton):
    rclicked = pyqtSignal()
    lclicked = pyqtSignal()

    def mouseReleaseEvent(self, qMouseEvent):
        if qMouseEvent.button() == Qt.RightButton:
            self.animateClick()
            self.rclicked.emit()
        elif qMouseEvent.button() == Qt.LeftButton:
            self.lclicked.emit()
        super().mouseReleaseEvent(qMouseEvent)


class SqButton(QPushButton):
    def __init__(self, *args):
        super().__init__(*args)
        self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)

    def sizeHint(self):
        height = super().sizeHint().height()
        return QSize(height, height)


class SymbolLineEdit(QLineEdit):
    def __init__(self, *args, symbols):
        super().__init__(*args)
        self.symbols = symbols

    def sizeHint(self):
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
            self.combobox.setItemData(i, port.description, Qt.ToolTipRole)  # CONSIDER: does not work... :(
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

    def __init__(self, devInt, *args):
        super().__init__(*args)

        # Core
        self.serialInt = devInt
        self.actionList = super().actions
        self.comUpdaterThread = None
        self.commMode = CommMode.Continuous
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
        self.testLineEdit = self.newTestLineEdit()
        self.testLineEdit2 = self.newTestLineEdit()
        self.testLineEdit3 = self.newTestLineEdit()

        # Setup
        self.initLayout()
        self.changeCommMode(self.commMode)
        self.updateComPortsAsync()

        self.setFixedSize(self.minimumSize())  # CONSIDER: SizePolicy is not working
        self.setStyleSheet('background-color: rgb(200, 255, 200)')

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
        layout.addWidget(self.testLineEdit)
        layout.addWidget(QLabel("–", self))
        layout.addWidget(self.testLineEdit2)
        layout.addWidget(QLabel("–", self))
        layout.addWidget(self.testLineEdit3)
        layout.addSpacing(spacing)
        layout.addWidget(self.testButton)
        self.setLayout(layout)

    def setActions(self):
        new = self.actions.new
        self.actions.test = new(
                name='Test', slot=self.testSlot)
        self.actions.changePort = new(
                name='Change COM port', slot=self.changeSerialPort)
        self.actions.refreshPorts = new(
                name='Refresh COM ports', slot=self.updateComPortsAsync, shortcut=QKeySequence("Ctrl+R"))

    def newCommButton(self):
        def setName(self: RightclickButton):
            if self.parent().commMode == CommMode.Continuous:
                self.setText('Stop' if self.text() == 'Start' else 'Start')  # TEMP - consider passing parameter
        this = RightclickButton('Communication', self)
        this.setName = setName.__get__(this, this.__class__)
        this.rclicked.connect(partial(self.dropStartButtonMenuBelow, this))
        this.lclicked.connect(self.commButtonClicked)
        this.lclicked.connect(this.setName)  # TEMP - connect this slot later to a result of self.commButtonClicked
        this.lclicked.connect(lambda: self.serialInt.close() if self.serialInt.is_open else self.serialInt.open())  # TEMP
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
        actionGroup.triggered.connect(lambda x: log.debug(f"Communication mode set: {x.text()}"))
        actionGroup.triggered.connect(self.changeCommMode)
        this.group = actionGroup
        return this

    def newCommOptionsButton(self):
        this = SqButton('▼', self)  # TODO: increases height with '🞃'
        this.clicked.connect(partial(self.dropStartButtonMenuBelow, self.commButton))
        return this

    def newComCombobox(self):
        this = QComboBox(parent=self)
        this.setEditable(True)
        this.setInsertPolicy(QComboBox.NoInsert)
        # CONSIDER: ▼ adjust combobox drop-down size when update is performed with unfolded ports list
        # this.view().setSizeAdjustPolicy(this.view().AdjustToContents)
        this.setStyleSheet('background-color: rgb(255, 200, 255)')
        this.currentIndexChanged[str].connect(self.actions.changePort.triggerWithData)
        this.setValidator(None)  # TODO: setValidator()
        return this

    def newRefreshPortsButton(self):
        this = SqButton(self)
        this.clicked.connect(self.actions.refreshPorts.trigger)
        this.setIcon(QIcon(r"D:\GLEB\Python\refresh-gif-2.gif"))  # TODO: manage ui resources
        this.setIconSize(this.sizeHint() - QSize(10,10))
        this.anim = QMovie(r"D:\GLEB\Python\refresh-gif-2.gif")
        this.anim.frameChanged.connect(lambda: this.setIcon(QIcon(this.anim.currentPixmap())))
        return this

    def newBaudCombobox(self):
        this = QComboBox(parent=self)
        this.setModel(QStringListModel())
        this.setEditable(True)
        this.setInsertPolicy(QComboBox.NoInsert)
        this.view().setSizeAdjustPolicy(this.view().AdjustToContents)
        this.setStyleSheet('background-color: rgb(200, 255, 255)')
        this.insertItem(0, '11000000')
        # self.addAction(changeComPortAction)
        # this.setValidator(None)  # TODO
        return this

    def newTestLineEdit(self):
        this = SymbolLineEdit("I", self, symbols=('N', 'E', 'O', 'S', 'M'))
        this.setAlignment(Qt.AlignCenter)
        this.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        # this.setMaximumSize(22, 22)
        return this

    def newTestButton(self):
        this = RightclickButton('Test', self)
        this.clicked.connect(lambda: print("click on button!"))
        this.lclicked.connect(self.actions.test.trigger)
        return this

    def dropStartButtonMenuBelow(self, qWidget):
        self.commOptionsMenu.exec(self.mapToGlobal(qWidget.geometry().bottomLeft()))

    def changeCommMode(self, action: Union[QAction, CommMode]):
        if isinstance(action, CommMode): mode = action
        else: mode = action.mode
        log.debug(f"Changing communication mode to {mode}")

        button = self.commButton
        self.commMode = mode

        if mode == CommMode.Continuous:
            self.commButtonClicked = self.continuousCommBinding

        elif mode == CommMode.Smart:
            self.commButtonClicked = self.smartCommBinding
            button.setText('Send')
        elif mode == CommMode.Manual:
            self.commButtonClicked = self.manualCommBinding
            button.setText('Send')
        else: raise AttributeError(f"Unsupported mode '{mode.name}'")

    @staticmethod
    def getComPortsList():
        log.debug("Fetching com ports...")
        newComPorts: List[ComPortInfo] = comports()
        log.debug(f"New com ports list: {', '.join(port.device for port in newComPorts)} ({len(newComPorts)} items)")
        return newComPorts

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
        log.debug(f"Updating com ports: DONE")

    def updateComCombobox(self, ports: List[ComPortInfo]):
        log.debug("Refreshing com ports combobox...")
        combobox = self.comCombobox
        currentPort = combobox.currentText()
        currentPortNumbers = tuple(combobox.itemText(i) for i in range(combobox.count()))
        newPortNumbers = tuple((port.device.strip('COM') for port in ports))
        if currentPortNumbers != newPortNumbers:
            combobox.blockSignals(True)
            combobox.clear()
            combobox.addItems((port.device.strip('COM') for port in ports))
            combobox.blockSignals(False)
            for i, port in enumerate(ports):
                combobox.setItemData(i, port.description, Qt.ToolTipRole)
            combobox.setCurrentIndex(combobox.findText(currentPort))
            log.info(f"COM ports refreshed: {', '.join(f'COM{port}' for port in newPortNumbers)}")
        else:
            log.debug("Com ports refresh - no changes")

    def changeSerialPort(self):
        newPort = self.sender().data()
        if newPort is '': return
        else: newPort = 'COM' + newPort
        log.debug(f"Changing serial port to {newPort}...")
        try:
            with self.serialInt.reopen():
                self.serialInt.port = newPort
        except Exception as e:
            log.error(e)
        else: log.info(f"Serial port changed to {newPort}")

    def testSlot(self, par=None):
        print(f"Port is open? {self.serialInt.is_open}")
        print(f"Communication mode: {self.commMode.name}")

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

    def testPythonThreads(self):
        comUpdateThread = Thread(name="TestUpdateComs", target=self.blockingTest)
        comUpdateThread.start()

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

    tr = SerialTransceiver()
    w = SerialCommPanel(tr)
    w.resize(100, 20)
    w.move(300, 300)
    w.setWindowTitle('Sample')

    # test=QPushButton('TestShortcut', w)
    # action = QAction('Test Shortcut Action')
    # action.setShortcut(QKeySequence("Ctrl+E"))
    # action.setShortcutContext(Qt.ApplicationShortcut)
    # w.addAction(action)
    # action.triggered.connect(lambda: print("Shortcut action triggered"))
    # # test.addAction(action)
    # # test.setShortcut(QKeySequence("Ctrl+R"))
    # test.clicked.connect(action.trigger)

    w.show()
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
