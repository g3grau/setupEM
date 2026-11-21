"""Read-only network analysis tab; numerical extraction has no GUI dependencies."""
from pathlib import Path
import math

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QWidget,QVBoxLayout,QHBoxLayout,QGridLayout,QLabel,QComboBox,
    QPushButton,QFileDialog,QDoubleSpinBox,QSpinBox,QPlainTextEdit,QTableWidget,QTableWidgetItem,
    QHeaderView,QDialog,QDialogButtonBox,QTabWidget)

try:
    from .network_parameters import ExtractionSpec,load_touchstone,extract_parameters,export_parameters
    from .postprocessing_tools import DCExtensionTab,LumpedModelsTab
    from .comparison_tab import ComparisonTab,DEFAULT_PLOT_OPTIONS
    from .plot_window import PlotWindow
    from .path_config import browse_start
except ImportError:
    from network_parameters import ExtractionSpec,load_touchstone,extract_parameters,export_parameters
    from postprocessing_tools import DCExtensionTab,LumpedModelsTab
    from comparison_tab import ComparisonTab,DEFAULT_PLOT_OPTIONS
    from plot_window import PlotWindow
    from path_config import browse_start


INDUCTOR_PLOTS=[('L_H','Differential L (nH)',1e9),('R_ohm','Differential R (ohm)',1),('Q','Differential Q',1)]
LINE_PLOTS=[('Zc_real_ohm','Zc real (ohm)',1),('Zc_imag_ohm','Zc imaginary (ohm)',1),
 ('alpha_dB_per_mm','Attenuation (dB/mm)',1),('effective_permittivity','Effective permittivity',1),
 ('L_H_per_m','L per length (nH/mm)',1e6),('C_F_per_m','C per length (pF/mm)',1e9),
 ('R_ohm_per_m','R per length (ohm/mm)',1e-3),('G_S_per_m','G per length (mS/mm)',1)]
DEFAULT_OPTIONS=dict(file='',mode='inductor',port_a=1,port_b=2,unused_ports='matched',
                     length=0.0,length_unit='um',phase_branch=0,minimum_GHz=.1,maximum_GHz=0.0)


