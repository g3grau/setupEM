"""Non-modal plot surface, kept alive when closed so curves can be reopened."""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QWidget,QVBoxLayout,QHBoxLayout,QLabel,QDoubleSpinBox,QPlainTextEdit


class PlotWindow(QWidget):
    CLOSE_WITH_MAIN_WINDOW = True

    def __init__(self,owner,title,marker):
        super().__init__(owner,Qt.Window)
        self.setWindowTitle(title)
        screen=self.screen()
        if screen:
            area=screen.availableGeometry();self.resize(min(1400,int(area.width()*.9)),min(1000,int(area.height()*.9)))
        else:self.resize(1200,900)
        layout=QVBoxLayout(self);layout.setContentsMargins(6,6,6,6)
        row=QHBoxLayout();layout.addLayout(row)
        row.addWidget(QLabel('Readout (GHz)'))
        self.marker=QDoubleSpinBox();self.marker.setRange(marker.minimum(),marker.maximum());self.marker.setDecimals(marker.decimals())
        self.marker.setValue(marker.value());row.addWidget(self.marker)
        row.addWidget(QLabel('Click a curve to inspect its nearest native sample.'));row.addStretch()
        self.marker.valueChanged.connect(marker.setValue);marker.valueChanged.connect(self.marker.setValue)
        self.plot_layout=QVBoxLayout();layout.addLayout(self.plot_layout,1)
        self.readout=QPlainTextEdit();self.readout.setReadOnly(True);self.readout.setMaximumHeight(75)
        layout.addWidget(self.readout)

    def reveal(self):
        if self.isMinimized():self.showNormal()
        self.show();self.raise_();self.activateWindow()

    def set_readout(self,text):
        self.readout.setPlainText(text)
