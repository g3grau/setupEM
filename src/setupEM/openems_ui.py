"""openEMS-specific controls for the shared setupEM front end."""
from PySide6.QtCore import Qt,QSignalBlocker
from PySide6.QtWidgets import (QComboBox, QDoubleSpinBox, QSpinBox, QGroupBox, QGridLayout, QSplitter,
                               QFormLayout, QLabel, QMessageBox, QWidget, QVBoxLayout, QLayout, QTableWidgetItem, QPushButton, QFileDialog, QPlainTextEdit)
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
    window.openems_calibration_group.setVisible(openems and bool(port_feed_configs(window)))
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
    window.settings_tab.load_values()
    m.openems_numfreq.setValue(int(v.get('numfreq', 401)))
    m.openems_engine.setCurrentIndex(1 if v.get('openems_engine') == 'gpu' else 0)
    load_geometry(window)
    for combo, value in zip(m.openems_bc, v.get('openems_boundaries', ['PEC'] * 6)):
        combo.setCurrentText(value)


def save(window):
    window.settings_tab.save_values()
    save_geometry(window)
    m, v = window.mesh_tab, window.saved_values
    v.update(energy_limit=m.openems_energy.value(), numThreads=m.openems_threads.value() or None,
             numfreq=m.openems_numfreq.value(), openems_engine=m.openems_engine.currentData(),
             openems_boundaries=[c.currentText() for c in m.openems_bc])



