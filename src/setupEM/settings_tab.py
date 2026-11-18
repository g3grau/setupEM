"""Solver-specific runtime parallelism, separate from mesh/boundary settings."""
from PySide6.QtWidgets import QWidget, QVBoxLayout, QGroupBox, QFormLayout, QSpinBox, QComboBox, QLabel


class SettingsTab(QWidget):
    def __init__(self, window):
        super().__init__()
        self.window = window
        layout = QVBoxLayout(self)
        self.openems_group = QGroupBox('openEMS execution')
        form = QFormLayout(self.openems_group)
        self.openems_threads = self._count('Automatic (solver default)')
        self.openems_threads.setToolTip('Automatic omits numThreads and lets openEMS select/tune the thread count. A positive value fixes it. No -1 value is sent to the solver.')
        form.addRow('Solver threads', self.openems_threads)
        self.openems_engine = QComboBox()
        self.openems_engine.addItem('CPU (default)', 'cpu')
        self.openems_engine.addItem('GPU (requires compatible openEMS build)', 'gpu')
        self.openems_engine.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.openems_engine.setMinimumContentsLength(16)
        form.addRow('Execution engine', self.openems_engine)
        layout.addWidget(self.openems_group)
        self.palace_group = QGroupBox('Palace execution')
        form = QFormLayout(self.palace_group)
        self.palace_mpi = self._count('Launcher default (unset)')
        self.palace_threads = self._count('Launcher default (unset)')
        self.palace_blas = self._count('Library default (unset)')
        form.addRow('MPI processes', self.palace_mpi)
        form.addRow('OpenMP threads per process', self.palace_threads)
        form.addRow('OpenBLAS threads per process', self.palace_blas)
        note = QLabel('OpenMP requires an OpenMP-enabled Palace build. For example, 32 MPI processes × 1 thread uses 32 cores. MPI count uses PALACE_NP; the run_palace wrapper must support it.')
        note.setWordWrap(True);form.addRow(note)
        layout.addWidget(self.palace_group)
        self.elmer_group = QGroupBox('Elmer execution')
        self.elmer_layout = QVBoxLayout(self.elmer_group)
        layout.addWidget(self.elmer_group)
        layout.addStretch()

    @staticmethod
    def _count(automatic):
        box = QSpinBox();box.setRange(0, 4096);box.setSpecialValueText(automatic)
        return box

    def update_solver(self):
        self.openems_group.setVisible(self.window.OpenEMSMode)
        self.palace_group.setVisible(self.window.PalaceMode)
        self.elmer_group.setVisible(self.window.ElmerMode)
        self.load_values()

    def load_values(self):
        v = self.window.saved_values
        self.openems_threads.setValue(int(v.get('numThreads') or 0))
        self.openems_engine.setCurrentIndex(1 if v.get('openems_engine') == 'gpu' else 0)
        for key, box in self._palace_boxes():
            box.setValue(int(v.get(key) or 0))

    def _palace_boxes(self):
        return [('palace_mpi_processes', self.palace_mpi),
                ('palace_omp_threads', self.palace_threads),
                ('palace_blas_threads', self.palace_blas)]

    def save_values(self):
        v = self.window.saved_values
        if self.window.OpenEMSMode:
            v['numThreads'] = self.openems_threads.value() or None
            v['openems_engine'] = self.openems_engine.currentData()
        if self.window.PalaceMode:
            for key, box in self._palace_boxes():
                if box.value() or key in v:
                    v[key] = box.value() or None
        return True
