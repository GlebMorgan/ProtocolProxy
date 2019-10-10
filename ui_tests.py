import sys
from time import sleep

from PyQt5.QtCore import Qt, QSize, QStringListModel, pyqtSignal, QRegExp, QTimer
from PyQt5.QtGui import QValidator, QFontMetrics, QPalette, QRegExpValidator
from PyQt5.QtWidgets import QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QDesktopWidget, QPushButton, \
    QComboBox, QAction, QLineEdit, QBoxLayout, QLabel, QLayout, QSizePolicy, QMenu, QActionGroup
from PyQt5Utils import ActionButton, ColoredComboBox, Validator, Colorer, ActionComboBox, ActionLineEdit, CommMode
from Utils import Logger, memoLastPosArgs, ConfigLoader, formatDict
from PyQt5Utils import SerialCommPanel


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



if __name__ == '__main__':

    app = QApplication([])
    app.setStyle('fusion')

    tb = TestButton('TEST')
    tb.clicked.connect(tb.inc)
    tb.show()
    sys.exit(app.exec_())