def install_geometry(w):
    """Optional generated geometry, isolated from Palace's port-wall controls."""
    g=QGroupBox('Selected port: calibrated boxwall feed (experimental)')
    g.setCheckable(True);g.setChecked(False);w.openems_boxwall_group=g
    body=QWidget();body_layout=QVBoxLayout(body);outer=QVBoxLayout(g);outer.addWidget(body)
    settings=QWidget();form=QVBoxLayout(settings);fields=QGridLayout();form.addLayout(fields)
    form.setSizeConstraint(QLayout.SetMinimumSize)
    fields.setColumnStretch(1,1);fields.setColumnStretch(3,1)
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
    for index,(label,widget) in enumerate([('Outward wall side',w.openems_wall_side),('Signal metal',w.openems_signal),
        ('Ground return',w.openems_return_kind),('Return metal / background layer',w.openems_return),
        ('Uniform feed length (um)',w.openems_feed_length),('Wall gap (um)',w.openems_feed_gap),
        ('Feed width (um)',w.openems_feed_width),
        ('Reference plane setback toward wall (um)',w.openems_reference_setback)]):
        row,column=divmod(index,2);fields.addWidget(QLabel(label),row,column*2);fields.addWidget(widget,row,column*2+1)
    note=QLabel('Generates feeds from aligned rectangular terminal markers. GDS does not determine access direction. '
        'The 3D preview shows the generated device; Prepare also writes calibration standards. Metal returns and backside returns '
        'are different physical fixtures; calibration does not remove their coupling into the device. '
        'Select a port row to edit its own feed. Ports sharing a wall need matching wall/reference planes. '
        'A deep backside return may limit the valid calibration band. Trial dimensions require review.')
    note.setWordWrap(True);form.addWidget(note)
    w.openems_check_calibration=QPushButton('Check calibration limits / geometry (no simulation)')
    w.openems_check_calibration.clicked.connect(lambda: check_calibration(w, save_tabs=True))
    form.addWidget(w.openems_check_calibration)
    w.openems_calibration_report=QPlainTextEdit()
    w.openems_calibration_report.setReadOnly(True)
    w.openems_calibration_report.setMinimumHeight(100)
    w.openems_calibration_report.setPlaceholderText('Check the current inputs to see wavelength, phase and feed requirements, with guidance.')
    splitter=QSplitter(Qt.Vertical);w.openems_boxwall_splitter=splitter
    splitter.setObjectName('openems_boxwall_messages');splitter.setChildrenCollapsible(False);splitter.setHandleWidth(9)
    splitter.setStyleSheet('QSplitter::handle:vertical { margin: 3px 8px; background: #c8c8c8; }')
    splitter.addWidget(settings);splitter.addWidget(w.openems_calibration_report)
    splitter.setStretchFactor(0,0);splitter.setStretchFactor(1,1);splitter.setSizes([230,300])
    splitter.handle(1).setToolTip('Drag to resize the calibration messages')
    body_layout.setContentsMargins(0,0,0,0);body_layout.addWidget(splitter)
    w.openems_calibration_group=QGroupBox('openEMS calibration preflight')
    preflight_layout=QVBoxLayout(w.openems_calibration_group)
    w.openems_run_calibration_report=QPlainTextEdit()
    w.openems_run_calibration_report.setReadOnly(True)
    w.openems_run_calibration_report.setMaximumHeight(180)
    w.openems_run_calibration_report.setPlaceholderText('Preview, Prepare or Start checks calibration before proceeding. You can also check from the Ports tab.')
    preflight_layout.addWidget(w.openems_run_calibration_report)
    w.openems_calibration_group.setMaximumHeight(230)
    w.create_model_tab.actions_layout.insertWidget(1,w.openems_calibration_group)
    w.openems_calibration_group.hide()
    g.toggled.connect(lambda checked: feed_edited(w))
    w.ports_tab.lists_splitter.insertWidget(0,g)
    w.ports_tab.lists_splitter.setStretchFactor(0,2)
    w.ports_tab.lists_splitter.setStretchFactor(1,3)
    w.ports_tab.lists_splitter.setStretchFactor(2,1)
    w.ports_tab.lists_splitter.setSizes([420,350,160])
    w.ports_tab.lists_splitter.handle(1).setToolTip('Drag to share the height between calibration messages and the port overview')
    w.ports_tab.lists_splitter.handle(2).setToolTip('Drag to share the height between the port overview and port walls')
    g.toggled.connect(lambda _: refresh_layer_choices(w))
    w.openems_return_kind.currentIndexChanged.connect(lambda _: refresh_layer_choices(w))
    g.hide()
    w._openems_port_feeds={}
    w._openems_legacy_feed=None
    w._loading_port_feed=False
    for widget in (w.openems_wall_side,w.openems_signal,w.openems_return,w.openems_return_kind):
        widget.currentTextChanged.connect(lambda _: feed_edited(w))
    for widget in (w.openems_feed_length,w.openems_feed_gap,w.openems_feed_width,w.openems_reference_setback):
        widget.valueChanged.connect(lambda _: feed_edited(w))
    for widget in (w.openems_wall_side,w.openems_signal,w.openems_return,w.openems_return_kind):
        widget.currentTextChanged.connect(lambda _: invalidate_calibration(w))
    for widget in (w.openems_feed_length,w.openems_feed_gap,w.openems_feed_width,w.openems_reference_setback):
        widget.valueChanged.connect(lambda _: invalidate_calibration(w))
    for widget in (w.frequencies_tab.start_edit,w.frequencies_tab.stop_edit,w.file_tab.gds_file_edit,
                   w.file_tab.XML_file_edit,w.file_tab.purpose_edit):
        widget.textChanged.connect(lambda _: invalidate_calibration(w))
    w.file_tab.cellname_box.currentTextChanged.connect(lambda _: invalidate_calibration(w))
    w.ports_tab.portslist.itemChanged.connect(lambda _: invalidate_calibration(w))
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


def _populated_ports(w):
    table=w.ports_tab.portslist
    return [row+1 for row in range(table.rowCount()) if table.item(row,2) is not None and table.item(row,2).text()]


def port_feed_configs(w):
    legacy=getattr(w,'_openems_legacy_feed',None)
    if legacy:return {str(number):dict(legacy) for number in _populated_ports(w)}
    return dict(getattr(w,'_openems_port_feeds',{}))


