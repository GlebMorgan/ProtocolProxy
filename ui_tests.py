import sys
from functools import partial
from time import sleep

from PyQt5.QtCore import Qt, QSize, QStringListModel, pyqtSignal, QRegExp, QTimer
from PyQt5.QtGui import QValidator, QFontMetrics, QPalette, QRegExpValidator, QIntValidator
from PyQt5.QtWidgets import QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QDesktopWidget, QPushButton, \
    QComboBox, QAction, QLineEdit, QBoxLayout, QLabel, QLayout, QSizePolicy, QMenu, QActionGroup, QGroupBox, \
    QRadioButton, QCheckBox
from PyQt5Utils import ActionButton, ColoredComboBox, Validator, Colorer, ActionComboBox, ActionLineEdit, \
    DisplayColor, QRightclickButton, install_exhook
from Utils import Logger, memoLastPosArgs, ConfigLoader, formatDict
from PyQt5Utils import SerialCommPanel, QIndicator


if __name__ == '__main__':
    install_exhook()

    app = QApplication([])
    app.setStyle('fusion')

    # parent
    p = QWidget()
    p.layout = QHBoxLayout()
    p.layout.setContentsMargins(*(p.layout.spacing(),) * 4)
    p.setLayout(p.layout)

# ———————————————————————————————————————————————————————————————————————————————————————————————————————————————————— #
    # use app, p, p.layout


    p.layout.addWidget(...)
    p.layout.addWidget(QPushButton("Dummy"))

# ———————————————————————————————————————————————————————————————————————————————————————————————————————————————————— #

    p.show()
    sys.exit(app.exec_())