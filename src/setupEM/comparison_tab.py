"""Editable multi-file overlay plots for postprocessing."""
from datetime import datetime
from pathlib import Path
import numpy as np
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QWidget,QVBoxLayout,QHBoxLayout,QLabel,QTableWidget,QTableWidgetItem,
    QHeaderView,QPushButton,QFileDialog,QComboBox,QSpinBox,QDoubleSpinBox,QCheckBox,QPlainTextEdit)
try:
    from .network_comparison import ComparisonEntry,compare_networks,export_comparison
    from .plot_window import PlotWindow
except ImportError:
    from network_comparison import ComparisonEntry,compare_networks,export_comparison
    from plot_window import PlotWindow


DEFAULT_PLOT_OPTIONS=dict(entries=[],mode='inductor',minimum_GHz=.1,maximum_GHz=0.,
                          zoom=True,zoom_GHz=8.,representation='polar',normalize=False,reference_ohm=50.)


class ComparisonTab(QWidget):
    def __init__(self,analysis):
        super().__init__(analysis);self.analysis=analysis;self.result=None;self.figure=None;self.canvas=None
        self._loading=False;self._markers=[]
        layout=QVBoxLayout(self)
        help=QLabel('Compare Touchstone results on their native frequency grids. Add files, optionally enter short legend names, '
                    'and choose each file’s ports and style. Blank names use the filename. A/B are the differential inductor terminals '
                    'or the two single-ended terminals for S-parameter views.')
        help.setWordWrap(True);layout.addWidget(help)
        row=QHBoxLayout();layout.addLayout(row)
        add=QPushButton('Add files…');loaded=QPushButton('Add loaded result');remove=QPushButton('Remove selected')
        for button in (add,loaded,remove):row.addWidget(button)
        row.addStretch();add.clicked.connect(self.add_files);loaded.clicked.connect(self.add_loaded);remove.clicked.connect(self.remove_selected)
        self.files=QTableWidget(0,7);self.files.setHorizontalHeaderLabels(['Use','Touchstone file','Legend name','Port A','Port B','Unused ports','Style'])
        self.files.horizontalHeader().setSectionResizeMode(1,QHeaderView.Stretch)
        for col in (0,3,4):self.files.setColumnWidth(col,65)
        self.files.setColumnWidth(2,155);self.files.setColumnWidth(5,100);self.files.setColumnWidth(6,125)
        self.files.setSelectionBehavior(QTableWidget.SelectRows);self.files.setWordWrap(False)
        self.files.setFixedHeight(80);layout.addWidget(self.files);self.files.itemChanged.connect(self.invalidate)
        row=QHBoxLayout();layout.addLayout(row)
        self.mode=QComboBox();self.mode.addItem('Inductor L / R / Q','inductor');self.mode.addItem('Raw S-parameters','raw')
        self.representation=QComboBox();self.representation.addItem('Magnitude (dB) / phase','polar');self.representation.addItem('Real / imaginary','cartesian')
        self.minimum=QDoubleSpinBox();self.maximum=QDoubleSpinBox();self.marker=QDoubleSpinBox();self.zoom_limit=QDoubleSpinBox()
        for spin in (self.minimum,self.maximum,self.marker,self.zoom_limit):spin.setRange(0,1e6);spin.setDecimals(6)
        self.minimum.setValue(.1);self.maximum.setSpecialValueText('File end');self.marker.setValue(3);self.zoom_limit.setValue(8)
        row.addWidget(self.mode);row.addWidget(QLabel('Min (GHz)'));row.addWidget(self.minimum)
        row.addWidget(QLabel('Max (GHz)'));row.addWidget(self.maximum);row.addWidget(self.representation);row.addStretch()
        row=QHBoxLayout();layout.addLayout(row)
        self.zoom=QCheckBox('Add low-band panels through (GHz)');self.zoom.setChecked(True)
        row.addWidget(self.zoom);row.addWidget(self.zoom_limit)
        self.normalize=QCheckBox('Common reference (ohm)');self.reference=QDoubleSpinBox();self.reference.setRange(.001,1e6);self.reference.setValue(50)
        self.reference.setDecimals(3);row.addWidget(self.normalize);row.addWidget(self.reference)
        row.addWidget(QLabel('Readout (GHz)'));row.addWidget(self.marker)
        self.plot_button=QPushButton('Plot comparison');row.addWidget(self.plot_button)
        self.status=QLabel('Add files to compare. Source files are never modified.');self.status.setWordWrap(True);layout.addWidget(self.status)
        self.plot_window=PlotWindow(self,'setupEM — Network comparison',self.marker)
        self.plot_layout=self.plot_window.plot_layout
        self.empty=QLabel('Inductor L/R/Q and raw S-parameter overlays');self.empty.setAlignment(Qt.AlignCenter);self.plot_layout.addWidget(self.empty)
        details=QWidget();bottom=QVBoxLayout(details);bottom.setContentsMargins(0,0,0,0)
        self.readout=QTableWidget();self.readout.setEditTriggers(QTableWidget.NoEditTriggers)
        self.readout.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents);self.readout.horizontalHeader().setStretchLastSection(True)
        self.readout.setMinimumHeight(75);bottom.addWidget(self.readout)
        self.diagnostics=QPlainTextEdit();self.diagnostics.setReadOnly(True);self.diagnostics.setMaximumHeight(75);bottom.addWidget(self.diagnostics)
        layout.addWidget(details,1)
        row=QHBoxLayout();layout.addLayout(row)
        self.export_button=QPushButton('Export plots + native CSVs + provenance…');self.export_button.setEnabled(False);row.addWidget(self.export_button)
        self.show_plot_button=QPushButton('Show plots…');self.show_plot_button.setEnabled(False)
        self.show_plot_button.clicked.connect(self.plot_window.reveal);row.addWidget(self.show_plot_button)
        row.addStretch();row.addWidget(QLabel('No smoothing or frequency-grid interpolation.'))
        self.plot_button.clicked.connect(self.plot);self.export_button.clicked.connect(self.export)
        self.mode.currentIndexChanged.connect(self.update_controls)
        for combo in (self.mode,self.representation):combo.currentIndexChanged.connect(self.invalidate)
        for spin in (self.minimum,self.maximum,self.zoom_limit,self.reference):spin.valueChanged.connect(self.invalidate)
        for check in (self.zoom,self.normalize):check.toggled.connect(self.invalidate)
        self.normalize.toggled.connect(self.reference.setEnabled);self.zoom.toggled.connect(self.zoom_limit.setEnabled)
        self.marker.valueChanged.connect(self.update_readout);self.update_controls()

    def update_controls(self):
        raw=self.mode.currentData()=='raw';self.representation.setVisible(raw)
        self.zoom.setVisible(not raw);self.zoom_limit.setVisible(not raw)
        self.reference.setEnabled(self.normalize.isChecked());self.zoom_limit.setEnabled(self.zoom.isChecked())

    def invalidate(self,*args):
        if self._loading:return
        self.result=None;self.export_button.setEnabled(False);self.readout.setRowCount(0);self.diagnostics.clear()
        self.plot_window.set_readout('Settings changed. Plot comparison again to refresh these curves and readouts.')
        self.status.setText('Selection changed. Plot comparison to refresh.')
        if self.figure is not None:
            self.figure.suptitle('Previous comparison — settings changed');self.canvas.draw_idle()

    def add_files(self):
        paths,_=QFileDialog.getOpenFileNames(self,'Add Touchstone results',self.analysis.files.currentText(),'Touchstone (*.s*p *.S*P);;All files (*)')
        for path in paths:self.add_entry(dict(path=path))

    def add_loaded(self):
        try:
            self.analysis.ensure_source();spec=self.analysis.specification()
            self.add_entry(dict(path=self.analysis.source['path'],port_a=spec.port_a,port_b=spec.port_b,unused_ports=spec.unused_ports))
        except (ValueError,OSError) as error:self.status.setText(str(error))

    def add_entry(self,entry):
        self._loading=True
        row=self.files.rowCount();self.files.insertRow(row)
        use=QTableWidgetItem();use.setFlags(Qt.ItemIsUserCheckable|Qt.ItemIsEnabled|Qt.ItemIsSelectable)
        use.setCheckState(Qt.Checked if entry.get('enabled',True) else Qt.Unchecked);self.files.setItem(row,0,use)
        item=QTableWidgetItem(entry.get('path',''));item.setToolTip(entry.get('path',''));self.files.setItem(row,1,item)
        self.files.setItem(row,2,QTableWidgetItem(entry.get('label','')))
        for col,key,default in ((3,'port_a',1),(4,'port_b',2)):
            spin=QSpinBox();spin.setRange(1,65535);spin.setValue(entry.get(key,default));self.files.setCellWidget(row,col,spin);spin.valueChanged.connect(self.invalidate)
        for col,key,choices in ((5,'unused_ports',[('Matched','matched'),('Open','open')]),
                                (6,'style',[('Line + markers','markers'),('Line','line'),('Points only','points')])):
            combo=QComboBox()
            for text,data in choices:combo.addItem(text,data)
            combo.setCurrentIndex(max(0,combo.findData(entry.get(key,choices[0][1]))));self.files.setCellWidget(row,col,combo)
            combo.currentIndexChanged.connect(self.invalidate)
        self._loading=False;self.resize_file_table();self.invalidate()

    def resize_file_table(self):
        self.files.setFixedHeight(min(180,max(80,self.files.horizontalHeader().height()+self.files.rowCount()*self.files.verticalHeader().defaultSectionSize()+4)))

    def remove_selected(self):
        for row in sorted({item.row() for item in self.files.selectedIndexes()},reverse=True):self.files.removeRow(row)
        self.resize_file_table();self.invalidate()

    def options(self):
        entries=[]
        for row in range(self.files.rowCount()):
            entries.append(dict(enabled=self.files.item(row,0).checkState()==Qt.Checked,
                path=self.files.item(row,1).text().strip(),label=self.files.item(row,2).text().strip(),
                port_a=self.files.cellWidget(row,3).value(),port_b=self.files.cellWidget(row,4).value(),
                unused_ports=self.files.cellWidget(row,5).currentData(),style=self.files.cellWidget(row,6).currentData()))
        return dict(entries=entries,mode=self.mode.currentData(),minimum_GHz=self.minimum.value(),maximum_GHz=self.maximum.value(),
                    zoom=self.zoom.isChecked(),zoom_GHz=self.zoom_limit.value(),representation=self.representation.currentData(),
                    normalize=self.normalize.isChecked(),reference_ohm=self.reference.value())

    def load_options(self,options):
        self._loading=True;self.files.setRowCount(0)
        for entry in options.get('entries',[]):self.add_entry(entry)
        self._loading=True
        for combo,key in ((self.mode,'mode'),(self.representation,'representation')):
            combo.setCurrentIndex(max(0,combo.findData(options.get(key,DEFAULT_PLOT_OPTIONS[key]))))
        for spin,key in ((self.minimum,'minimum_GHz'),(self.maximum,'maximum_GHz'),(self.zoom_limit,'zoom_GHz'),(self.reference,'reference_ohm')):
            spin.setValue(options.get(key,DEFAULT_PLOT_OPTIONS[key]))
        self.zoom.setChecked(options.get('zoom',True));self.normalize.setChecked(options.get('normalize',False))
        self._loading=False;self.resize_file_table();self.update_controls();self.invalidate()

    def plot(self):
        self.invalidate()
        try:
            options=self.options();entries=[ComparisonEntry(**{key:value for key,value in e.items() if key!='enabled'}) for e in options['entries'] if e['enabled']]
            result=compare_networks(entries,options['mode'],options['minimum_GHz']*1e9,options['maximum_GHz']*1e9,
                                    options['reference_ohm'] if options['normalize'] else None)
            if result['mode']=='inductor' and options['zoom'] and options['zoom_GHz']<=options['minimum_GHz']:
                raise ValueError('Low-band upper limit must exceed the minimum frequency.')
            self.result=result;self._plotted_options=options;self.draw();self.update_readout()
            messages=list(result['warnings'])
            for curve in result['curves']:
                messages.extend(curve['label']+': '+warning for warning in curve['warnings'])
            self.diagnostics.setPlainText('\n'.join(messages) or 'No extraction diagnostics.')
            self.status.setText(f"{len(result['curves'])} file(s) plotted. Each curve retains its own native samples; readout selects the nearest sample per file.")
            self.export_button.setEnabled(True)
            self.plot_window.reveal()
        except (ValueError,OSError,ArithmeticError) as error:
            self.result=None;self.status.setText('Cannot plot comparison: '+str(error))

    def draw(self):
        if self.figure is None:
            from matplotlib.figure import Figure
            from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg,NavigationToolbar2QT
            self.figure=Figure(figsize=(12,10),layout='constrained');self.canvas=FigureCanvasQTAgg(self.figure)
            self.plot_layout.removeWidget(self.empty);self.empty.hide()
            self.plot_layout.addWidget(NavigationToolbar2QT(self.canvas,self));self.plot_layout.addWidget(self.canvas,1)
            self.show_plot_button.setEnabled(True)
            self.canvas.mpl_connect('button_press_event',self.plot_clicked)
        self.figure.clear();self._markers=[];self._axis_limits={}
        options=self._plotted_options;inductor=self.result['mode']=='inductor'
        columns=2 if not inductor or options['zoom'] else 1
        axes=self.figure.subplots(3 if inductor else 4,columns,squeeze=False,sharex='col')
        keys=[('L_H','L (nH)',1e9),('R_ohm','R (ohm)',1),('Q','Q',1)] if inductor else [('aa','Saa',1),('ba','Sba',1),('ab','Sab',1),('bb','Sbb',1)]
        from matplotlib import colormaps
        colors=colormaps['tab10'];markers=['o','s','^','D','v','P','X','<','>','h']
        for number,curve in enumerate(self.result['curves']):
            style=curve['entry']['style'];kwargs=dict(color=colors(number%10),lw=1.4,label=curve['label'])
            if style!='line':kwargs.update(marker=markers[number%len(markers)],markerfacecolor='none',markersize=4,
                markevery=1 if style=='points' else max(1,len(curve['frequency_hz'])//18))
            if style=='points':kwargs['linestyle']='none'
            f=curve['frequency_hz']/1e9
            for row,(key,label,scale) in enumerate(keys):
                for col in range(columns):
                    if inductor:
                        values=curve['columns'][key]*scale;mask=f<=options['zoom_GHz'] if columns==2 and col==0 else np.ones(len(f),bool)
                        ylabel=label
                    else:
                        suffix=('_dB','_phase_deg') if options['representation']=='polar' else ('_real','_imag')
                        values=curve['columns'][key+suffix[col]];mask=np.ones(len(f),bool)
                        ylabel=label+' '+(('(dB)','(°)')[col] if options['representation']=='polar' else ('real','imaginary')[col])
                    axis=axes[row,col];axis.plot(f[mask],values[mask],**kwargs);axis.set_ylabel(ylabel,fontsize=9)
        for row in range(len(keys)):
            for col in range(columns):
                axis=axes[row,col];axis.grid(alpha=.3);axis.tick_params(labelsize=8)
                if row==len(keys)-1:axis.set_xlabel('Frequency (GHz)',fontsize=9)
                self._axis_limits[axis]=axis.get_xlim()
                self._markers.append(axis.axvline(self.marker.value(),color='grey',ls=':',lw=.7))
                axis.set_xlim(self._axis_limits[axis])
                if inductor and columns==2 and row==0:axis.set_title(f"Low band ≤ {options['zoom_GHz']:g} GHz" if col==0 else 'Selected full band',fontsize=10)
        handles,labels=axes[0,0].get_legend_handles_labels()
        self.figure.legend(handles,labels,loc='outside lower center',ncols=min(4,len(labels)),fontsize=8)
        self.figure.suptitle('Differential inductor comparison' if inductor else 'S-parameter comparison (phase unwrapped): A / B are selected per file',fontsize=10)
        self.canvas.draw_idle()

    def plot_clicked(self,event):
        if event.inaxes and event.xdata is not None and event.xdata>=0:self.marker.setValue(event.xdata)

    def update_readout(self,*args):
        if self.result is None:return
        inductor=self.result['mode']=='inductor'
        headers=['Legend','Native GHz','L (nH)','R (ohm)','Q','Peak Q','Peak GHz'] if inductor else ['Legend','Native GHz','Saa','Sba','Sab','Sbb']
        self.readout.setColumnCount(len(headers));self.readout.setHorizontalHeaderLabels(headers)
        self.readout.setRowCount(len(self.result['curves']))
        self.readout.setMinimumHeight(min(140,30+len(self.result['curves'])*30))
        def fmt(value):return f'{value:.7g}' if value is not None and np.isfinite(value) else 'undefined'
        for row,curve in enumerate(self.result['curves']):
            index=int(np.argmin(abs(curve['frequency_hz']-self.marker.value()*1e9)));f=curve['frequency_hz'][index]
            values=[curve['label'],fmt(f/1e9)];data=curve['columns'];s=curve['summary']
            if inductor:values += [fmt(data['L_H'][index]*1e9),fmt(data['R_ohm'][index]),fmt(data['Q'][index]),fmt(s['peak_Q']),fmt(s['peak_Q_frequency_Hz']/1e9 if s['peak_Q_frequency_Hz'] is not None else None)]
            else:values += [f"{data[key+'_real'][index]:.5g}{data[key+'_imag'][index]:+.5g}j" for key in ('aa','ba','ab','bb')]
            for col,value in enumerate(values):self.readout.setItem(row,col,QTableWidgetItem(value))
        for marker in self._markers:marker.set_xdata([self.marker.value()]*2)
        self.plot_window.set_readout('\n'.join(' | '.join(headers[col]+': '+self.readout.item(row,col).text()
            for col in range(len(headers))) for row in range(self.readout.rowCount())))
        if self.canvas:self.canvas.draw_idle()

    def export(self):
        if self.result is None:return
        parent=QFileDialog.getExistingDirectory(self,'Choose parent for a new comparison output folder')
        if not parent:return
        try:
            folder=export_comparison(self.result,Path(parent)/('comparison_'+datetime.now().strftime('%Y%m%d_%H%M%S_%f')),self._plotted_options)
            size=self.figure.get_size_inches().copy()
            try:
                self.figure.set_size_inches(12,10 if self.result['mode']=='inductor' else 13,forward=False)
                self.figure.savefig(folder/'comparison.png',dpi=160);self.figure.savefig(folder/'comparison.svg')
            finally:
                self.figure.set_size_inches(size,forward=False);self.canvas.draw_idle()
            self.status.setText('Exported plots, native CSVs and provenance: '+str(folder))
        except (ValueError,OSError) as error:self.status.setText('Cannot export: '+str(error))
