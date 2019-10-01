from functools import partial
from sys import argv, path as sys_path, exit as sys_exit
from threading import RLock, Thread, Event
from typing import NamedTuple, Tuple, List

from PyQt5.QtCore import Qt
from PyQt5.QtGui import QValidator
from PyQt5.QtWidgets import QApplication, QHBoxLayout, QVBoxLayout
from PyQt5.QtWidgets import QMainWindow, QWidget, QLabel, QLineEdit, QPushButton, QComboBox
from serial.tools.list_ports import comports

from Transceiver import PelengTransceiver, SerialError

sys_path.insert(0, r"D:\GLEB\Python\ComPortDataLogger")
from protocol import Protocol


class UI(QApplication):

    class ParamValidator(QValidator):
        def __init__(self, valRange:tuple, target:QLineEdit):
            super().__init__()
            self.valRange = valRange
            self.target = target
            self.numBase = 10

        def validate(self, text, pos):
            text = text.strip()
            if text == '':
                return self.Intermediate, text, pos
            if text.startswith('0x') or text.startswith('0b'):
                self.numBase = 16 if text.startswith('0x') else 2
                if len(text) == 2:
                    self.target.setStyleSheet('color: mediumblue')
                    return self.Intermediate, text, pos
            else: self.numBase = 10

            try:
                value = int(text, base=self.numBase)
            except (ValueError, SyntaxError):
                self.target.setStyleSheet('color: red')
                return self.Invalid, text, pos
            else:
                if value < min(self.valRange):
                    self.target.setStyleSheet('color: mediumblue')
                    return self.Intermediate, text, pos
                elif value in range(*self.valRange):
                    self.target.setStyleSheet('color: forestgreen')
                    return self.Acceptable, text, pos
                else:
                    self.target.setStyleSheet('color: red')
                    return self.Intermediate, text, pos

    class ParamEntry(NamedTuple):
        widget: QWidget = None
        idx: int = None
        name: str = None
        value: int = 0
        acceptableRange: Tuple[int, int] = None

    class Par(NamedTuple):
        idx: int = None
        val: int = None

    def __init__(self, argv, *args):
        super().__init__(argv)
        self.window = self.setUiWindow()
        self.protocol = Protocol.loadProtocol(
                r"D:\GLEB\Python\ComPortDataLogger\protocols\Sych_TPVK_Cube817_Command.protocol")
        self.tr = PelengTransceiver(14)
        self.port = 'COM1'

        self.paramLock = RLock()
        self.currParam = self.Par()
        self.paramEntries: List[UI.ParamEntry] = [
            (0,2),
            (0,2),
            None,
            (0,2),
            (0,2),
            (0,2),
            (0,2),
            (0,2),
            (0,2),
            (0,2),
            (0,2),
            (0,3),
            (0,2),
            (0,4),
            (0,2),
            None,
            (0,2**16),
            (0,2**16),
            (0,256),
            (0,56),
            (0,4),
            (0,49),
            (0,3),
            (0,4),
            (0,5),
            (0,5),
        ]
        for p in self.protocol.parameters:
            i = p.n - 1
            if self.paramEntries[i] is None: continue
            valueRange = self.paramEntries[i]
            self.paramEntries[i] = (self.ParamEntry(
                    widget=self.setParamEntry(p.name),
                    idx=i+1,
                    name=p.name,
                    acceptableRange=valueRange,
            ))

        self.settingsPanel = self.setSettingsPanel()
        self.paramsPanel = self.setParamsPanel()

        self.stopFlag = Event()
        self.commThread = None

        self.BASE_MSG = bytearray.fromhex('00 00 00 30 00 30 00 00 00 00 00')
        self.currMsg = bytearray(self.BASE_MSG)

    def setSettingsPanel(self):
        this = QWidget(self.window)

        this.comButton = QPushButton("Start", this)
        this.comButton.setCheckable(True)
        this.comButton.toggled.connect(self.toggleComm)
        this.comButton.resize(this.comButton.sizeHint())
        this.comButton.show()

        this.comChooser = QComboBox(this)
        this.comChooser.setEditable(True)
        this.comChooser.addItems(port.device for port in comports())
        this.comChooser.currentIndexChanged.connect(self.setComPort)
        this.comChooser.resize(this.comChooser.sizeHint())
        this.comChooser.show()

        this.sendButton = QPushButton("Send", this)
        this.sendButton.clicked.connect(self.sendSingle)
        this.sendButton.resize(this.sendButton.sizeHint())
        this.sendButton.show()

        layout = QHBoxLayout()
        layout.addWidget(this.comButton)
        layout.addWidget(this.comChooser)
        layout.addWidget(this.sendButton)
        this.setLayout(layout)
        this.show()

        return this

    def setUiWindow(self):
        this = QMainWindow()
        this.resize(310, 690)
        # self.centerWindowOnScreen(this)
        this.move(1550, 150)
        this.setWindowTitle(f"Sych-03 - ua640 Tests © GlebMorgan")
        # this.setWindowIcon(QIcon("sampleIcon.jpg"))
        this.show()
        return this

    def setParamEntry(self, name):
        this = QWidget(self.window)
        layout = QHBoxLayout()
        layout.setContentsMargins(0,0,0,0)

        this.label = QLabel(name)
        this.label.resize(this.label.sizeHint())

        this.edit = QLineEdit('')
        this.edit.resize(this.edit.sizeHint())

        layout.addWidget(this.label)
        layout.addWidget(this.edit)

        this.setLayout(layout)
        return this

    def setParamsPanel(self):
        this = QWidget(self.window)
        mainLayout = QVBoxLayout()
        mainLayout.addWidget(self.settingsPanel)
        for entry in self.paramEntries:
            if entry is None: continue
            entry.widget.edit.setText(str(entry.value))
            entry.widget.edit.editingFinished.connect(partial(self.setValue, entry))
            entry.widget.edit.setValidator(
                    self.ParamValidator(entry.acceptableRange, entry.widget.edit))
            mainLayout.addWidget(entry.widget, alignment=Qt.AlignTop)
        this.setLayout(mainLayout)
        this.resize(this.sizeHint())
        this.show()
        return this

    def setComPort(self, idx):
        sender = self.sender()
        comPortsList = (port.device for port in comports())
        newPort = sender.currentText()
        if newPort in comPortsList:
            if self.commThread and self.commThread.is_alive():
                print("Cannot change port - communication is running")
            else:
                try: self.tr.port = newPort
                except SerialError as e: print(e)
                print(f"Com port changed to '{newPort}'")
        else:
            if not newPort[3:].isdecimal():
                print("Invalid com port signifier. Type 'COM[n]'")
            else:
                print(f"Com port '{newPort}' does not exist in system")

    def setValue(self, entry):
        sender = self.sender()
        with self.paramLock:
            self.currParam = self.Par(entry.idx, int(sender.text(), sender.validator().numBase))
        sender.setStyleSheet('color: black')
        print(f"Entry #{self.currParam.idx} {entry.name} = {self.currParam.val}")

    @staticmethod
    def setPacketParams(parIdx, value):
        par = ui.protocol.parameters[parIdx - 1]
        bytesSegment = slice(par.bytesRange[0] - 1, par.bytesRange[1] - 1)
        parBytesSegment = bytes(ui.currMsg[bytesSegment])
        currentSegmentValue = int.from_bytes(parBytesSegment, 'big')
        newSegmentValue = (currentSegmentValue & ~par.mask) | (value << par.shift)
        ui.currMsg[bytesSegment] = newSegmentValue.to_bytes(
                par.bytesRange[1] - par.bytesRange[0], 'big', signed=False)

    def toggleComm(self, run):
        if not self.commThread or (run and not self.commThread.is_alive()):
            self.commThread = Thread(name="Communication", target=self.comm)
            self.commThread.start()
            self.settingsPanel.comButton.setText('Stop')
        elif not run and self.commThread.is_alive():
            self.stopFlag.set()
            self.commThread.join()
            self.stopFlag.clear()
            self.settingsPanel.comButton.setText('Start')
        else:
            print(f"Error: communication is already {'running' if run else 'stopped'}")

    def comm(self):
        print("Comm started")
        with self.tr as transceiver:
            with self.paramLock:
                oldParam = self.currParam

            while not self.stopFlag.wait(0.1):
                with self.paramLock:
                    oldParam = self.transaction(transceiver, oldParam)
        print("Comm stopped")

    def transaction(self, tr, oldParam):
        if oldParam != self.currParam: self.setPacketParams(*self.currParam)

        tr.sendPacket(bytes(self.currMsg))
        try: tr.receivePacket()
        except SerialError as e: print(e)

        return self.currParam

    def sendSingle(self):
        with self.tr as tr, self.paramLock:
            self.transaction(tr, None)




