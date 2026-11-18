"""openEMS-specific controls for the shared setupEM front end."""
from PySide6.QtWidgets import (QComboBox, QDoubleSpinBox, QSpinBox, QGroupBox,
                               QFormLayout, QLabel, QMessageBox)
try:
    from .openems_writer import BOUNDARIES
except ImportError:
    from openems_writer import BOUNDARIES


def layout_visible(layout, visible):
    for i in range(layout.count()):
        item = layout.itemAt(i)
        if item.widget():
            item.widget().setVisible(visible)
        elif item.layout():
            layout_visible(item.layout(), visible)


def install(window):
    selector = QComboBox()
    for label, key in [('Palace FEM', 'palace'), ('Elmer FEM', 'elmer'), ('openEMS FDTD', 'openems')]:
        selector.addItem(label, key)
    window.solver_selector = selector
    row = QFormLayout()
    row.addRow('Target solver', selector)
    window.file_tab.main_layout.insertLayout(0, row)
    note = QLabel('Choose a stackup compatible with the target solver. Switching solver does not convert the stackup.')
    note.setWordWrap(True)
    window.file_tab.main_layout.insertWidget(1, note)
    selector.currentIndexChanged.connect(lambda _: select(window, selector.currentData()))
    mesh = window.mesh_tab
    mesh.openems_group = QGroupBox('openEMS FDTD settings')
    form = QFormLayout(mesh.openems_group)
    mesh.openems_energy = QDoubleSpinBox()
    mesh.openems_energy.setRange(-160, -1);mesh.openems_energy.setValue(-50)
    form.addRow('Residual energy limit (dB)', mesh.openems_energy)
    mesh.openems_threads = window.settings_tab.openems_threads
    mesh.openems_numfreq = QSpinBox();mesh.openems_numfreq.setRange(2, 1000001);mesh.openems_numfreq.setValue(401)
    form.addRow('Output frequency points', mesh.openems_numfreq)
    mesh.openems_engine = window.settings_tab.openems_engine
    mesh.Elmer_layout.removeItem(mesh.threads_layout)
    window.settings_tab.elmer_layout.addLayout(mesh.threads_layout)
    mesh.labelthreads.setText('MPI processes')
    for index, count in enumerate((1, 2, 4, 8, 16)):
        mesh.threads_box.setItemText(index, f'{count} MPI process' + ('' if count == 1 else 'es'))
    mesh.openems_bc = []
    for label in ('xmin', 'xmax', 'ymin', 'ymax', 'zmin', 'zmax'):
        combo = QComboBox();combo.addItems(BOUNDARIES);mesh.openems_bc.append(combo)
        form.addRow(label + ' boundary', combo)
    note = QLabel('Boundaries are independent of FEM settings. PEC is reflective; choose MUR or PML_8 for absorbing boundaries. Surface/skin FEM presets and port-wall extensions are not applied.')
    note.setWordWrap(True);form.addRow(note)
    mesh.main_layout.insertWidget(1, mesh.openems_group)
    mesh.openems_group.hide()


def select(window, solver):
    if getattr(window, 'script_model', None) is not None:
        current = 'openems' if window.OpenEMSMode else ('elmer' if window.ElmerMode else 'palace')
        if solver != current:
            QMessageBox.warning(window, 'Target solver', 'Import the script as a new model before changing its target solver.')
            window.solver_selector.blockSignals(True)
            window.solver_selector.setCurrentIndex(window.solver_selector.findData(current))
            window.solver_selector.blockSignals(False)
            return
    window.settings_tab.save_values()
    if window.OpenEMSMode:
        save(window)
    if solver == 'openems':
        window.setOpenEMSMode()
    elif solver == 'elmer':
        window.setElmerMode()
    else:
        window.setPalaceMode()
    filename = window.saved_values.get('SubstrateFile', '')
    if filename:
        import os
        if os.path.isfile(filename):
            window.read_XML()


def update(window):
    if not hasattr(window, 'solver_selector'):
        return
    openems = window.OpenEMSMode
    solver = 'openems' if openems else ('elmer' if window.ElmerMode else 'palace')
    window.solver_selector.blockSignals(True)
    window.solver_selector.setCurrentIndex(window.solver_selector.findData(solver))
    window.solver_selector.blockSignals(False)
    m, f = window.mesh_tab, window.frequencies_tab
    m.openems_group.setVisible(openems)
    for layout in (m.meshorder_layout, m.cells_maxsize_layout, m.conductor_model_layout):
        layout_visible(layout, not openems)
    # Conductor presets were already hidden for Elmer.
    if window.ElmerMode:
        layout_visible(m.conductor_model_layout, False)
    m.refined_override_btn.setEnabled(not openems)
    layout_visible(m.boundary_layout, not openems)
    window.ports_tab.portwall_group.setVisible(not openems)
    m.AMR_group.setVisible(window.PalaceMode)
    m.Elmer_group.setVisible(window.ElmerMode)
    layout_visible(m.amr_conformal_layout, window.PalaceMode)
    f.sweep_group.setTitle('Broadband excitation' if openems else 'Adaptive frequency sweep')
    layout_visible(f.step_layout, not openems)
    f.discrete_group.setVisible(not openems)
    f.dump_group.setVisible(not openems)  # spatial field-dump boxes need a separate UI
    if openems:
        window.create_model_tab.viewer_btn.setVisible(False)
        window.create_model_tab.model_fit_btn.setVisible(False)
    window.create_model_tab.preview_model_btn.setText('Preview geometry / mesh in AppCSXCAD' if openems else '⚙️ Preview model geometry in gmsh')
    window.create_model_tab.create_model_btn.setText('Prepare geometry / FDTD mesh (no simulation)' if openems else '⚙️ Create mesh and simulation settings file')
    window.settings_tab.update_solver()
    load(window)


def load(window):
    if not hasattr(window.mesh_tab, 'openems_energy'):
        return
    m, v = window.mesh_tab, window.saved_values
    m.openems_energy.setValue(float(v.get('energy_limit', -50)))
    m.openems_threads.setValue(int(v.get('numThreads') or 0))
    m.openems_numfreq.setValue(int(v.get('numfreq', 401)))
    m.openems_engine.setCurrentIndex(1 if v.get('openems_engine') == 'gpu' else 0)
    for combo, value in zip(m.openems_bc, v.get('openems_boundaries', ['PEC'] * 6)):
        combo.setCurrentText(value)


def save(window):
    m, v = window.mesh_tab, window.saved_values
    v.update(energy_limit=m.openems_energy.value(), numThreads=m.openems_threads.value() or None,
             numfreq=m.openems_numfreq.value(), openems_engine=m.openems_engine.currentData(),
             openems_boundaries=[c.currentText() for c in m.openems_bc])
