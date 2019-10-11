import sys
from functools import partial
from time import sleep

from PyQt5.QtCore import Qt, QSize, QStringListModel, pyqtSignal, QRegExp, QTimer
from PyQt5.QtGui import QValidator, QFontMetrics, QPalette, QRegExpValidator
from PyQt5.QtWidgets import QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QDesktopWidget, QPushButton, \
    QComboBox, QAction, QLineEdit, QBoxLayout, QLabel, QLayout, QSizePolicy, QMenu, QActionGroup, QGroupBox, \
    QRadioButton
from PyQt5Utils import ActionButton, ColoredComboBox, Validator, Colorer, ActionComboBox, ActionLineEdit, CommMode, \
    DisplayColor, QRightclickButton, install_exhook
from Utils import Logger, memoLastPosArgs, ConfigLoader, formatDict
from PyQt5Utils import SerialCommPanel, QIndicator


class TestButton(QPushButton):
    def __init__(self, *args):
        super().__init__(*args)
        self.i = 0

    def inc(self):
        self.setDown(True)
        self.repaint()
        print('down')
        sleep(1)
        self.setDown(False)
        print('up')


def blinkSimple(widget: QWidget, color: DisplayColor):
    widget.colorer.setBaseColor(color)
    QTimer.singleShot(100, widget.colorer.resetBaseColor)


class QIndicatorTest(QRadioButton):
    def __init__(self, *args):
        super().__init__(*args)
        self.setDisabled(True)
        self.colorer = Colorer(self, duration=120)
        self.blink = self.colorer.blink
        self.blinkHalo = self.colorer.blinkHalo

    def sizeHint(self):
        height = super().sizeHint().height()
        return QSize(height, height)


if __name__ == '__main__':

    install_exhook()

    app = QApplication([])
    app.setStyle('fusion')
    p = QWidget()
    p.layout = QHBoxLayout()
    p.setLayout(p.layout)
    p.layout.setContentsMargins(*(p.layout.spacing(),)*4)

    i = QIndicator(p)

    b = QRightclickButton('fire!', p)
    b.clicked.connect(partial(blinkSimple, i, DisplayColor.Green))
    b.rclicked.connect(partial(blinkSimple, i, DisplayColor.Orange))
    # b.move(30, 0)

    b2 = QRightclickButton('blink!', p)
    b2.clicked.connect(partial(i.blink, DisplayColor.Green))
    b2.rclicked.connect(partial(i.blink, DisplayColor.Orange))
    b2.mclicked.connect(partial(i.blink, DisplayColor.Red))
    # b2.move(120, 0)

    p.layout.addWidget(i)
    p.layout.addWidget(b)
    p.layout.addWidget(b2)

    print(b.height())

    p.show()
    sys.exit(app.exec_())