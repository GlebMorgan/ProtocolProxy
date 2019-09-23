from PyQt5.QtCore import Qt, pyqtSignal, QRegExp, QTimer, QThread
from PyQt5.QtGui import QPalette, QRegExpValidator
from PyQt5.QtWidgets import QWidget, QHBoxLayout, QAction
from PyQt5Utils import ColoredComboBox, NotifyingValidator, Colorer
from serial.tools.list_ports import comports
from Utils import memoLastPosArgs, threaded, Dummy, Logger, Context


log = Logger("ComPanel")


class ComChooserValidator(QRegExpValidator, NotifyingValidator):

    def __init__(self, *args):
        self.prefix = 'COM'
        super().__init__(QRegExp('[1-9]{1}[0-9]{0,2}'), *args)

    def validate(self, text, pos):
        if not text.startswith(self.prefix):
            newState, text, pos = super().validate(text, pos)
            if newState == self.Invalid:
                self.parent().lineEdit().setText(self.prefix)
                self.parent().lineEdit().setCursorPosition(len(self.prefix))
        else:
            newState, text, pos = super().validate(text[len(self.prefix):], pos-len(self.prefix))

        self.triggered.emit(newState)
        if self.state != newState:
            self.state = newState
            self.validationStateChanged.emit(newState)

        return newState, self.prefix + text, len(self.prefix) + pos


class SerialCommPanel(QWidget):

    class ComPortUpdaterThread(QThread):

        finished = pyqtSignal(list)
        instance = Dummy()

        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self.__class__.instance = self

        def run(self):
            self.finished.emit(self.parent().getComPortsList())

    def __init__(self, *args, devInt):
        super().__init__(*args)
        self.serialInt = devInt
        self.targetActions = {}
        self.comChooserCombobox = self.setComChooser()
        self.updateComPorts()
        self.initLayout()
        self.show()

    def initLayout(self):
        layout = QHBoxLayout()
        layout.setContentsMargins(0,0,0,0)
        layout.addWidget(self.comChooserCombobox)
        self.setLayout(layout)

    def setComChooser(self):
        this = ColoredComboBox(parent=self, default='COM', persistInput=ColoredComboBox.InputMode.Retain)
        this.lastInput = this.activeValue
        this.updateRequired.connect(self.updateComPorts)
        changeComPortAction = QAction('SwapPort', this)
        changeComPortAction.triggered.connect(self.changeSerialPort)
        self.targetActions[changeComPortAction.text()] = changeComPortAction
        this.setAction(changeComPortAction)
        this.setCompleter(None)
        this.setValidator(ComChooserValidator(this))
        this.setColorer(Colorer(this, colorize=self.comChooserColorize))
        return this

    def getComPortsList(self):
        newComPortsList = []
        for i, port in enumerate(comports()):
            newComPortsList.append(port.device)
            self.comChooserCombobox.setItemData(i, port.description, Qt.ToolTipRole)  # CONSIDER: does not work... :(
        log.info(f'COM ports updated: {len(newComPortsList)} items')
        return newComPortsList

    def updateComPorts(self):
        if self.ComPortUpdaterThread.instance.isRunning(): return
        comPortUpdaterThread = self.ComPortUpdaterThread(self)
        comPortUpdaterThread.finished.connect(lambda portsList: self.updateComChooserCombobox(portsList))
        comPortUpdaterThread.start()

    def updateComChooserCombobox(self, portsList):
        if portsList == self.comChooserCombobox.model().stringList(): return
        with Context(self.comChooserCombobox) as cBox:
            currentText = cBox.currentText()
            currentSelection = (
                cBox.lineEdit().selectionStart(),
                len(cBox.lineEdit().selectedText()),
            )

            cBox.blockSignals(True)
            cBox.clear()
            cBox.addItems(portsList)
            cBox.setCurrentIndex(cBox.findText(cBox.activeValue))
            cBox.blockSignals(False)

            cBox.setCurrentText(currentText)
            if cBox.view().hasFocus(): cBox.colorer.setColor(QPalette.Text, cBox.colorer.DisplayColor.Black)
            cBox.lineEdit().setSelection(*currentSelection)
            # cBox.adjustSize()
            cBox.view().adjustSize()  # CONSIDER: does not work... ;(
            cBox.colorer.blink(cBox.colorer.DisplayColor.Blue)

    @staticmethod
    def comChooserColorize(colorer):
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

    def changeSerialPort(self):
        sender = self.sender()
        try:
            self.serialInt.close()
            self.serialInt.port = sender.data()
            self.serialInt.open()
        except Exception as e:
            print(e)
            sender.parent().ack(False)
        else: sender.parent().ack(True)