if __name__ == '__main__':
    try:
        print(f"Launched with args: [{', '.join(argv)}]")

        ui = UI(argv)
        print(f"\nProtocol parameters:\n{ui.protocol}\n")

        exit_code = ui.exec_()
        print(f"PyQt5 exit code: {exit_code}")

        sys_exit(exit_code)

    
        while True:
            with ui.tr as com:
                userinput = input('——►')

                if (userinput.strip() == ''): continue
                params = userinput.strip().split()
                command = params[0]

                if len(params) != 2:
                    print('Specify parameter number and target value')
                    continue

                try:
                    nPar = int(command)
                    if nPar not in range(1, 1 + len(ui.protocol.parameters)): raise ValueError
                except ValueError:
                    print("Incorrect parameter number")
                    continue

                try:
                    targetValue = int(params[1])
                except ValueError:
                    print("Incorrect target value")
                    continue

                par = ui.protocol.parameters[nPar - 1]
                bytesSegment = slice(par.bytesRange[0] - 1, par.bytesRange[1] - 1)
                parBytesSegment = bytes(ui.currMsg[bytesSegment])
                currentSegmentValue = int.from_bytes(parBytesSegment, 'big')
                newSegmentValue = (currentSegmentValue & ~par.mask) | (targetValue << par.shift)
                ui.currMsg[bytesSegment] = newSegmentValue.to_bytes(
                        par.bytesRange[1] - par.bytesRange[0], 'big', signed=False)
                # print(f"Bytes segment: was: {bytewise(parBytesSegment)}, became {bytewise(ui.currMsg[bytesSegment])}")

                com.sendPacket(bytes(ui.currMsg))
                try:
                    com.receivePacket()
                except SerialError as e:
                    print(e)
                    input()
    except Exception as e:
        print(e)
        input()
