"""Review original PDK pins before creating solver-neutral EM marker layers."""
import hashlib
from pathlib import Path
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QDialog,QVBoxLayout,QHBoxLayout,QFormLayout,QLineEdit,
    QPushButton,QPlainTextEdit,QTableWidget,QTableWidgetItem,QLabel,QSpinBox,
    QFileDialog,QMessageBox,QHeaderView)
if __package__ in (None, ''):
    import pin_preparation as pins
    from path_config import browse_start,project_directory,output_filename
    from generated_output_dialog import choose_output
else:
    from . import pin_preparation as pins
    from .path_config import browse_start,project_directory,output_filename
    from .generated_output_dialog import choose_output


class PreparePortsDialog(QDialog):
    def __init__(self,window,source=None,cellname=None,mapfile=None,output=None,preparation_options=None):
        super().__init__(window)
        self.window=window;self.result_data=None;self.scanned=None
        self.preparation_options=preparation_options
        self.setWindowTitle('Prepare named EM ports from GDS pins');self.resize(1050,670)
        layout=QVBoxLayout(self);form=QFormLayout();layout.addLayout(form)
        self.source=QLineEdit(source if source is not None else window.file_tab.gds_file_edit.text());form.addRow('Original / cleaned GDS',self.source)
        self.cell=QLineEdit(cellname if cellname is not None else window.saved_values.get('cellname',''));form.addRow('Cell (blank = unique top cell)',self.cell)
        row=QHBoxLayout();self.mapfile=QLineEdit(mapfile or '');row.addWidget(self.mapfile)
        browse=QPushButton('Load mapfile…');row.addWidget(browse);browse.clicked.connect(self.load_map)
        form.addRow('Layer map',row)
        self.mapping=QPlainTextEdit();self.mapping.setMaximumHeight(115)
        self.mapping.setPlaceholderText('Metal purpose GDS-layer datatype, e.g.\nM6 drawing 36 0\nM6 pin 136 0\nM6 label 36 0')
        form.addRow('Pin / drawing / label mappings',self.mapping)
        hint=QLabel('Load the technology stream map, or enter mappings above. Only pin-purpose polygons become candidates. '
                    'Names from labels inside a pin are preselected; nearest-label suggestions require review. '
                    'Names are editable. Each selected shape becomes one port; original geometry and hierarchy are retained.')
        hint.setWordWrap(True);layout.addWidget(hint)
        scan=QPushButton('Find pins / refresh inventory');scan.clicked.connect(self.scan);layout.addWidget(scan)
        self.table=QTableWidget(0,7);self.table.setHorizontalHeaderLabels(['Use','Pin ID','Name / net','Metal','Original layer/datatype','Label match','Bounds'])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setStretchLastSection(True);layout.addWidget(self.table,1)
        form=QFormLayout();layout.addLayout(form)
        self.start=QSpinBox();self.start.setRange(0,65535);self.start.setValue(240)
        form.addRow('First candidate marker layer (occupied layers skipped)',self.start)
        row=QHBoxLayout();self.output=QLineEdit(output or output_filename('gds',Path(self.source.text()).stem+'_ems.gds',window,self.source.text(),str(Path(self.source.text()).parent)))
        row.addWidget(self.output);browse=QPushButton('Save as…');row.addWidget(browse);browse.clicked.connect(self.choose_output)
        form.addRow('Prepared GDS',row)
        hint=QLabel('Port numbers follow the selected table rows. Writes datatype 0 markers and net-name labels, plus a .ports.json manifest. '
                    'Selected pins replace the current port table. Existing outputs require confirmation unless replacement is enabled in Preferences. Port direction, return conductor and impedance are configured on the Ports tab.')
        hint.setWordWrap(True);layout.addWidget(hint)
        row=QHBoxLayout();row.addStretch();cancel=QPushButton('Cancel');cancel.clicked.connect(self.reject);row.addWidget(cancel)
        self.create=QPushButton('Create _ems.gds and use it');self.create.clicked.connect(self.generate);row.addWidget(self.create);layout.addLayout(row)
        if mapfile:self.read_map()
        for name in (() if mapfile else ('mapfile','stream.map','gds.map')):
            candidate=Path(self.source.text()).parent/name
            if candidate.is_file():
                self.mapfile.setText(str(candidate));self.read_map();break

    def load_map(self):
        name,_=QFileDialog.getOpenFileName(self,'Technology stream map',browse_start('stream_map',self.mapfile.text(),str(Path(self.source.text()).parent),project=project_directory(self.window)),'All files (*)')
        if name:self.mapfile.setText(name);self.read_map()

    def read_map(self):
        try:
            rows=pins.read_map(Path(self.mapfile.text()))
            self.mapping.setPlainText('\n'.join(f'{n} {p} {l} {d}' for n,p,l,d in rows))
        except Exception as error:QMessageBox.warning(self,'Cannot read mapfile',str(error))

    def rows(self):
        rows=[]
        for line in self.mapping.toPlainText().splitlines():
            fields=line.split('#',1)[0].split()
            if not fields:continue
            if len(fields)!=4:raise ValueError('Each mapping needs: metal purpose layer datatype')
            row=(fields[0],fields[1],int(fields[2]),int(fields[3]))
            if not all(0<=v<=65535 for v in row[2:]):raise ValueError('Layer and datatype must be in 0..65535')
            rows.append(row)
        if not any(r[1]=='pin' for r in rows):raise ValueError('Add at least one pin-purpose mapping')
        return rows

    def fingerprint(self):
        return (self.source.text(),self.cell.text(),self.mapping.toPlainText(),
                hashlib.sha256(Path(self.source.text()).read_bytes()).hexdigest())

    def scan(self):
        try:
            rows=self.rows();before=self.fingerprint()
            lib,cell,inventory=pins.inspect(self.source.text(),rows,self.cell.text())
            if before!=self.fingerprint():raise ValueError('Input changed during inventory; scan again')
            self.table.setRowCount(len(inventory))
            for r,p in enumerate(inventory):
                use=QTableWidgetItem();use.setFlags(Qt.ItemIsEnabled|Qt.ItemIsUserCheckable)
                use.setCheckState(Qt.Checked if p['match']=='inside' else Qt.Unchecked);self.table.setItem(r,0,use)
                values=(str(p['id']),', '.join(p['names']),p['metal'],str(p['source']),
                        p['match']+(f" ({p['label_distance']:g} units)" if p['label_distance'] is not None else ''),' – '.join('('+', '.join(f'{v:g}' for v in corner)+')' for corner in p['bbox']))
                for c,value in enumerate(values,1):
                    item=QTableWidgetItem(value)
                    if c!=2:item.setFlags(item.flags() & ~Qt.ItemIsEditable)
                    self.table.setItem(r,c,item)
            self.scanned=before
            if not inventory:QMessageBox.information(self,'No pins','No polygons found on the mapped pin layers in this cell.')
        except Exception as error:QMessageBox.warning(self,'Cannot inspect pins',str(error))

    def choose_output(self):
        path,_=QFileDialog.getSaveFileName(self,'Prepared GDS',self.output.text(),'GDSII (*.gds)')
        if path:self.output.setText(path)

    def generate(self):
        try:
            if self.scanned is None or self.scanned!=self.fingerprint():raise ValueError('Find pins again after changing inputs or mappings')
            selection=[(int(self.table.item(r,1).text()),self.table.item(r,2).text())
                       for r in range(self.table.rowCount()) if self.table.item(r,0).checkState()==Qt.Checked]
            stackup=self.window.file_tab.XML_file_edit.text()
            if not Path(stackup).is_file():stackup=''
            preparation=None
            if self.preparation_options:
                if __package__ in (None,''):
                    from raw_preparation import verified_report
                else:
                    from .raw_preparation import verified_report
                preparation=verified_report(self.preparation_options)
                if Path(self.source.text()).resolve()!=Path(preparation['output']['path']):
                    raise ValueError('Port source differs from the verified cleaned layout.')
            raw=self.window.file_tab.raw_input.source.text()
            output,overwrite=choose_output(self,self.window.APP_NAME,self.output.text(),('.ports.json',),
                (self.source.text(),stackup,self.mapfile.text(),raw))
            if output is None:return
            self.output.setText(output)
            Path(output).expanduser().parent.mkdir(parents=True,exist_ok=True)
            self.result_data=pins.write(self.source.text(),self.output.text(),self.rows(),selection,
                cellname=self.cell.text(),start_layer=self.start.value(),stackup=stackup,mapfile=self.mapfile.text(),preparation=preparation,overwrite=overwrite)
            self.accept()
        except Exception as error:QMessageBox.warning(self,'Cannot prepare ports',str(error))


