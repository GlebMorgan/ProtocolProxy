import re
from enum import Enum

from PyQt5.QtCore import pyqtSignal, QRegExp
from PyQt5.QtGui import QValidator, QRegExpValidator
from PyQt5.QtWidgets import QWidget, QHBoxLayout, QAction
from PyQt5Utils import ValidatingComboBox
from PyQt5Utils.ActionComboBox import NotifyingValidator
from serial.tools.list_ports import comports
from utils import memoLastPosArgs


class ComChooserValidator(NotifyingValidator):

    def __init__(self, *args):
        self.prefix = 'COM'
        super().__init__(QRegExp('[1-9]{1}[0-9]{0,2}'), *args)

    # @memoLastPosArgs
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

        print(f"Final state: {newState}, text: '{text}', pos: {pos}")
        return newState, self.prefix + text, len(self.prefix) + pos


class SerialCommPanel(QWidget):

    def __init__(self, *args, devInt):
        super().__init__(*args)
        self.serialInt = devInt
        self.targetActions = {}
        self.comChooserCombobox = self.setComChooser()
        self.updateComPorts()
        self.initLayout()
        self.show()

        # TODO: refresh com ports list on hoover

    def updateComPorts(self):
        newComPortsList = []
        for i, port in enumerate(comports()):
            newComPortsList.append(port.device)
            self.comChooserCombobox.setItemData(i, port.description)
        if newComPortsList != self.comChooserCombobox.model().stringList():
            self.comChooserCombobox.clear()
            self.comChooserCombobox.addItems(newComPortsList)

    def setComChooser(self):
        changeComPortAction = QAction('SwapPort')
        changeComPortAction.triggered.connect(self.changeSerialPort)
        self.targetActions[changeComPortAction.text()] = changeComPortAction
        this = ValidatingComboBox(parent=self.parent())
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
        self.serialInt.port = self.comChooserCombobox.currentText()