class PostprocessingTab(QWidget):
    independent_analysis_tab = True

    def __init__(self,owner):
        super().__init__(owner)
        self.owner=owner
        if not hasattr(owner,'postprocessing_settings'):owner.postprocessing_settings={}
        self.network=None;self.source=None;self.result=None;self._loading=False
        self.figure=None;self.canvas=None;self._marker_lines=[]
        layout=QVBoxLayout(self)
        row=QHBoxLayout();layout.addLayout(row)
        row.addWidget(QLabel('Touchstone result'))
        self.files=QComboBox();self.files.setEditable(True);self.files.setMinimumContentsLength(30)
        self.files.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        row.addWidget(self.files,1)
        self.browse_button=QPushButton('Browse…');row.addWidget(self.browse_button)
        self.find_button=QPushButton('Find current results');row.addWidget(self.find_button)
        self.load_button=QPushButton('Load');row.addWidget(self.load_button)
        self.source_label=QLabel('Load an existing .sNp file. No simulation or de-embedding is performed here.')
        self.source_label.setWordWrap(True);layout.addWidget(self.source_label)
        self.subtabs=QTabWidget();layout.addWidget(self.subtabs,1)
        parameters=QWidget();self.subtabs.addTab(parameters,'Parameters')
        layout=QVBoxLayout(parameters);layout.setContentsMargins(0,4,0,0)
        controls=QGridLayout();layout.addLayout(controls)
        self.mode=QComboBox();self.mode.addItem('Differential inductor','inductor');self.mode.addItem('Uniform transmission line','line')
        self.port_a=QComboBox();self.port_b=QComboBox()
        self.termination=QComboBox();self.termination.addItem('Unused ports: matched','matched');self.termination.addItem('Unused ports: open circuit','open')
        self.termination.setToolTip('Matched: other ports terminate in their own file reference impedances. Open: zero current at other terminals. No port is silently grounded.')
        controls.addWidget(self.mode,0,0,1,2);controls.addWidget(QLabel('Port A / input'),0,2);controls.addWidget(self.port_a,0,3)
        controls.addWidget(QLabel('Port B / output'),0,4);controls.addWidget(self.port_b,0,5);controls.addWidget(self.termination,0,6,1,2)
        self.line_length=QDoubleSpinBox();self.line_length.setRange(0,1e9);self.line_length.setDecimals(6);self.line_length.setSpecialValueText('Enter length')
        self.length_unit=QComboBox()
        for text,value in [('um',1e-6),('mm',1e-3),('m',1)]:self.length_unit.addItem(text,value)
        self.phase_branch=QSpinBox();self.phase_branch.setRange(-10000,10000)
        self.phase_branch.setToolTip('Full 2*pi phase turns added at the first positive source frequency, before selecting a display band. Default 0 assumes the low-frequency principal branch.')
        self.length_label=QLabel('Uniform line length');self.branch_label=QLabel('Phase branch offset')
        controls.addWidget(self.length_label,1,0);controls.addWidget(self.line_length,1,1)
        controls.addWidget(self.length_unit,1,2);controls.addWidget(self.branch_label,1,3);controls.addWidget(self.phase_branch,1,4)
        self.minimum=QDoubleSpinBox();self.maximum=QDoubleSpinBox();self.marker=QDoubleSpinBox()
        for spin in (self.minimum,self.maximum,self.marker):spin.setRange(0,1e6);spin.setDecimals(6)
        self.minimum.setValue(.1);self.maximum.setSpecialValueText('File end');self.marker.setValue(3)
        controls.addWidget(QLabel('Minimum (GHz)'),2,0);controls.addWidget(self.minimum,2,1)
        controls.addWidget(QLabel('Maximum (GHz)'),2,2);controls.addWidget(self.maximum,2,3)
        controls.addWidget(QLabel('Readout (GHz)'),2,4);controls.addWidget(self.marker,2,5)
        self.analyze_button=QPushButton('Analyze selected pair');controls.addWidget(self.analyze_button,2,6,1,2)
        self.assumptions=QLabel();self.assumptions.setWordWrap(True);layout.addWidget(self.assumptions)
        self.status=QLabel('No result loaded.');self.status.setWordWrap(True);layout.addWidget(self.status)
        self.plot_window=PlotWindow(self,'setupEM — Extracted parameters',self.marker)
        self.plot_layout=self.plot_window.plot_layout
        self.empty=QLabel('Load a result to plot extracted parameters.');self.empty.setAlignment(Qt.AlignCenter);self.plot_layout.addWidget(self.empty)
        details=QWidget();details_layout=QVBoxLayout(details);details_layout.setContentsMargins(4,0,0,0)
        self.summary=QPlainTextEdit();self.summary.setReadOnly(True);self.summary.setMaximumHeight(190);details_layout.addWidget(self.summary)
        self.sample_label=QLabel('Nearest native sample');self.sample_label.setWordWrap(True);details_layout.addWidget(self.sample_label)
        self.table=QTableWidget(0,2);self.table.setHorizontalHeaderLabels(['Parameter','Value'])
        self.table.horizontalHeader().setSectionResizeMode(0,QHeaderView.Stretch);self.table.verticalHeader().hide()
        self.table.setEditTriggers(QTableWidget.NoEditTriggers);details_layout.addWidget(self.table,1)
        self.warnings=QPlainTextEdit();self.warnings.setReadOnly(True);self.warnings.setMaximumHeight(150);details_layout.addWidget(self.warnings)
        layout.addWidget(details,1)
        row=QHBoxLayout();layout.addLayout(row)
        self.export_button=QPushButton('Export CSV + provenance JSON…');self.export_button.setEnabled(False)
        self.metadata_button=QPushButton('View input file metadata…');self.metadata_button.setEnabled(False)
        self.show_plot_button=QPushButton('Show plots…');self.show_plot_button.setEnabled(False)
        self.show_plot_button.clicked.connect(self.plot_window.reveal);row.addWidget(self.show_plot_button)
        row.addWidget(self.export_button);row.addWidget(self.metadata_button);row.addStretch()
        row.addWidget(QLabel('Native samples; no smoothing or model fitting.'))
        self.browse_button.clicked.connect(self.browse);self.load_button.clicked.connect(self.load_file)
        self.find_button.clicked.connect(self.find_current);self.analyze_button.clicked.connect(self.analyze)
        self.export_button.clicked.connect(self.export);self.metadata_button.clicked.connect(self.show_metadata)
        self.mode.currentIndexChanged.connect(self._mode_changed)
        for combo in (self.port_a,self.port_b,self.termination,self.length_unit):combo.currentIndexChanged.connect(self.invalidate)
        for spin in (self.line_length,self.phase_branch,self.minimum,self.maximum):spin.valueChanged.connect(self.invalidate)
        self.files.editTextChanged.connect(self.invalidate)
        self.marker.valueChanged.connect(self.update_marker)
        self.dc_tab=DCExtensionTab(self);self.subtabs.addTab(self.dc_tab,'DC extension')
        self.lumped_tab=LumpedModelsTab(self);self.subtabs.addTab(self.lumped_tab,'Lumped models')
        self.plot_tab=ComparisonTab(self);self.subtabs.addTab(self.plot_tab,'Plot')
        self._mode_changed()

    def _mode_changed(self,*args):
        line=self.mode.currentData()=='line'
        for widget in (self.line_length,self.length_unit,self.phase_branch,self.length_label,self.branch_label):widget.setVisible(line)
        self.assumptions.setText('Uniform, reciprocal line assumed; enter physical length. Fixtures must already be de-embedded. Phase is unwrapped from the full source band, assuming its initial branch.'
            if line else 'Differential drive: I_A=+I, I_B=-I; Zdiff=ZAA−ZAB−ZBA+ZBB. L=Im(Zdiff)/(2πf), R=Re(Zdiff), Q=Im(Zdiff)/R. Negative L/Q remains visible above resonance.')
        self.invalidate()

    def invalidate(self,*args):
        if self._loading:return
        self.result=None;self.export_button.setEnabled(False)
        self.plot_window.set_readout('Settings changed. Analyze again to refresh these plots and readouts.')
        if hasattr(self,'dc_tab'):self.dc_tab.invalidate()
        self.status.setText('Selection changed. Load / Analyze to refresh; displayed plots, if any, are from the previous analysis.')
        self.summary.clear();self.table.setRowCount(0);self.warnings.clear()
        if self.figure is not None:
            self.figure.suptitle('Previous analysis — settings changed')
            self.canvas.draw_idle()

    def browse(self):
        path,_=QFileDialog.getOpenFileName(self,'Load Touchstone network',browse_start('touchstone',self.files.currentText()),'Touchstone (*.s*p *.S*P);;All files (*)')
        if path:self.files.setEditText(path);self.load_file()

    def find_current(self):
        import re
        v=self.owner.saved_values;tab=self.owner.create_model_tab
        active=tab.active_run()
        name=(active or {}).get('model_basename') or tab.modelname_edit.text() or v.get('model_basename','')
        root=Path(tab.targetdir_edit.text() or v.get('sim_path') or '.')
        if not name:
            self.status.setText('Set a model name/output directory first, or Browse a Touchstone file.');return
        roots=[root/'output'/(name+'_data'),root/(name+'_data')]
        if active:roots.insert(0,Path(active['sim_path']))
        for solver in ('palace_model','elmer_model'):
            roots.append(root/solver/(name+'_data'))
        found=set()
        for directory in roots:
            if not directory.is_dir():continue
            try:
                paths=list(directory.iterdir())
            except OSError:
                continue
            for p in paths:
                if p.is_file() and re.search(r'\.s\d+p$',p.name,re.I):found.add(str(p.resolve()))
        selected=self.files.currentText()
        self._loading=True
        self.files.clear()
        # Calibrated files first, but require an explicit Load; never silently
        # substitute an uncalibrated network when calibration failed.
        for path in sorted(found,key=lambda p:('_calibrated' not in Path(p).stem,p)):
            self.files.addItem(path)
        if selected:self.files.setEditText(selected)
        self._loading=False
        self.invalidate()
        self.status.setText(f'Found {len(found)} current-run result(s). Choose a file and Load; raw and calibrated remain distinct.')

    def load_file(self):
        self.invalidate()
        try:
            self.network,self.source=load_touchstone(self.files.currentText().strip())
            if self.network.nports<2:raise ValueError('Choose a network with at least two ports.')
            self._loading=True
            names=getattr(self.network,'port_names',None)
            for combo in (self.port_a,self.port_b):
                combo.clear()
                for i in range(self.network.nports):
                    label=f'{i+1}: {names[i]}' if names and names[i] else f'Port {i+1}'
                    combo.addItem(label,i+1)
            config=self.owner.postprocessing_settings
            for combo,key,default in [(self.port_a,'port_a',1),(self.port_b,'port_b',2)]:
                index=combo.findData(config.get(key,default));combo.setCurrentIndex(index if index>=0 else default-1)
            self._loading=False
            self.source_label.setText(f"{self.source['path']} | {self.network.nports} ports | SHA256 {self.source['sha256'][:16]}…")
            self.metadata_button.setEnabled(True)
            self.analyze()
        except (ValueError,OSError,UnicodeError,IndexError) as error:
            self._loading=False;self.network=None;self.source=None;self.result=None
            self.source_label.setText('No network loaded.')
            self.export_button.setEnabled(False);self.metadata_button.setEnabled(False)
            self.status.setText('Cannot load result: '+str(error))

    def specification(self):
        return ExtractionSpec(mode=self.mode.currentData(),port_a=self.port_a.currentData() or 1,
            port_b=self.port_b.currentData() or 2,unused_ports=self.termination.currentData(),
            line_length_m=self.line_length.value()*self.length_unit.currentData(),phase_branch=self.phase_branch.value(),
            minimum_hz=self.minimum.value()*1e9,maximum_hz=self.maximum.value()*1e9)

    def ensure_source(self):
        if self.source is None or Path(self.files.currentText()).expanduser().resolve()!=Path(self.source['path']):
            self.load_file()
        if self.network is None:raise ValueError('Load a valid Touchstone network first.')

    def analyze(self):
        if self.network is None:
            if self.files.currentText().strip():self.load_file()
            return
        if Path(self.files.currentText()).expanduser().resolve()!=Path(self.source['path']):
            self.load_file();return
        try:
            self.result=extract_parameters(self.network,self.specification(),self.source)
            self._draw()
            s=self.result.summary
            lines=[f"{s['samples']} native samples",f"Band: {s['first_frequency_Hz']/1e9:g}–{s['last_frequency_Hz']/1e9:g} GHz",
                   f"Ports {s['selected_ports'][0]} / {s['selected_ports'][1]}; others {s['unused_ports']}"]
            if s['mode']=='inductor':
                if s['peak_Q'] is not None:lines.append(f"Peak Q (selected band): {s['peak_Q']:.6g} at {s['peak_Q_frequency_Hz']/1e9:g} GHz")
                if s['reactance_zero_Hz'] is not None:lines.append(f"Reactance zero: {s['reactance_zero_Hz']/1e9:.6g} GHz (interpolated)")
            else:
                lines += [f"Length: {s['line_length_m']:.6g} m",f"Max uniform-line residual: {s['max_uniform_line_residual']:.3g}"]
            self.summary.setPlainText('\n'.join(lines))
            self.warnings.setPlainText('\n\n'.join(self.result.warnings) or 'No extraction warnings. This is not an accuracy or convergence validation.')
            self.status.setText('Analysis complete. Source data and calibration are unchanged.')
            self.export_button.setEnabled(True);self.update_marker()
            self.plot_window.reveal()
        except (ValueError,ArithmeticError) as error:
            self.result=None;self.export_button.setEnabled(False);self.status.setText('Cannot extract parameters: '+str(error))

    def _draw(self):
        if self.figure is None:
            from matplotlib.figure import Figure
            from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg,NavigationToolbar2QT
            self.figure=Figure(figsize=(10,7),layout='constrained');self.canvas=FigureCanvasQTAgg(self.figure)
            self.plot_layout.removeWidget(self.empty);self.empty.hide()
            self.plot_layout.addWidget(NavigationToolbar2QT(self.canvas,self));self.plot_layout.addWidget(self.canvas,1)
            self.show_plot_button.setEnabled(True)
            self.canvas.mpl_connect('button_press_event',self._plot_clicked)
        self.figure.clear();self._marker_lines=[]
        line=self.result.summary['mode']=='line';plots=LINE_PLOTS if line else INDUCTOR_PLOTS
        axes=self.figure.subplots(4,2,squeeze=False).ravel() if line else self.figure.subplots(3,1,squeeze=False).ravel()
        f=self.result.frequency_hz/1e9
        for axis,(key,label,scale) in zip(axes,plots):
            axis.plot(f,self.result.columns[key]*scale,lw=1.4)
            axis.set_ylabel(label,fontsize=9);axis.set_xlabel('Frequency (GHz)',fontsize=9)
            axis.grid(alpha=.3);axis.tick_params(labelsize=8)
            axis.axhline(0,color='grey',lw=.5)
            self._marker_lines.append(axis.axvline(self.marker.value(),color='grey',ls=':',lw=.8))
        spec=self.specification()
        self.figure.suptitle(f"{Path(self.source['path']).name} — ports {spec.port_a}/{spec.port_b}, unused {spec.unused_ports}",fontsize=10)
        self.canvas.draw_idle()

    def _plot_clicked(self,event):
        if event.inaxes and event.xdata is not None and event.xdata>=0:self.marker.setValue(event.xdata)

    def update_marker(self,*args):
        if self.result is None:return
        import numpy as np
        i=int(np.argmin(abs(self.result.frequency_hz-self.marker.value()*1e9)))
        frequency=self.result.frequency_hz[i]
        self.sample_label.setText(f'Nearest native sample: {frequency/1e9:.6g} GHz (no interpolation)')
        items=INDUCTOR_PLOTS if self.result.summary['mode']=='inductor' else LINE_PLOTS+[
            ('beta_rad_per_m','Phase beta (rad/mm)',1e-3),('uniform_line_residual','Uniform-line residual',1)]
        self.table.setRowCount(len(items))
        for row,(key,label,scale) in enumerate(items):
            value=self.result.columns[key][i]*scale
            self.table.setItem(row,0,QTableWidgetItem(label))
            self.table.setItem(row,1,QTableWidgetItem(f'{value:.8g}' if math.isfinite(value) else 'undefined'))
        self.plot_window.set_readout(self.sample_label.text()+'\n'+' | '.join(
            self.table.item(row,0).text()+': '+self.table.item(row,1).text() for row in range(self.table.rowCount())))
        for marker in self._marker_lines:marker.set_xdata([frequency/1e9]*2)
        if self.canvas:self.canvas.draw_idle()

    def export(self):
        if self.result is None:return
        default=str(Path(self.source['path']).with_name(Path(self.source['path']).stem+'_'+self.mode.currentData()+'_parameters.csv'))
        path,_=QFileDialog.getSaveFileName(self,'Export extracted parameters',default,'CSV (*.csv)')
        if not path:return
        try:
            csv_path,json_path=export_parameters(self.result,path)
            self.status.setText(f'Exported {csv_path} and {json_path}; source Touchstone unchanged.')
        except (OSError,ValueError) as error:self.status.setText('Cannot export: '+str(error))

    def show_metadata(self):
        if not self.source:return
        import json
        dialog=QDialog(self);dialog.setWindowTitle('Loaded Touchstone source and comments');dialog.resize(850,600)
        layout=QVBoxLayout(dialog);text=QPlainTextEdit();text.setReadOnly(True)
        text.setPlainText(json.dumps({k:v for k,v in self.source.items() if k!='comments'},indent=2)+'\n\n'+self.source['comments'])
        layout.addWidget(text);buttons=QDialogButtonBox(QDialogButtonBox.Close);buttons.rejected.connect(dialog.reject);layout.addWidget(buttons)
        dialog.exec()

    def save_values(self):
        broadband=getattr(self.owner,'broadband_tab',None)
        if broadband is not None and not broadband.save_values():return False
        options=dict(file=self.files.currentText(),mode=self.mode.currentData(),
            port_a=self.port_a.currentData() or 1,port_b=self.port_b.currentData() or 2,
            unused_ports=self.termination.currentData(),length=self.line_length.value(),length_unit=self.length_unit.currentText(),
            phase_branch=self.phase_branch.value(),minimum_GHz=self.minimum.value(),maximum_GHz=self.maximum.value())
        self.owner.postprocessing_settings=options if options!=DEFAULT_OPTIONS else {}
        dc=dict(method=self.dc_tab.method.currentData(),samples=self.dc_tab.samples.value())
        if dc!=dict(method='skrf',samples=4):self.owner.postprocessing_settings['dc']=dc
        model=dict(repository=self.lumped_tab.repository.text(),tool=self.lumped_tab.tool.currentData(),
                   target_GHz=self.lumped_tab.target.value(),basic=self.lumped_tab.basic.isChecked(),spectre=self.lumped_tab.spectre.isChecked())
        try:
            from .lumped_models import default_repository
        except ImportError:
            from lumped_models import default_repository
        if model['repository']==default_repository():model.pop('repository')
        if model!=dict(tool='inductor_fit',target_GHz=3.,basic=False,spectre=False):
            self.owner.postprocessing_settings['lumped']=model
        plot=self.plot_tab.options()
        if plot!=DEFAULT_PLOT_OPTIONS:self.owner.postprocessing_settings['plot']=plot
        return True

    def load_values(self):
        v=self.owner.postprocessing_settings
        self._loading=True
        self.files.setEditText(v.get('file',''))
        for combo,key,default in [(self.port_a,'port_a',1),(self.port_b,'port_b',2)]:
            combo.clear()
            for number in range(1,max(2,v.get('port_a',1),v.get('port_b',2))+1):combo.addItem(f'Port {number}',number)
            combo.setCurrentIndex(combo.findData(v.get(key,default)))
        self.mode.setCurrentIndex(max(0,self.mode.findData(v.get('mode','inductor'))))
        self.termination.setCurrentIndex(max(0,self.termination.findData(v.get('unused_ports','matched'))))
        self.line_length.setValue(v.get('length',0));self.length_unit.setCurrentText(v.get('length_unit','um'))
        self.phase_branch.setValue(v.get('phase_branch',0));self.minimum.setValue(v.get('minimum_GHz',.1));self.maximum.setValue(v.get('maximum_GHz',0))
        dc=v.get('dc',{});self.dc_tab.method.setCurrentIndex(max(0,self.dc_tab.method.findData(dc.get('method','skrf'))))
        self.dc_tab.samples.setValue(dc.get('samples',4))
        model=v.get('lumped',{})
        try:
            from .lumped_models import default_repository
        except ImportError:
            from lumped_models import default_repository
        self.lumped_tab.repository.setText(model.get('repository',default_repository()))
        self.lumped_tab.tool.setCurrentIndex(max(0,self.lumped_tab.tool.findData(model.get('tool','inductor_fit'))))
        self.lumped_tab.target.setValue(model.get('target_GHz',3.));self.lumped_tab.basic.setChecked(model.get('basic',False));self.lumped_tab.spectre.setChecked(model.get('spectre',False))
        self.plot_tab.load_options(v.get('plot',{}))
        self._loading=False;self.network=None;self.source=None;self.metadata_button.setEnabled(False)
        self.source_label.setText('Configured result (not loaded): '+v['file'] if v.get('file') else
                                  'Load an existing .sNp file. No simulation or de-embedding is performed here.')
        self.invalidate()
        broadband=getattr(self.owner,'broadband_tab',None)
        if broadband is not None:broadband.load_values()