def feed_controls(w):
    result=dict(side=w.openems_wall_side.currentText(),signal_layer=w.openems_signal.currentText(),
        return_kind=w.openems_return_kind.currentData(),return_layer=w.openems_return.currentText(),
        feed_length=w.openems_feed_length.value(),gap=w.openems_feed_gap.value(),width=w.openems_feed_width.value())
    if w.openems_reference_setback.value():result['reference_plane_setback']=w.openems_reference_setback.value()
    return result


def feed_edited(w):
    if getattr(w,'_loading_port_feed',True):return
    row=w.ports_tab.portslist.currentRow()
    if row<0:return
    entries=port_feed_configs(w)
    w._openems_legacy_feed=None
    if w.openems_boxwall_group.isChecked():entries[str(row+1)]=feed_controls(w)
    else:entries.pop(str(row+1),None)
    w._openems_port_feeds=entries
    w.ports_tab._update_direction_controls()
    w.ports_tab._update_direction_lock(row)
    refresh_port_overview(w)
    invalidate_calibration(w)


def select_port_feed(w,row):
    if not hasattr(w,'openems_boxwall_group') or row<0:return
    c=port_feed_configs(w).get(str(row+1),{})
    w._loading_port_feed=True
    try:
        w.openems_boxwall_group.setTitle(f'Port {row+1}: calibrated boxwall feed (experimental)')
        w.openems_boxwall_group.setChecked(bool(c))
        w.openems_wall_side.setCurrentText(c.get('side','xmax'))
        w.openems_signal.setCurrentText(c.get('signal_layer',w.ports_tab.target_box.currentText()))
        w.openems_return_kind.setCurrentIndex(1 if c.get('return_kind')=='background' else 0)
        refresh_layer_choices(w)
        w.openems_return.setCurrentText(c.get('return_layer',w.ports_tab.from_box.currentText()))
        w.openems_feed_length.setValue(c.get('feed_length',100));w.openems_feed_gap.setValue(c.get('gap',1))
        w.openems_feed_width.setValue(c.get('width',0))
        w.openems_reference_setback.setValue(c.get('reference_plane_setback',0))
    finally:w._loading_port_feed=False
    w.ports_tab._update_direction_controls()
    w.ports_tab._update_direction_lock(row)
    refresh_port_overview(w)


def load_geometry(w):
    if not hasattr(w,'openems_boxwall_group'):return
    c=w.saved_values.get('openems_boxwall') or {}
    w._openems_port_feeds={str(k):dict(v) for k,v in c.get('ports',{}).items()}
    w._openems_legacy_feed=dict(c) if c and 'ports' not in c else None
    select_port_feed(w,max(w.ports_tab.portslist.currentRow(),0))
    c=w.saved_values.get('openems_aircut') or {}
    w.openems_aircut_group.setChecked(bool(c));w.openems_rdl_metal.setCurrentText(c.get('metal',''))
    w.openems_valley_height.setValue(c.get('valley_height',1));w.openems_coating_width.setValue(c.get('coating_width',.5))


def save_geometry(w):
    if not hasattr(w,'openems_boxwall_group'):return
    v=w.saved_values
    populated=set(map(str,_populated_ports(w)))
    entries={k:c for k,c in port_feed_configs(w).items() if k in populated}
    if entries:v['openems_boxwall']={'ports':entries}
    else:v.pop('openems_boxwall',None)
    if w.openems_aircut_group.isChecked():
        v['openems_aircut']=dict(metal=w.openems_rdl_metal.currentText(),
            valley_height=w.openems_valley_height.value(),coating_width=w.openems_coating_width.value())
    else:v.pop('openems_aircut',None)


