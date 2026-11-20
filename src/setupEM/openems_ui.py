"""openEMS-specific controls for the shared setupEM front end."""
from PySide6.QtWidgets import (QComboBox, QDoubleSpinBox, QSpinBox, QGroupBox,
                               QFormLayout, QLabel, QMessageBox, QWidget, QVBoxLayout, QTableWidgetItem, QPushButton, QFileDialog)
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
    install_geometry(window)
    saved_preview=QPushButton('Preview saved openEMS solver geometry…')
    saved_preview.setToolTip('Open an existing solver XML unchanged. Does not regenerate feeds, mesh or calibration.')
    saved_preview.clicked.connect(lambda: preview_saved_geometry(window))
    grid = window.create_model_tab.buttons_grid
    grid.addWidget(saved_preview, grid.rowCount(), 0, 1, 2)
    window.openems_saved_preview=saved_preview



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
    window.openems_saved_preview.setVisible(openems)
    for layout in (m.meshorder_layout, m.cells_maxsize_layout, m.conductor_model_layout):
        layout_visible(layout, not openems)
    # Conductor presets were already hidden for Elmer.
    if window.ElmerMode:
        layout_visible(m.conductor_model_layout, False)
    m.refined_override_btn.setEnabled(not openems)
    layout_visible(m.boundary_layout, not openems)
    window.ports_tab.portwall_group.setVisible(not openems)
    window.openems_boxwall_group.setVisible(openems)
    window.openems_aircut_group.setVisible(openems)
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
    refresh_port_overview(window)


def load(window):
    if not hasattr(window.mesh_tab, 'openems_energy'):
        return
    m, v = window.mesh_tab, window.saved_values
    m.openems_energy.setValue(float(v.get('energy_limit', -50)))
    m.openems_threads.setValue(int(v.get('numThreads') or 0))
    m.openems_numfreq.setValue(int(v.get('numfreq', 401)))
    m.openems_engine.setCurrentIndex(1 if v.get('openems_engine') == 'gpu' else 0)
    load_geometry(window)
    for combo, value in zip(m.openems_bc, v.get('openems_boundaries', ['PEC'] * 6)):
        combo.setCurrentText(value)


def save(window):
    save_geometry(window)
    m, v = window.mesh_tab, window.saved_values
    v.update(energy_limit=m.openems_energy.value(), numThreads=m.openems_threads.value() or None,
             numfreq=m.openems_numfreq.value(), openems_engine=m.openems_engine.currentData(),
             openems_boundaries=[c.currentText() for c in m.openems_bc])



