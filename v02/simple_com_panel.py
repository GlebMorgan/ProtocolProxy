from __future__ import annotations as annotations_feature

from functools import partial
import sys
from threading import Thread
from time import sleep
from typing import Union, Callable

from PyQt5.QtCore import Qt, QStringListModel, pyqtSignal, QPoint, QSize, QObject, QThread, pyqtSlot
from PyQt5.QtGui import QFont, QFontMetrics, QIcon, QMovie, QColor
from PyQt5.QtWidgets import QWidget, QApplication, QHBoxLayout, QComboBox, QAction, QPushButton, QMenu, QLabel, \
    QToolButton, QSizePolicy, QLineEdit

# TODO: check for actions() to be updated when I .addAction() to widget
from Utils import Logger
from Transceiver import SerialTransceiver
from serial.tools.list_ports_windows import comports


# Default layout spacing = 5
# Default ContentsMargins = 12

log = Logger("ComPanel")

def trap_exc_during_debug(*args):
    raise args[0]

sys.excepthook = trap_exc_during_debug

# TODO: tooltips


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


class WidgetActions:
    def __init__(self, owner: QWidget):
        self.owner: QWidget = owner

    def addAction(self, action: QAction):
        self.owner.addAction(action)
        setattr(self, action.text().lower(), action)

    def add(self, id: str, name: str, slot: Callable = None, shortcut: str = None):
        this = QAction(name, self.owner)
        if shortcut: this.setShortcut(shortcut)
        if slot: this.triggered.connect(slot)
        log.debug(f"Action '{name}' created, id={id}")
        setattr(self, id, this)

    def __getattr__(self, item):
        """ Mock for pyCharm syntax highlighter """
        raise AttributeError(f"Action '{item}' does not exist")


class ExtendedButton(QPushButton):
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


