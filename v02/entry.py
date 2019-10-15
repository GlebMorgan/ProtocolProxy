from functools import partial
from typing import Union, NamedTuple, Callable, Type, Optional

from PyQt5.QtGui import QIntValidator
from PyQt5.QtWidgets import QWidget, QCheckBox, QHBoxLayout, QLabel, QVBoxLayout, QPushButton
from PyQt5Utils import QAutoSelectLineEdit, Colorer, DisplayColor, install_exhook, QRightclickButton
from Utils import Logger

from device import Prop, Par
from notifier import Notifier

log = Logger("Entry")


class Entry(QWidget):
    def __init__(self, parent, target: Union[Par, Prop], name: str = None, *args,
                 label: bool, input: bool, echo: bool):

        super().__init__(parent, *args)

        self.name: str = name if name is not None else target.name
        self.par = target
        self.type: type = target.type

        if self.type is bool:
            if input:
                self.input = QCheckBox(self)
                self.signal = self.input.stateChanged
                self.fetcher = self.input.isChecked
                self.setter = self.input.setChecked
                self.widgetType = bool
            if echo:
                self.echo = QCheckBox(self)
                self.slot = self.echo.setChecked
        else:
            if self.type is not int:
                log.warning(f"Unsupported entry type {self.type}, number representation is used")
            if input:
                self.input = QAutoSelectLineEdit(self)
                self.input.setValidator(QIntValidator())  # CONSIDER: parameter value limits
                self.input.textEdited.connect(self.inputSetUpdated)  # CONSIDER: rename
                self.signal = self.input.editingFinished
                self.signal.connect(self.inputSetUpdated)
                self.fetcher = self.input.text
                self.setter = self.input.setText
                self.widgetType = str
            if echo:
                self.echo = QLabel(self)
                self.slot = self.echo.setText

        if label:
            self.label: QLabel = QLabel(f'{self.name}:', self)

        self.echo.setDisabled(True)
        self.echo.setVisible(False)

    def initLayout(self):
        fontSpacing = self.font().pointSize()
        layout = QHBoxLayout()
        layout.setSpacing(fontSpacing)

        for widgetName in ('label', 'input', 'echo'):
            try: layout.addWidget(getattr(self, widgetName))
            except AttributeError: pass
        layout.addStretch()

        # self.label.setStyleSheet('background-color: rgb(200, 200, 255)')  # TEMP
        # if hasattr(self, 'input'):
        #     self.input.setStyleSheet('background-color: rgb(200, 255, 200)')  # TEMP
        # self.echo.setStyleSheet('background-color: rgb(255, 200, 200)')  # TEMP

        self.setLayout(layout)

    def inputSetUpdated(self):
        try: colorize = self.input.colorer.setBaseColor
        except AttributeError: return

        try:
            currentValue = self.type(self.fetcher())
        except ValueError:
            colorize(DisplayColor.LightRed)
        else:
            if currentValue != self.par.value:
                colorize(DisplayColor.LightOrange)
            else:
                colorize(None)

    def showEcho(self):
        self.echo.setVisible(True)

    def updateEcho(self, value):
        self.slot(self.widgetType(value))


class PropEntry(Entry):

    def __init__(self, *args):
        super().__init__(*args, label=True, input=False, echo=True)

        Notifier.addHandler(f'{self.par.name} new', self.updateEcho)

        self.initLayout()


class ParEntry(Entry):

    def __init__(self, *args):
        super().__init__(*args, label=True, input=True, echo=True)
        self.input.colorer = Colorer(self.input)
        self.setter(self.widgetType(self.par.value))
        self.signal.connect(self.updatePar)

        Notifier.addHandler(f'{self.par.name} new', self.updateEcho)
        Notifier.addHandler(f'{self.par.name} cnn', self.showEcho)
        Notifier.addHandler(f'{self.par.name} upd', partial(self.input.colorer.setBaseColor, None))
        Notifier.addHandler(f'{self.par.name} upd', partial(self.input.colorer.blink, DisplayColor.Green))
        Notifier.addHandler(f'{self.par.name} uxp', partial(self.input.colorer.blink, DisplayColor.Red))

        self.initLayout()

    def updatePar(self):
        return self.par.set(self.type(self.fetcher()))

# ———————————————————————————————————————————————————————————————————————————————————————————————————————————————————— #


if __name__ == '__main__':
    import sys
    from PyQt5.QtWidgets import QApplication
    from random import randint

    install_exhook()

    app = QApplication(sys.argv)
    app.setStyle('fusion')

    p = QWidget()
    p.setWindowTitle('Simple COM Panel - dev')

    def sign(x): return 0 if x == 0 else int(x//abs(x))

    class TestDevice:
        testParInt = Par('ti', int)
        testParBool = Par('tb', bool)
        testPropInt = Prop('tpi', int)
        testPropBool = Prop('tpb', bool)

    dev = TestDevice()
    dev.testParInt = 7
    dev.testParBool = True
    dev.testPropInt = 42
    dev.testPropBool = False

    l = QVBoxLayout()

    PropInt = PropEntry(p, TestDevice.testPropInt, 'TestPropIntLabel')
    PropBool = PropEntry(p, TestDevice.testPropBool, 'TestPropBoolLabel')
    ParInt = ParEntry(p, TestDevice.testParInt, 'TestParIntLabel')
    ParBool = ParEntry(p, TestDevice.testParBool, 'TestParBoolLabel')

    TestParIntButton = QRightclickButton('Test ParInt', p)
    parObjInt = TestDevice.testParInt
    inc = lambda: sign(int(ParInt.input.text() or 0) - (parObjInt.status or parObjInt.value))
    TestParIntButton.lclicked.connect(lambda: parObjInt.ack((parObjInt.status or parObjInt.value) + inc()))
    TestParIntButton.rclicked.connect(lambda: parObjInt.ack(randint(1, 20)))

    TestParBoolButton = QRightclickButton('Test ParBool', p)
    parObjBool = TestDevice.testParBool
    TestParBoolButton.lclicked.connect(lambda: parObjBool.ack(
            parObjBool.value if randint(0, 3) == 0 else ParBool.input.isChecked()))
    TestParBoolButton.rclicked.connect(lambda: parObjBool.ack(bool(randint(0, 1))))

    TestPropIntButton = QRightclickButton('Test PropInt', p)
    TestPropIntButton.lclicked.connect(lambda: setattr(dev, 'testPropInt', randint(0, 20)))

    TestPropBoolButton = QRightclickButton('Test PropBool', p)
    TestPropBoolButton.lclicked.connect(lambda: setattr(dev, 'testPropBool', bool(randint(0, 1))))

    bl = QHBoxLayout()
    bl.addWidget(TestParIntButton)
    bl.addWidget(TestParBoolButton)
    bl.addWidget(TestPropIntButton)
    bl.addWidget(TestPropBoolButton)

    l.addWidget(PropInt)
    l.addWidget(PropBool)
    l.addWidget(ParInt)
    l.addWidget(ParBool)
    l.addStretch()
    l.addLayout(bl)

    p.setLayout(l)
    p.show()

    sys.exit(app.exec())