def open_dialog(window,**options):
    if not options.get('source') and not window.file_tab.save_values():return
    dialog=PreparePortsDialog(window,**options)
    if dialog.exec()!=QDialog.Accepted:return
    data=dialog.result_data
    use_prepared_gds(window,dialog.output.text(),data)
    return data


def use_prepared_gds(window,path,data=None):
    """Select an existing or just-generated file as the one active solver input."""
    import gdspy
    path=Path(path).expanduser().resolve()
    if not path.is_file():raise ValueError('Prepared GDS file not found: '+str(path))
    if data is None:data=pins.read_prepared_manifest(path)
    if data and data.get('output_sha256')!=hashlib.sha256(path.read_bytes()).hexdigest():
        raise ValueError('Prepared port manifest does not match the selected GDS.')
    lib=gdspy.GdsLibrary();lib.read_gds(str(path),units='import')
    if data and data['cell'] not in lib.cells:raise ValueError('Prepared manifest cell is not in this GDS.')
    if data is None:
        window.file_tab.set_gds_file(str(path));window.file_tab.cellname_box.setCurrentIndex(0)
        window.saved_values['cellname']=''
        window.statusBar().showMessage('Selected existing GDS for simulation. Existing port settings are retained.',15000)
        return None
    # Include the new datatype 0 markers even with a restricted purpose filter.
    purposes=list(window.saved_values.get('purpose',[]))
    preparation=(data or {}).get('raw_preparation',{})
    if preparation.get('simulation_drawing_lpps'):
        purposes=sorted({d for l,d in preparation['simulation_drawing_lpps']}|{0})
    if 0 not in purposes:
        purposes=[0]+purposes
    ports=[]
    if data and hasattr(window,'ports_tab'):
        for p in data['ports']:
            target=''
            metals=getattr(window,'metals_list',None)
            if metals is not None:
                candidates=[m.name for m in metals.metals if m.is_metal and
                            (m.name==p['metal'] or int(m.layernum) in [l for l,d in p['drawing']])]
                if len(set(candidates))==1:target=candidates[0]
            ports.append(dict(portnumber=p['portnumber'],source_layernum=p['source_layernum'],
                              target_layername=target,direction=''))
    window.file_tab.set_gds_file(str(path))
    window.file_tab.cellname_box.setCurrentText(data['cell'] if data else '(default)')
    window.saved_values['cellname']=data['cell'] if data else ''
    window.saved_values['purpose']=purposes
    window.file_tab.purpose_edit.setText(','.join(map(str,purposes)))
    if data and hasattr(window,'ports_tab'):
        window.ports_tab.update_port_from_import(ports)
        window.ports_tab.refresh_missing_layer_annotations()
    window.statusBar().showMessage('Prepared named ports. Configure port direction and return on the Ports tab.',15000)
    return data
