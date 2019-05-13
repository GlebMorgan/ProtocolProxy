import logging
import sys

from PyQt5.QtGui import QIcon
from PyQt5.QtWidgets import QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QAction
from PyQt5Utils import ActionButton
from colored_logger import ColorHandler

from fcb_ui import SonyUI
import tests

log = logging.getLogger(__name__ + ":main")
log.setLevel(logging.DEBUG)
log.addHandler(ColorHandler())
log.disabled = False


class Actions:
    def __init__(self):
        self.testAction: QAction = self.newAction(
                name="TestAction",
                slot=lambda: print("Test test test"),
                shortcut=None
        )

        self.testAction2: QAction = self.newAction(
                name='TestAction2',
                slot=lambda: print("azaza test"),
                shortcut='Ctrl+Shift+T'
        )

    @staticmethod
    def newAction(name, slot, shortcut=None):
        this = QAction(name)  # parent=self.window?
        if shortcut: this.setShortcut(shortcut)
        this.triggered.connect(slot)
        log.debug(f"Action {name} created: {this}")

        return this


class App(QApplication):

    def __init__(self, sonyUi: QWidget, argv):
        super().__init__(argv)
        self.window = self.setUiWindow()
        # self.sonyUiPanel = sonyUi
        self.actions = Actions()

        self.testButton = self.newButton('Test', self.actions.testAction, toggleable=True)
        self.testButton2 = self.newButton('Test2')
        self.testButton2.clicked.connect(lambda: print("test2 clicked"))
        self.testButton2.clicked.connect(lambda: self.actions.testAction.setToolTip("TEST"))
        print(f"testAction.toolTip: {self.actions.testAction.toolTip()}")
        self.desk = self.setDesk()

    def setUiWindow(self):
        this = QMainWindow()
        # setGeometry(x, y, w, h) == resize(w, h) + move(x, y)
        this.setGeometry(300, 600, 300, 220)
        this.setWindowTitle("ProtocolProxy - alpha")
        # this.setWindowIcon(QIcon("sampleIcon.jpg"))
        this.show()
        return this

    def setDesk(self):
        this = QWidget(self.window)
        windowLayout = QVBoxLayout()
        toolpanelLayout = QHBoxLayout()
        buttonsLayout = QHBoxLayout()

        buttonsLayout.addWidget(self.testButton)
        buttonsLayout.addWidget(self.testButton2)
        buttonsLayout.addStretch(1)

        windowLayout.addLayout(buttonsLayout)
        # windowLayout.addWidget(self.sonyUiPanel)
        windowLayout.addStretch(1)

        this.setLayout(windowLayout)
        self.window.setCentralWidget(this)

        return this

    def newButton(self, name, action=None, toggleable=False):
        if action:
            this = ActionButton(name, self.window, action=action)
        else:
            this = QPushButton(name, self.window)
        if toggleable: this.setCheckable(True)
        this.resize(this.sizeHint())
        this.show()
        log.debug(f"Button {name} created: {this}")
        return this

    def testSlot(self, caller):
        print(f"Sender: {self.sender().__class__.__name__} '{self.sender().text()}'")
        print(f"Caller: {str(caller)}")


if __name__ == '__main__':
    app = App(..., sys.argv)
    sys.exit(app.exec_())