def install_geometry(w):
    """Optional generated geometry, isolated from Palace's port-wall controls."""
    g=QGroupBox('openEMS: calibrated box-wall feeds (experimental)')
    g.setCheckable(True);g.setChecked(False);w.openems_boxwall_group=g
    body=QWidget();form=QFormLayout(body);outer=QVBoxLayout(g);outer.addWidget(body)
    body.hide();g.toggled.connect(body.setVisible)
    w.openems_wall_side=QComboBox();w.openems_wall_side.addItems(['xmax','xmin','ymax','ymin'])
    w.openems_signal=QComboBox();w.openems_signal.setEditable(True)
    w.openems_return_kind=QComboBox()
    w.openems_return_kind.addItem('Individual return strips (same width as signal)','metal')
    w.openems_return_kind.addItem('Existing conductive backside layer','background')
    w.openems_return=QComboBox();w.openems_return.setEditable(True)
    def spin(value,zero=False):
        x=QDoubleSpinBox();x.setDecimals(4);x.setRange(0 if zero else .001,1e6);x.setValue(value);return x
    w.openems_feed_length=spin(100)
    w.openems_feed_gap=spin(1)
    w.openems_feed_width=spin(0,True);w.openems_feed_width.setSpecialValueText('Use pin width')
    w.openems_reference_setback=spin(0,True)
    w.openems_reference_setback.setToolTip('Move the calibrated reference plane outward from the terminal toward the wall. '
        'The transition between the terminal and this plane remains part of the measured device. '
        'Use when an existing ground patch extends into the generated feed; do not de-embed across a nonuniform section.')
    for label,widget in [('Outward wall side',w.openems_wall_side),('Signal metal',w.openems_signal),
        ('Ground return',w.openems_return_kind),('Return metal / background layer',w.openems_return),
        ('Uniform feed length (um)',w.openems_feed_length),('Wall gap (um)',w.openems_feed_gap),
        ('Feed width (um)',w.openems_feed_width),
        ('Reference plane setback toward wall (um)',w.openems_reference_setback)]:form.addRow(label,widget)
    note=QLabel('Generates feeds from aligned rectangular terminal markers. GDS does not determine access direction. '
        'The 3D preview shows the generated device; Prepare also writes calibration standards. Metal returns and backside returns '
        'are different physical fixtures; calibration does not remove their coupling into the device. '
        'A deep backside return may limit the valid calibration band. Trial dimensions require review.')
    note.setWordWrap(True);form.addRow(note)
    w.ports_tab.main_layout.insertWidget(1,g)
    g.toggled.connect(lambda _: refresh_layer_choices(w))
    w.openems_return_kind.currentIndexChanged.connect(lambda _: refresh_layer_choices(w))
    g.hide()
    for widget in (w.openems_wall_side,w.openems_signal,w.openems_return,w.openems_return_kind):
        widget.currentTextChanged.connect(lambda _: refresh_port_overview(w))
    for widget in (w.openems_feed_length,w.openems_feed_gap,w.openems_feed_width):
        widget.valueChanged.connect(lambda _: refresh_port_overview(w))
    w.openems_boxwall_group.toggled.connect(lambda _: refresh_port_overview(w))
    g=QGroupBox('RDL passivation: air-valley approximation (experimental)')
    g.setCheckable(True);g.setChecked(False);w.openems_aircut_group=g
    body=QWidget();form=QFormLayout(body);outer=QVBoxLayout(g);outer.addWidget(body)
    body.hide();g.toggled.connect(body.setVisible)
    w.openems_rdl_metal=QComboBox();w.openems_rdl_metal.setEditable(True)
    w.openems_valley_height=spin(1,True);w.openems_coating_width=spin(.5,True)
    form.addRow('RDL source metal',w.openems_rdl_metal)
    form.addRow('Valley coating height above RDL bottom (um)',w.openems_valley_height)
    form.addRow('Lateral coating width (um)',w.openems_coating_width)
    note=QLabel('Cuts air outside the grown RDL footprint, from the specified valley height to the existing '
        'planar dielectric top. Lower layers are unchanged. With no RDL polygons the stack stays planar. '
        'These are sensitivity parameters, not process data. Inspect the 3D preview and minimum dz. '
        'This recipe cannot yet be combined with calibrated box-wall feeds.')
    note.setWordWrap(True);form.addRow(note)
    w.mesh_tab.main_layout.insertWidget(2,g)
    g.toggled.connect(lambda _: refresh_layer_choices(w))
    g.hide()


def refresh_layer_choices(w):
    def fill(combo,names):
        current=combo.currentText();combo.blockSignals(True);combo.clear();combo.addItem('');combo.addItems(names)
        if current:combo.setCurrentText(current)
        combo.blockSignals(False)
    metals=getattr(w,'metals_list',None)
    names=[m.name for m in getattr(metals,'metals',[]) if m.is_metal or m.is_sheet]
    fill(w.openems_signal,names);fill(w.openems_rdl_metal,names)
    if w.openems_return_kind.currentData()=='metal':returns=names
    else:
        materials=getattr(w,'materials_list',None)
        returns=[]
        for d in getattr(getattr(w,'dielectrics_list',None),'dielectrics',[]):
            m=materials.get_by_name(d.material) if materials is not None else None
            if m is not None and m.sigma>=1e4:returns.append(d.name)
    fill(w.openems_return,returns)


def load_geometry(w):
    if not hasattr(w,'openems_boxwall_group'):return
    refresh_layer_choices(w)
    c=w.saved_values.get('openems_boxwall') or {}
    w.openems_boxwall_group.setChecked(bool(c))
    w.openems_wall_side.setCurrentText(c.get('side','xmax'))
    w.openems_signal.setCurrentText(c.get('signal_layer',''))
    w.openems_return_kind.setCurrentIndex(1 if c.get('return_kind')=='background' else 0)
    w.openems_return.setCurrentText(c.get('return_layer',''))
    w.openems_feed_length.setValue(c.get('feed_length',100));w.openems_feed_gap.setValue(c.get('gap',1))
    w.openems_feed_width.setValue(c.get('width',0))
    w.openems_reference_setback.setValue(c.get('reference_plane_setback',0))
    c=w.saved_values.get('openems_aircut') or {}
    w.openems_aircut_group.setChecked(bool(c));w.openems_rdl_metal.setCurrentText(c.get('metal',''))
    w.openems_valley_height.setValue(c.get('valley_height',1));w.openems_coating_width.setValue(c.get('coating_width',.5))


