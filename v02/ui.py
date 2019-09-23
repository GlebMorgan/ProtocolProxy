# CONSIDER: ui.py is launched - do not initialize protocol ui panel until user sets protocol explicitly
#           some_protocol.ui is launched - pull up main ui and init with executed protocol ui

# TODO: help functionality: tooltips, dedicated button (QT 'whatsThis' built-in), etc.

# TODO: disable animation

from sys import argv, stdout, exit as sys_exit

from PyQt5.QtCore import Qt, QSize, QStringListModel, pyqtSignal, QRegExp
from PyQt5.QtGui import QValidator, QFontMetrics, QPalette, QRegExpValidator
from PyQt5.QtWidgets import QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QDesktopWidget, QPushButton, \
    QComboBox, QAction, QLineEdit
from PyQt5Utils import ActionButton, ColoredComboBox, Validator, Colorer, ActionComboBox, ActionLineEdit
from Utils import Logger, memoLastPosArgs

from app import App


log = Logger("UI")


class UI(QApplication):

    def __init__(self, app, argv, *args):
        super().__init__(argv)
        self.app = app

        self.window = self.setUiWindow()
        self.test_addWidgets()

        self.settingsPane = self.setSettingsPane()

        self.parseArgv(argv)
        self.app.addHandler('quit', self.quit)
        self.app.init()

    def parseArgv(self, argv):
        if 'cmd' in argv: self.app.startCmdThread()

    def setUiWindow(self):
        this = QMainWindow()
        this.resize(650, 400)
        # self.centerWindowOnScreen(this)
        this.move(1250, 250)
        this.setWindowTitle(f"ProtocolProxy - v{self.app.VERSION} © GlebMorgan")
        # this.setWindowIcon(QIcon("sampleIcon.jpg"))
        this.show()
        return this

    def setSettingsPane(self):
        this = QWidget(self.window)
        toolpaneLayout = QHBoxLayout()

        toolpaneLayout.addStretch(1)

        this.setLayout(toolpaneLayout)
        this.resize(this.sizeHint())
        this.show()
        return this

    @staticmethod
    def centerWindowOnScreen(window):
        #                   ▼ ————— that is whole screen ————— ▼
        screenCenterPoint = QDesktopWidget().availableGeometry().center()
        windowFrame = window.frameGeometry()
        windowFrame.moveCenter(screenCenterPoint)
        window.move(windowFrame.topLeft())

# ———————————————————————————————————————————————————————————————————————————————————————————————————————————————————— #

    @staticmethod
    def test_newAction(name, parent, slot, shortcut=None):
        this = QAction(name, parent)
        if shortcut: this.setShortcut(shortcut)
        this.triggered.connect(slot)
        log.debug(f"Action {name} created: {this}")
        return this

    def test_addWidgets(self):
        self.testButton1 = ActionButton("ActionButtonTest", parent=self.window, resize=True, show=True)
        self.testButton1.move(50, 0)
        self.testButton2 = ActionButton("&Test2", parent=self.window, resize=True, show=True)
        self.testButton2.move(200, 0)
        self.testCombobox = self.test_setTestCombobox()
        self.testCombobox.move(300, 0)
        self.testActionCombobox = self.test_setActionCombobox()
        self.testActionCombobox.move(300, 100)
        self.testComPanel = self.test_setTestComPanel()
        self.testComPanel.move(380, 0)
        self.testInputMaskLineEdit = self.test_setInputMaskLineEdit()
        self.testInputMaskLineEdit.move(500, 0)
        self.testLineEdit = self.test_setLineEdit()
        self.testLineEdit.move(100, 100)

        self.testButton2.clicked.connect(self.test)

    def test_setInputMaskLineEdit(self):

        this = QLineEdit(self.window)
        this.setInputMask('0->A-0')
        this.setText('8-N-1')
        this.setValidator(QRegExpValidator(QRegExp('[6789]-[OEN]-[12]')))
        this.resize(this.sizeHint())
        this.setMaximumWidth(50)
        this.show()
        return this

    def test_setLineEdit(self):
        this = ActionLineEdit(parent=self.window)
        this.setAction(self.test_newAction("TestLineEdit", this, lambda: print("ActionLineEdit triggered")))
        this.resize(this.sizeHint())
        this.show()
        return this

    def test_setActionCombobox(self):
        this = ActionComboBox(parent=self.window, resize=True, show=True)  # NOTE: kwargs break super()!
        this.setAction(self.test_newAction("TestActionComboBox", this, lambda: print("ActionCombobox triggered")))
        this.setValidator(Validator(this, validate=self.testComboboxValidate))
        this.addItems(('1', '2', '3'))
        this.resize(this.sizeHint())
        # this.show()
        return this

    def test_setTestComPanel(self):
        from serial_transceiver import PelengTransceiver
        from test_com_panel import SerialCommPanel

        this = SerialCommPanel(self.window, devInt=PelengTransceiver())
        return this

    def test_setTestCombobox(self):
        this = ColoredComboBox(parent=self.window)
        this.setAction(self.test_newAction("TestComboBox", this, self.testComboboxActionTriggered))
        this.setValidator(Validator(this, validate=self.testComboboxValidate))
        this.setColorer(Colorer(this, colorize=self.testComboboxColorize))
        this.addItems((pName.upper() for pName in self.app.protocols if len(pName) < 8))
        this.addItems(('TK-275', 'SMTH'))
        this.resize(this.sizeHint())
        this.show()
        return this

    def testComboboxActionTriggered(self):
        log.info(f"{self.sender().text()}: new value → {self.sender().data()}")
        self.sender().parent().ack(True)

    @staticmethod
    def testComboboxValidate(validator, text, pos):
        text = text.upper().strip()

        if any(char in text for char in r'<>:"/\|?*'): newState = validator.Invalid
        elif text.endswith('.'): newState = validator.Intermediate
        else: newState = validator.Acceptable

        validator.triggered.emit(newState)
        if validator.state != newState:
            validator.state = newState
            validator.validationStateChanged.emit(newState)

        return validator.state, text, pos

    @staticmethod
    def testComboboxColorize(colorer):
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

    @staticmethod
    def testLineEditValidate(validator):
        ...


    def test(self):
        ...
        from PyQt5.QtGui import QColor
        color = QColor("aqua")
        palette = self.testLineEdit.palette()
        palette.setColor(QPalette.Base, color)
        self.testLineEdit.setPalette(palette)
        # self.testCombobox.lineEdit().setSelection(3, -2)
        # print(type(self.testComPanel.comChooserCombobox.view()))


if __name__ == '__main__':
    print(f"Launched with args: [{', '.join(argv)}]")
    # if not stdout.isatty() and 'cmd' not in argv: argv.append('cmd')

    with App() as core:
        ui = UI(core, argv)
        exitCode = ui.exec_()
        sys_exit(exitCode)
    # sys.kill(sys.getpid(), signal.SIGTERM)
