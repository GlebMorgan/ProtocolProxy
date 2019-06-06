import re
from enum import Enum

from PyQt5.QtCore import Qt, pyqtSignal, QRegExp, QTimer, QThread
from PyQt5.QtWidgets import QWidget, QHBoxLayout, QAction
from PyQt5Utils import ValidatingComboBox
from PyQt5Utils.ActionComboBox import NotifyingValidator
from context_proxy import Context
from serial.tools.list_ports import comports
from utils import memoLastPosArgs, threaded, Dummy

from serial_transceiver import SerialError


class ComChooserValidator(NotifyingValidator):

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
            self.instance = self

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

    def getComPortsList(self):
        # FIXME: update ValidatingComboBox.lastInput when comports are updated
        newComPortsList = []
        for i, port in enumerate(comports()):
            newComPortsList.append(port.device)
            self.comChooserCombobox.setItemData(i, port.description, Qt.ToolTipRole)  # FIXME
        print(f'COM ports updated: {len(newComPortsList)} items')
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
            print(f"Idx before: {cBox.currentIndex()} "),
            cBox.setCurrentIndex(
                    cBox.findText(cBox.activeValue))
            print(f"idx after: {cBox.currentIndex()}")
            cBox.blockSignals(False)
            cBox.setCurrentText(currentText)
            cBox.lineEdit().setSelection(*currentSelection)
            cBox.blink(cBox.DisplayColor.Blue)

    def setComChooser(self):
        changeComPortAction = QAction('SwapPort')
        changeComPortAction.triggered.connect(self.changeSerialPort)
        self.targetActions[changeComPortAction.text()] = changeComPortAction
        this = ValidatingComboBox(parent=self)
        this.updateRequired.connect(self.updateComPorts)  # FIXME UI hangs for a moment when system is updating config
        this.setAction(changeComPortAction)
        this.setCompleter(None)
        this.setValidator(ComChooserValidator(this))
        return this

    def initLayout(self):
        layout = QHBoxLayout()
        layout.setContentsMargins(0,0,0,0)
        layout.addWidget(self.comChooserCombobox)
        self.setLayout(layout)

    def changeSerialPort(self):
        try:
            self.serialInt.close()
            self.serialInt.port = self.comChooserCombobox.currentText()
            self.serialInt.open()
        except Exception as e: print(e)
        else: self.comChooserCombobox.ack()
