"""Raw Cadence GDS -> stackup-driven cleanup -> reviewed EM-port preparation."""
from pathlib import Path
import json
import sys
import tempfile
from PySide6.QtCore import QProcess,QProcessEnvironment,Qt
from PySide6.QtWidgets import (QGroupBox,QWidget,QVBoxLayout,QHBoxLayout,QFormLayout,QLineEdit,
    QPushButton,QLabel,QCheckBox,QSpinBox,QPlainTextEdit,QFileDialog,QApplication)
try:
    from .raw_preparation import verified_report
    from .datatype_filters import parse_datatypes,format_datatypes
    from .path_config import browse_start
except ImportError:
    from raw_preparation import verified_report
    from datatype_filters import parse_datatypes,format_datatypes
    from path_config import browse_start


class RawInputSection(QGroupBox):
    def __init__(self,file_tab):
        super().__init__('Raw Input — Cadence GDS preprocessing',file_tab)
        self.file_tab=file_tab;self.window=file_tab.MainWindow;self.process=None;self.temporary=None;self._preview_windows=[]
        layout=QVBoxLayout(self)
        help=QLabel('Preparation workflow: Raw GDS → Cleaned GDS → EM-port GDS. Uses the XML stackup above. '
                    'Step 2 creates the EM-port file and selects it as the active simulation input below. Show previews a file; Use for simulation selects it.')
        help.setWordWrap(True);layout.addWidget(help)
        self.source=QLineEdit();self.source.setPlaceholderText('Original Cadence GDS export')
        self.mapfile=QLineEdit();self.mapfile.setPlaceholderText('Cadence stream map (used for drawing/pin purposes and port names)')
        self.cleaned=QLineEdit();self.cleaned.setPlaceholderText('Separate cleaned GDS output')
        self.prepared=QLineEdit();self.prepared.setPlaceholderText('Final _ems.gds, with named EM-port markers')
        self.preview_buttons={}
        for text,edit,callback,key in [('Raw GDS',self.source,self.browse_source,'raw'),('Stream map',self.mapfile,self.browse_map,None),('Cleaned GDS',self.cleaned,self.browse_cleaned,'cleaned'),('EM-port GDS',self.prepared,self.browse_prepared,'prepared')]:
            row=QHBoxLayout();label=QLabel(text);label.setMinimumWidth(100);row.addWidget(label);row.addWidget(edit,1)
            button=QPushButton('Browse…');button.clicked.connect(callback);row.addWidget(button);layout.addLayout(row)
            if key:
                show=QPushButton('Show');show.clicked.connect(lambda checked=False,k=key:self.preview(k))
                row.addWidget(show);self.preview_buttons[key]=show
                edit.textChanged.connect(self.update_file_buttons)
            if key=='prepared':
                self.use_button=QPushButton('Use for simulation');self.use_button.clicked.connect(self.use_prepared);row.addWidget(self.use_button)
        self.source.editingFinished.connect(self.suggest_output)
        self.cleaned.editingFinished.connect(self.suggest_prepared)
        row=QHBoxLayout();layout.addLayout(row)
        self.options_button=QPushButton('Simplification options…');self.options_button.setCheckable(True)
        row.addWidget(self.options_button)
        self.run_button=QPushButton('1. Simplify raw GDS');row.addWidget(self.run_button)
        self.stop_button=QPushButton('Stop');self.stop_button.setEnabled(False);row.addWidget(self.stop_button)
        self.ports_button=QPushButton('2. Create EM-port GDS…');row.addWidget(self.ports_button)
        self.options_widget=QWidget();form=QFormLayout(self.options_widget);self.options_widget.setVisible(False)
        self.cell=QLineEdit();self.cell.setPlaceholderText('Blank = largest design top cell (ignores KLayout context cell)');form.addRow('Raw design cell',self.cell)
        self.drawing=QLineEdit('0');form.addRow('Drawing datatypes (without a stream map)',self.drawing)
        self.drop=QLineEdit();self.drop.setPlaceholderText('Blank = keep; enter filler-purpose datatypes or inclusive ranges');form.addRow('Remove polygon datatypes',self.drop)
        self.excluded=QLineEdit();self.excluded.setPlaceholderText('Optional comma-separated layer numbers');form.addRow('Do not simplify these layers',self.excluded)
        self.floating=QCheckBox('Remove repeated isolated metal fill');self.floating.setChecked(True);form.addRow(self.floating)
        sizes=QHBoxLayout();self.minsize=QLineEdit('1');self.maxsize=QLineEdit('20');self.mincount=QSpinBox();self.mincount.setRange(2,1000000);self.mincount.setValue(20)
        for text,widget in [('Min size (µm)',self.minsize),('Max (blank = unlimited)',self.maxsize),('Min repeats',self.mincount)]:sizes.addWidget(QLabel(text));sizes.addWidget(widget)
        form.addRow(sizes)
        sizes=QHBoxLayout();self.cutouts=QCheckBox('Fill density cutouts through (µm²)');self.cutouts.setChecked(True);self.maxarea=QLineEdit('1')
        sizes.addWidget(self.cutouts);sizes.addWidget(self.maxarea);form.addRow(sizes)
        self.merge=QCheckBox('Merge touching drawing polygons per layer/datatype');self.merge.setChecked(True);form.addRow(self.merge)
        self.ground_holes=QCheckBox('Fill repeated ground-plane openings (20 or more of one size)');form.addRow(self.ground_holes)
        sizes=QHBoxLayout();sizes.addWidget(QLabel('Via merge distance (µm, 0 = off)'));self.via=QLineEdit('0');sizes.addWidget(self.via);form.addRow(sizes)
        note=QLabel('Floating-fill removal already merges touching metal. Via merging is off by default: preprocessing vias into solid polygons loses their original fill factor. '
                    'Mapped pin shapes and all labels are retained. No PDK layer or filler-purpose numbers are assumed.')
        note.setWordWrap(True);form.addRow(note);layout.addWidget(self.options_widget)
        self.status=QLabel('Choose a raw layout and XML stackup. Stream-map drawing purposes override the fallback datatype field.')
        self.status.setWordWrap(True);layout.addWidget(self.status)
        self.log=QPlainTextEdit();self.log.setReadOnly(True);self.log.setMaximumHeight(95);self.log.setVisible(False);layout.addWidget(self.log)
        self.options_button.toggled.connect(self.options_widget.setVisible)
        self.run_button.clicked.connect(self.run);self.stop_button.clicked.connect(self.stop);self.ports_button.clicked.connect(self.prepare_ports)
        QApplication.instance().aboutToQuit.connect(self.shutdown)
        self.update_file_buttons()

    def update_file_buttons(self,*args):
        for key,edit in [('raw',self.source),('cleaned',self.cleaned),('prepared',self.prepared)]:
            if key in self.preview_buttons:self.preview_buttons[key].setEnabled(Path(edit.text()).expanduser().is_file())
        if hasattr(self,'use_button'):self.use_button.setEnabled(Path(self.prepared.text()).expanduser().is_file())

    def suggest_prepared(self):
        if self.source.text() and self.cleaned.text() and (not self.prepared.text() or self.prepared.text()==getattr(self,'_suggested_prepared','')):
            self._suggested_prepared=str(Path(self.cleaned.text()).with_name(Path(self.source.text()).stem+'_ems.gds'))
            self.prepared.setText(self._suggested_prepared)

    def browse_source(self):
        path,_=QFileDialog.getOpenFileName(self,'Raw Cadence GDS',browse_start('gds',self.source.text()),'GDSII (*.gds *.GDS);;All files (*)')
        if path:self.source.setText(path);self.suggest_output()

    def suggest_output(self):
        source=Path(self.source.text()).expanduser()
        if source.is_file() and (not self.cleaned.text() or getattr(self,'_suggested_output','')==self.cleaned.text()):
            self._suggested_output=str(source.with_name(source.stem+'_cleaned.gds'));self.cleaned.setText(self._suggested_output)
        if source.is_file() and not self.mapfile.text():
            for name in ('stream.map','mapfile','gds.map'):
                if (source.parent/name).is_file():self.mapfile.setText(str(source.parent/name));break
        self.suggest_prepared()

    def browse_map(self):
        path,_=QFileDialog.getOpenFileName(self,'Cadence stream map',browse_start('stream_map',self.mapfile.text(),str(Path(self.source.text()).parent)),'All files (*)')
        if path:self.mapfile.setText(path)

    def browse_cleaned(self):
        path,_=QFileDialog.getSaveFileName(self,'New cleaned GDS output',self.cleaned.text(),'GDSII (*.gds)')
        if path:self.cleaned.setText(path);self.suggest_prepared()

    def browse_prepared(self):
        path,_=QFileDialog.getOpenFileName(self,'Existing port-prepared GDS',browse_start('gds',self.prepared.text()),'GDSII (*.gds *.GDS);;All files (*)')
        if path:self.prepared.setText(path)

    def use_prepared(self):
        try:
            try:
                from .prepare_ports_dialog import use_prepared_gds
            except ImportError:
                from prepare_ports_dialog import use_prepared_gds
            use_prepared_gds(self.window,self.prepared.text())
            self.status.setText('Active simulation input selected: '+self.prepared.text()+'. No preparation rerun is needed.')
        except (OSError,ValueError,KeyError) as error:self.status.setText('Cannot select EM-port GDS: '+str(error))

    def preview(self,stage):
        try:
            import gdstk
            from gds_simplify_for_em import open_gds_cell
            try:
                from .layout_preview import LayoutPreviewWindow
                from .pin_preparation import read_prepared_manifest
            except ImportError:
                from layout_preview import LayoutPreviewWindow
                from pin_preparation import read_prepared_manifest
            edit={'raw':self.source,'cleaned':self.cleaned,'prepared':self.prepared}[stage]
            path=Path(edit.text()).expanduser().resolve();xml=Path(self.file_tab.XML_file_edit.text()).expanduser()
            if not path.is_file() or not xml.is_file():raise ValueError('Choose an existing GDS and XML stackup first.')
            metadata=read_prepared_manifest(path) if stage=='prepared' else None
            info=gdstk.gds_info(path);cellname=metadata['cell'] if metadata else self.cell.text().strip()
            if cellname and cellname not in info['cell_names']:raise ValueError('Cell not found in selected GDS: '+cellname)
            if not cellname:
                library,cell=open_gds_cell(str(path),'');cellname=cell.name;del cell,library
            from gds2palace import stackup_reader as reader
            if getattr(self.window,'OpenEMSMode',False):from gds2openEMS import stackup_reader as reader
            stackup=reader.read_substrate(str(xml),variable_overrides=self.file_tab.get_variable_overrides())
            markers=[dict(kind='port',group='Ports',portnumber=p['portnumber'],source_layernum=p['source_layernum'],name=p['name'],direction='') for p in metadata['ports']] if metadata else []
            settings=dict(GdsFile=str(path),SubstrateFile=str(xml),cellname=cellname,
                purpose=sorted({d for l,d in info['layers_and_datatypes']}),preprocess_gds=False,merge_polygon_size=0.)
            view=LayoutPreviewWindow(self.window,gds_override_path=str(path),title_suffix={'raw':'Raw GDS','cleaned':'Cleaned GDS','prepared':'EM-port GDS'}[stage],
                preview_settings=settings,preview_markers=markers,preview_stackup=stackup,preview_layers={l for l,d in info['layers_and_datatypes']})
            view.setParent(self.window,Qt.Window);view.CLOSE_WITH_MAIN_WINDOW=True
            self._preview_windows.append(view);view.destroyed.connect(lambda: self._forget_preview(view))
            view.show();self.status.setText('Previewing '+path.name+'. Active simulation input is unchanged.')
        except (OSError,ValueError,KeyError,SystemExit) as error:self.status.setText('Cannot preview GDS: '+str(error))

    def _forget_preview(self,view):
        if view in self._preview_windows:self._preview_windows.remove(view)

    def state(self):
        return dict(source=self.source.text(),mapfile=self.mapfile.text(),output=self.cleaned.text(),prepared=self.prepared.text(),cell=self.cell.text(),
            drawing=self.drawing.text(),drop=self.drop.text(),excluded=self.excluded.text(),
            do_floating=self.floating.isChecked(),do_cutouts=self.cutouts.isChecked(),do_merge=self.merge.isChecked(),
            fill_ground_holes=self.ground_holes.isChecked(),fill_minsize=self.minsize.text(),fill_maxsize=self.maxsize.text(),
            fill_mincount=self.mincount.value(),max_hole_area=self.maxarea.text(),via_merge_size=self.via.text())

    def load_state(self,state):
        for key,widget,default in [('source',self.source,''),('mapfile',self.mapfile,''),('output',self.cleaned,''),('prepared',self.prepared,''),('cell',self.cell,''),
            ('drawing',self.drawing,'0'),('drop',self.drop,''),('excluded',self.excluded,''),('fill_minsize',self.minsize,'1'),
            ('fill_maxsize',self.maxsize,'20'),('max_hole_area',self.maxarea,'1'),('via_merge_size',self.via,'0')]:widget.setText(str(state.get(key,default)))
        for key,widget,default in [('do_floating',self.floating,True),('do_cutouts',self.cutouts,True),('do_merge',self.merge,True),('fill_ground_holes',self.ground_holes,False)]:widget.setChecked(state.get(key,default))
        self.mincount.setValue(state.get('fill_mincount',20))
        self.suggest_prepared();self.update_file_buttons()
        self.status.setText('Raw preparation settings loaded. Step 2 verifies the cleaned file and preparation report before continuing.')

    def options(self):
        for label,value in [('Raw GDS',self.source.text()),('XML stackup',self.file_tab.XML_file_edit.text())]:
            if not Path(value).expanduser().is_file():raise ValueError('Choose a valid '+label+' file first.')
        if self.mapfile.text() and not Path(self.mapfile.text()).expanduser().is_file():raise ValueError('Stream map file not found.')
        if not self.cleaned.text():raise ValueError('Enter a new cleaned GDS output path.')
        def number(edit,label,optional=False):
            if optional and not edit.text().strip():return None
            try:return float(edit.text())
            except ValueError:raise ValueError('Invalid '+label)
        state=self.state()
        for key in ('source','output','mapfile'):
            if state[key]:state[key]=str(Path(state[key]).expanduser().resolve())
        state.pop('drawing');state.pop('drop');state.pop('excluded');state.pop('prepared')
        state.update(stackup=str(Path(self.file_tab.XML_file_edit.text()).expanduser().resolve()),
            stackup_reader='openems' if getattr(self.window,'OpenEMSMode',False) else 'palace',
            variable_overrides=self.file_tab.get_variable_overrides(),drawing_datatypes=parse_datatypes(self.drawing.text()),
            drop_datatypes=parse_datatypes(self.drop.text()),excluded_layers=parse_datatypes(self.excluded.text()),
            fill_minsize=number(self.minsize,'minimum fill size'),fill_maxsize=number(self.maxsize,'maximum fill size',True),
            max_hole_area=number(self.maxarea,'cutout area',True),via_merge_size=number(self.via,'via merge distance'))
        try:
            from .simplify_gds import _port_layer_range
        except ImportError:
            from simplify_gds import _port_layer_range
        state['port_layer_range']=list(_port_layer_range(self.window.APP_NAME))
        return state

    def run(self):
        if self.process and self.process.state()!=QProcess.NotRunning:return
        self.log.setVisible(True);self.log.clear()
        try:
            options=self.options()
            for path in (Path(options['output']),Path(options['output']).with_suffix('.prep.json'),Path(options['output']).with_suffix('.prep.log')):
                if path.exists():raise ValueError('Output already exists; choose a new cleaned GDS name: '+str(path))
            self.temporary=tempfile.TemporaryDirectory(prefix='.setupem_raw_job_',dir=Path(options['output']).parent)
            job=Path(self.temporary.name)/'job.json';job.write_text(json.dumps(options))
            self.process=QProcess(self);self.process.setProcessChannelMode(QProcess.MergedChannels)
            env=QProcessEnvironment.systemEnvironment();env.insert('PYTHONUNBUFFERED','1');self.process.setProcessEnvironment(env)
            self.process.readyReadStandardOutput.connect(self.read_output);self.process.finished.connect(self.finished);self.process.errorOccurred.connect(self.process_error)
            self._running_options=options
            self.run_button.setEnabled(False);self.ports_button.setEnabled(False);self.stop_button.setEnabled(True)
            self.status.setText('Simplifying raw layout in the background…')
            self.process.start(sys.executable,['-u',str(Path(__file__).with_name('raw_preparation_worker.py')),str(job)])
        except (ValueError,OSError) as error:self.status.setText('Cannot simplify: '+str(error))

    def read_output(self):
        text=bytes(self.process.readAllStandardOutput()).decode('utf-8',errors='replace')
        if text:self.log.appendPlainText(text.rstrip())

    def finished(self,code,status):
        self.read_output();self.run_button.setEnabled(True);self.ports_button.setEnabled(True);self.stop_button.setEnabled(False)
        if self.temporary:self.temporary.cleanup();self.temporary=None
        if code==0 and status==QProcess.NormalExit:
            try:
                report=verified_report(self._running_options)
                with Path(report['output']['path']).with_suffix('.prep.log').open('x') as stream:stream.write(self.log.toPlainText()+'\n')
                self.status.setText('Cleaned GDS ready. Continue with step 2 to review pins and create the _ems.gds.')
            except (OSError,ValueError) as error:self.status.setText('Cannot verify prepared layout: '+str(error))
        else:self.status.setText('Simplification failed or stopped. Simulation inputs were not changed; see the log.')
        self.suggest_prepared();self.update_file_buttons()

    def process_error(self,error):
        self.log.appendPlainText('Process error: '+self.process.errorString())
        if error==QProcess.FailedToStart:self.finished(-1,QProcess.CrashExit)

    def stop(self):
        if self.process and self.process.state()!=QProcess.NotRunning:self.process.kill()

    def shutdown(self):
        self.stop()
        if self.process:self.process.waitForFinished(1000)
        if self.temporary:self.temporary.cleanup();self.temporary=None

    def prepare_ports(self):
        try:
            options=self.options();report=verified_report(options)
            try:
                from .prepare_ports_dialog import open_dialog
            except ImportError:
                from prepare_ports_dialog import open_dialog
            self.suggest_prepared();output=Path(self.prepared.text())
            data=open_dialog(self.window,source=options['output'],cellname=report['cell'],mapfile=options['mapfile'],
                             output=str(output),preparation_options=options)
            if data:
                self.prepared.setText(self.file_tab.gds_file_edit.text());self.update_file_buttons()
                purposes=sorted({d for l,d in report['simulation_drawing_lpps']}|{0})
                self.file_tab.purpose_edit.setText(format_datatypes(purposes));self.window.saved_values['purpose']=purposes
                self.status.setText('Prepared _ems.gds is now selected in the simulation inputs, with drawing datatypes + marker datatype 0. Set port directions and return conductors on the Ports tab.')
        except (OSError,ValueError,KeyError) as error:self.status.setText('Cannot prepare ports: '+str(error))