def save_geometry(w):
    if not hasattr(w,'openems_boxwall_group'):return
    v=w.saved_values
    if w.openems_boxwall_group.isChecked():
        v['openems_boxwall']=dict(side=w.openems_wall_side.currentText(),signal_layer=w.openems_signal.currentText(),
            return_kind=w.openems_return_kind.currentData(),return_layer=w.openems_return.currentText(),
            feed_length=w.openems_feed_length.value(),gap=w.openems_feed_gap.value(),width=w.openems_feed_width.value())
        if w.openems_reference_setback.value():
            v['openems_boxwall']['reference_plane_setback']=w.openems_reference_setback.value()
    else:v.pop('openems_boxwall',None)
    if w.openems_aircut_group.isChecked():
        v['openems_aircut']=dict(metal=w.openems_rdl_metal.currentText(),
            valley_height=w.openems_valley_height.value(),coating_width=w.openems_coating_width.value())
    else:v.pop('openems_aircut',None)


def refresh_port_overview(w):
    """Show generated launches without overwriting the saved terminal markers."""
    if not hasattr(w, 'openems_boxwall_group'): return
    table=w.ports_tab.portslist
    active=w.OpenEMSMode and w.openems_boxwall_group.isChecked()
    if table.columnCount()<14:
        table.setColumnCount(14)
        for i,label in enumerate(('Wall / access','Signal metal','Return layer','Feed / shift (um)','Width / wall gap (um)'),9):
            table.setHorizontalHeaderItem(i,QTableWidgetItem(label))
            table.horizontalHeader().setSectionResizeMode(i,table.horizontalHeader().ResizeMode.ResizeToContents)
    table.horizontalHeaderItem(2).setText('Terminal marker layer' if active else 'Source layer')
    for col in (3,4,5,6,8):table.setColumnHidden(col,active)
    for col in range(9,14):table.setColumnHidden(col,not active)
    w.ports_tab.bottom_group.setTitle('Port overview — generated box-wall launches' if active else 'Port overview')
    w.ports_tab.top_group.setTitle('Terminal marker definitions (converted to wall launches below)' if active else 'Port settings')
    side=w.openems_wall_side.currentText()
    code={'xmax':'SWX → −X','xmin':'SW-X → +X','ymax':'SWY → −Y','ymin':'SW-Y → +Y'}[side]
    width=w.openems_feed_width.value()
    values=(side+' / '+code,w.openems_signal.currentText(),w.openems_return.currentText(),
            f'{w.openems_feed_length.value():g}',
            f'{width:g}' if width else 'pin width')
    for row in range(table.rowCount()):
        populated=table.item(row,2) is not None and bool(table.item(row,2).text())
        for col,value in enumerate(values,9):
            item=QTableWidgetItem(value + (f' / {w.openems_feed_gap.value():g}' if col==13 else '') if active and populated else '')
            item.setToolTip('Generated in-plane launch toward device. L/2L coupled-line calibration; feed length is the reference-plane shift. Original marker definitions are retained for editing.')
            table.setItem(row,col,item)


def saved_geometry_candidates(values):
    from pathlib import Path
    name=values.get('model_basename','')
    if not name:return []
    bases=[Path(values.get('sim_path') or '.'),Path(values.get('GdsFile') or '.').parent]
    candidates=[]
    for base in bases:
        for root in (base/'output'/(name+'_data'),base/(name+'_data'),base):
            for path in sorted(root.glob('sub-*/'+name+'.xml')):
                resolved=path.resolve()
                if resolved not in candidates:candidates.append(resolved)
    return candidates


def preview_saved_geometry(window):
    """Read the actual saved solver XML, without rerunning the model script."""
    from pathlib import Path
    import xml.etree.ElementTree as ET
    from PySide6.QtCore import QProcess
    candidates=saved_geometry_candidates(window.saved_values)
    if candidates:
        # Excitations share the physical geometry; use the first by default.
        filename=str(candidates[0])
    else:
        filename,_=QFileDialog.getOpenFileName(window,'Saved openEMS solver geometry',
            str(Path(window.saved_values.get('GdsFile') or '.').parent),'openEMS geometry (*.xml)')
    if not filename:return
    try:
        if ET.parse(filename).getroot().tag not in ('ContinuousStructure','openEMS'):
            raise ValueError('Select an openEMS solver XML, not a stackup XML')
        from CSXCAD import AppCSXCAD_BIN
        result=QProcess.startDetached(str(AppCSXCAD_BIN),[filename])
        if not (result[0] if isinstance(result,tuple) else result):
            raise RuntimeError('Could not start AppCSXCAD')
        window.create_model_tab.log_area.appendPlainText('Previewing saved solver geometry (unchanged): '+filename)
    except Exception as error:
        QMessageBox.warning(window,'Saved geometry preview',str(error))