class SerialCommPanel(QWidget):

    def __init__(self, devInt, *args):
        super().__init__(*args)
        self.serialInt = devInt
        self.actionList = super().actions
        self.actions = WidgetActions(self)
        self.comUpdaterThread = None
        self.setupActions()

        self.startButton = self.newStartButton()
        self.commOptionsMenu = self.newCommOptionsMenu()
        self.commOptionsButton = self.newCommOptionsButton()
        self.comCombobox = self.newComCombobox()
        self.refreshPortsButton = self.newRefreshPortsButton()
        self.baudCombobox = self.newBaudCombobox()

        self.testLineEdit = self.newTestLineEdit()
        self.testLineEdit2 = self.newTestLineEdit()
        self.testLineEdit3 = self.newTestLineEdit()

        self.initLayout()
        self.setFixedSize(self.minimumSize())  # CONSIDER: SizePolicy is not working
        self.setStyleSheet('background-color: rgb(200, 255, 200)')

        self.updateComPortsAsync()

    def initLayout(self):
        spacing = self.font().pointSize()
        smallSpacing = spacing/4
        layout = QHBoxLayout()
        layout.setContentsMargins(*(smallSpacing,)*4)
        layout.setSpacing(0)
        layout.addWidget(self.startButton)
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
        self.setLayout(layout)

    def setupActions(self):
        testAction = QAction('Test', self)
        testAction.triggered.connect(lambda: print("test_action_triggered"))
        self.actions.add(id='test', name='Test Action', slot=lambda: print("test_action_triggered"))

    def newStartButton(self):
        this = ExtendedButton('Start', self)
        this.clicked.connect(lambda: print("click on button!"))
        this.lclicked.connect(self.testSlot)
        this.rclicked.connect(partial(self.dropStartButtonMenuBelow, this))
        return this

    def newCommOptionsMenu(self):
        this = QMenu(self)
        this.addAction(self.actions.test)
        return this

    def newCommOptionsButton(self):
        this = SqButton('▼', self)  # TODO: increases height with '🞃'
        this.clicked.connect(partial(self.dropStartButtonMenuBelow, self.startButton))
        # this.setMaximumWidth(18)
        return this

    def newComCombobox(self):
        this = QComboBox(parent=self)
        this.setModel(QStringListModel())
        this.setEditable(True)
        this.setInsertPolicy(QComboBox.NoInsert)
        this.view().setSizeAdjustPolicy(this.view().AdjustToContents)
        this.setStyleSheet('background-color: rgb(255, 200, 255)')
        # this.updateRequired.connect(self.updateComPorts)
        changeComPortAction = QAction('SwapPort', this)
        changeComPortAction.triggered.connect(self.changeSerialPort)  # TODO
        self.addAction(changeComPortAction)
        this.setValidator(None)  # TODO
        this.setItemData(0, 'azaza', Qt.ToolTipRole)  # CONSIDER: doesn't work inside App(), works when adding itemData to stand-alone widget
        return this

    def newRefreshPortsButton(self):
        this = SqButton(self)  # TODO: reload image and animation here
        this.clicked.connect(self.updateComPortsAsync)
        this.setIcon(QIcon(r"D:\GLEB\Python\refresh-gif-2.gif"))
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
        # changeComPortAction = QAction('SwapPort', this)
        # changeComPortAction.triggered.connect(self.changeSerialPort)  # TODO
        # self.addAction(changeComPortAction)
        # this.setValidator(None)  # TODO
        return this

    def newTestLineEdit(self):
        this = SymbolLineEdit("I", self, symbols=('N', 'E', 'O', 'S', 'M'))
        this.setAlignment(Qt.AlignCenter)
        this.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        # this.setMaximumSize(22, 22)
        return this

    def dropStartButtonMenuBelow(self, qWidget):
        self.commOptionsMenu.exec(self.mapToGlobal(qWidget.geometry().bottomLeft()))

    def getComPortsList(self):
        log.debug("Fetching com ports...")
        newComPortsList = []
        for i, port in enumerate(comports()):
            newComPortsList.append(port.device.strip('COM'))
            self.comCombobox.setItemData(i, port.description, Qt.ToolTipRole)  # CONSIDER: does not work... :(
        log.debug(f"New COM ports list: {newComPortsList} ({len(newComPortsList)} items)")
        # CONSIDER: adjust combobox drop-down size when update is performed with unfolded ports list
        return newComPortsList

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
        thread.finished.connect(self.refreshPortsButton.anim.stop)
        thread.finished.connect(partial(self.refreshPortsButton.anim.jumpToFrame, 0))
        thread.finished.connect(partial(setattr, self, 'comUpdaterThread', None))
        thread.finished.connect(partial(log.debug, f"Updating com ports: DONE"))
        self.comUpdaterThread = thread
        log.debug(f"Main thread ID: {int(QThread.currentThreadId())}")
        thread.start()

    def updateComCombobox(self, ports):
        if ports != self.comCombobox.model().stringList():
            self.comCombobox.clear()
            self.comCombobox.addItems(ports)
            # TODO: insert tooltips with port description
        log.info(f"COM ports refreshed: {', '.join('COM' + str(port) for port in ports)}")

    def changeSerialPort(self):
        sender = self.sender()
        log.debug(f"Changing serial port to COM{sender.data()}...")
        try:
            self.serialInt.close()
            self.serialInt.port = sender.data()
            self.serialInt.open()
        except Exception as e:
            log.error(e)
        else: log.info(f"Serial port changed to COM{sender.data()}")

    def testSlot(self, par=None):
        print(f"test: {par}")
        print(self.comCombobox.itemData(1, Qt.BackgroundRole))
        self.comCombobox.setItemData(1, QColor(Qt.red), Qt.BackgroundRole)
        print(self.comCombobox.itemData(1, Qt.BackgroundRole))

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
    w.show()

    # w = QWidget()
    # cb = QComboBox(w)
    # cb.addItem('a')
    # cb.addItem('b')
    # cb.setItemData(0, 'tt1', Qt.ToolTipRole)
    # cb.setItemData(1, 'tt2', Qt.ToolTipRole)
    # w.show()

    sys.exit(app.exec())
