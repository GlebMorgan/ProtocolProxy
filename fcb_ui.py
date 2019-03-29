import utils
from PyQt5.QtWidgets import QWidget, QVBoxLayout, QPushButton

from fcb_protocol import SONY
from protocol import Protocol

log = utils.getLogger(__name__)


class SonyUI(QWidget):
    def __init__(self, sony: Protocol, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.setLayout(QVBoxLayout())
        self.layout().addWidget(QPushButton("test sony UI"))
        for par in sony.params:
            par.attach(self.paramsChanged)

    def paramsChanged(self, name: str, value):
        print(f"Parameter changed: '{name}' - '{value}'")