def refresh_port_overview(w):
    """Each row describes its own feed; ordinary and wall ports can coexist."""
    if not hasattr(w,'openems_boxwall_group'):return
    table=w.ports_tab.portslist
    blocker=QSignalBlocker(table)  # Updating derived columns is not an input change.
    entries=port_feed_configs(w) if w.OpenEMSMode else {}
    active=bool(entries)
    if table.columnCount()<15:
        table.setColumnCount(15)
        for i,label in enumerate(('Wall / access','Signal metal','Return layer','Feed / shift (um)','Width / wall gap (um)','Port type'),9):
            table.setHorizontalHeaderItem(i,QTableWidgetItem(label))
            table.horizontalHeader().setSectionResizeMode(i,table.horizontalHeader().ResizeMode.ResizeToContents)
        table.horizontalHeader().moveSection(table.horizontalHeader().visualIndex(14),0)
    populated=_populated_ports(w)
    all_wall=bool(populated) and all(str(n) in entries for n in populated)
    table.horizontalHeaderItem(2).setText('Terminal marker layer' if active else 'Source layer')
    for col in (3,4,5,6,8):table.setColumnHidden(col,all_wall)
    for col in range(9,14):table.setColumnHidden(col,not active)
    table.setColumnHidden(14,not w.OpenEMSMode)
    w.ports_tab.bottom_group.setTitle('Port overview — per-port feeds' if active else 'Port overview')
    w.ports_tab.top_group.setTitle('Port settings')
    for row in range(table.rowCount()):
        c=entries.get(str(row+1)) if row+1 in populated else None
        values=['']*5
        if c:
            side=c['side'];code={'xmax':'SWX → −X','xmin':'SW-X → +X','ymax':'SWY → −Y','ymin':'SW-Y → +Y'}[side]
            length=c['feed_length'];setback=c.get('reference_plane_setback',0)
            values=[side+' / '+code,c['signal_layer'],c['return_layer'],f'{length:g} / {length-setback:g}',
                    (f"{c['width']:g}" if c['width'] else 'pin width')+f" / {c['gap']:g}"]
        for col,value in enumerate(values,9):
            item=QTableWidgetItem(value)
            item.setToolTip('Selected port fixture. Feed length / calibrated shift are measured from its terminal and wall respectively.')
            table.setItem(row,col,item)
        direction=table.item(row,6).text().upper() if table.item(row,6) else ''
        kind='Boxwall feed' if c else ('Via port' if 'Z' in direction else 'In-plane port')
        table.setItem(row,14,QTableWidgetItem(kind if row+1 in populated else ''))
    w.openems_calibration_group.setVisible(w.OpenEMSMode and active)


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


def invalidate_calibration(window):
    if getattr(window,'_loading_port_feed',False):return
    for name in ('openems_calibration_report', 'openems_run_calibration_report'):
        panel=getattr(window,name,None)
        if panel is not None:
            panel.setPlainText('Settings changed. Check calibration again; Preview, Prepare and Start also check automatically.')


def check_calibration(window, save_tabs=False, for_run=False):
    """Show the current backend plan and block invalid simulation launches."""
    if save_tabs and not window.save_all_tabs():
        return False
    if not window.saved_values.get('openems_boxwall'):
        return True
    try:
        try:
            from .openems_preflight import check_configuration, report_text
        except ImportError:
            from openems_preflight import check_configuration, report_text
        report=check_configuration(window.saved_values, window.native_config_extra_struct()['ports'])
        text=report_text(report)
    except (ImportError, AttributeError) as error:
        report={'ok':False,'geometry_ok':False}
        text=('Calibration preflight unavailable. Install/update gds2openEMS in the Python environment running setupEM.\n'
              +str(error))
    window.openems_calibration_report.setPlainText(text)
    if hasattr(window, 'openems_run_calibration_report'):
        window.openems_run_calibration_report.setPlainText(text)
    window.openems_calibration_report.setToolTip('Last checked current settings. Preview, Prepare and Start check again automatically.')
    if not report['ok'] and (for_run or not report['geometry_ok']):
        QMessageBox.warning(window, 'openEMS calibration: changes required', text)
    # Preview/Prepare can still inspect valid geometry with a failed band check.
    # Start is blocked; a geometry failure blocks every action.
    return report['ok'] or (not for_run and report['geometry_ok'])
