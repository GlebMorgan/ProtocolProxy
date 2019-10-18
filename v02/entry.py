from functools import partial
from typing import Union

from PyQt5.QtCore import pyqtSignal
from PyQt5.QtGui import QIntValidator
from PyQt5.QtWidgets import QWidget, QCheckBox, QHBoxLayout, QLabel, QVBoxLayout, QSizePolicy
from PyQt5Utils import QAutoSelectLineEdit, Colorer, DisplayColor, install_exhook, QRightclickButton
from Utils import Logger

from device import Prop, Par
from notifier import Notifier

log = Logger("Entry")


class Entry:
    def __new__(cls, target: Union[Par, Prop], *args, **kwargs):
        if isinstance(target, Par):
            return ParEntry(target, *args)
        elif isinstance(target, Prop):
            return PropEntry(target, *args)
        else:
            raise TypeError(f"Invalid target parameter type "
                            f"'{target.__class__.__name__}', expected 'Par' or 'Prop'")


class EntryBase(QWidget):

    valueChanged = pyqtSignal(object)

    def __init__(self, target: Union[Par, Prop], parent: QWidget, name: str = None, *args,
                 label: bool, input: bool, echo: bool):

        super().__init__(parent, *args)

        self.label: str = name if name is not None else target.label
        self.par = target
        self.type: type = target.type

        if self.type is bool:
            if input:
                self.input = QCheckBox(self)
                self.signal = self.input.stateChanged
                self.fetcher = self.input.isChecked
                self.setter = self.input.setChecked
            if echo:
                self.echo = QCheckBox(self)
                self.slot = self.echo.setChecked
                self.widgetType = bool
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
            if echo:
                self.echo = QLabel(self)
                self.slot = self.echo.setText
                self.widgetType = str

        if label:
            self.label: QLabel = QLabel(f'{self.label}:', self)

        self.echo.setDisabled(True)
        self.setSizePolicy(QSizePolicy.Minimum, QSizePolicy.Minimum)

    def sizeHint(self):
        return QAutoSelectLineEdit().sizeHint()

    def initLayout(self):
        fontSpacing = self.font().pointSize()
        layout = QHBoxLayout()
        layout.setSpacing(fontSpacing)
        layout.setContentsMargins(*(fontSpacing/4,)*4)

        for widgetName in ('label', 'input', 'echo'):
            try: layout.addWidget(getattr(self, widgetName))
            except AttributeError: pass
        layout.addStretch()

        # self.label.setStyleSheet('background-color: rgb(200, 200, 255)')  # TEMP
        # if hasattr(self, 'input'):
        #     self.input.setStyleSheet('background-color: rgb(200, 255, 200)')  # TEMP
        # self.echo.setStyleSheet('background-color: rgb(255, 200, 200)')  # TEMP

        self.setLayout(layout)

    def bindSignals(self):
        Notifier.addHandler(f'{self.par.name} new', self.valueChanged.emit)
        self.valueChanged.connect(self.updateEcho)

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

    def updateEcho(self, value):
        self.slot(self.widgetType(value))


class PropEntry(EntryBase):

    def __init__(self, *args):
        super().__init__(*args, label=True, input=False, echo=True)

        self.bindSignals()
        self.initLayout()


class ParEntry(EntryBase):

    valueInit = pyqtSignal(object)
    valueUpdated = pyqtSignal(object)
    valueUnexp = pyqtSignal(object)
    valueAltd = pyqtSignal(object)

    def __init__(self, *args):
        super().__init__(*args, label=True, input=True, echo=True)

        self.input.colorer = Colorer(self.input)
        self.echo.setVisible(False)

        self.setter(self.widgetType(self.par.value))
        self.signal.connect(self.updatePar)

        self.bindSignals()
        self.initLayout()

    def bindSignals(self):
        super().bindSignals()

        Notifier.addHandler(f'{self.par.name} cnn', self.valueInit.emit)
        Notifier.addHandler(f'{self.par.name} upd', self.valueUpdated.emit)
        Notifier.addHandler(f'{self.par.name} uxp', self.valueUnexp.emit)
        Notifier.addHandler(f'{self.par.name} alt', self.valueAltd.emit)

        self.valueInit.connect(self.initEcho)

        # sync / out of sync
        colorer = self.input.colorer
        self.valueUpdated.connect(partial(colorer.setBaseColor, None))
        self.valueUpdated.connect(partial(colorer.blink, DisplayColor.Green))
        self.valueUnexp.connect(partial(colorer.setBaseColor, DisplayColor.LightRed))
        self.valueUnexp.connect(partial(colorer.blink, DisplayColor.Red))

    def updatePar(self):
        return self.par.set(self.type(self.fetcher()))

    def initEcho(self):
        self.echo.setVisible(True)

        self.valueAltd.connect(lambda: self.input.colorer.setBaseColor(
                                           None if self.par.inSync else DisplayColor.LightRed))


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
        testParInt = Par('testParInt', 'ti', int)
        testParBool = Par('testParBool', 'tb', bool)
        testPropInt = Prop('testPropInt', 'tpi', int)
        testPropBool = Prop('testPropBool', 'tpb', bool)

    dev = TestDevice()
    dev.testParInt = 7
    dev.testParBool = True
    dev.testPropInt = 42
    dev.testPropBool = False

    l = QVBoxLayout()

    PropInt = PropEntry(TestDevice.testPropInt, p, 'TestPropIntLabel')
    PropBool = PropEntry(TestDevice.testPropBool, p, 'TestPropBoolLabel')
    ParInt = ParEntry(TestDevice.testParInt, p, 'TestParIntLabel')
    ParBool = ParEntry(TestDevice.testParBool, p, 'TestParBoolLabel')

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