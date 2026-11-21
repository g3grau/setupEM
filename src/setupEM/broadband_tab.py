"""Broadband N-port macromodel fitting through snp2le's optional pure core."""
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
import importlib.util
import json
import sys
from PySide6.QtCore import QProcess,QProcessEnvironment,QTimer,QElapsedTimer
from PySide6.QtWidgets import (QWidget,QVBoxLayout,QHBoxLayout,QFormLayout,QLabel,QLineEdit,QPushButton,
    QFileDialog,QSpinBox,QDoubleSpinBox,QCheckBox,QComboBox,QPlainTextEdit,QTableWidget,QTableWidgetItem,
    QHeaderView,QProgressBar,QDialog,QDialogButtonBox,QApplication)
try:
    from .broadband_model import BroadbandSpec,prepare_broadband_run,default_engine_python
    from .network_parameters import load_touchstone
except ImportError:
    from broadband_model import BroadbandSpec,prepare_broadband_run,default_engine_python
    from network_parameters import load_touchstone


class BroadbandModelTab(QWidget):
    independent_analysis_tab=True

    def __init__(self,window):
        super().__init__(window);self.window=window;self.source=None;self.network=None;self.process=None;self.folder=None;self.report=None;self._buffer=''
        if not hasattr(window,'broadband_settings'):window.broadband_settings={}
        layout=QVBoxLayout(self)
        label=QLabel('Universal N-port vector fitting with snp2le. Fits every port in the file, independently of the port pair in Postprocessing. '
            'The model reproduces terminal behavior; its elements are not physical device values. Each run writes a new output folder.')
        label.setWordWrap(True);layout.addWidget(label)
        row=QHBoxLayout();layout.addLayout(row);row.addWidget(QLabel('Touchstone source'))
        self.file=QLineEdit();row.addWidget(self.file,1)
        browse=QPushButton('Browse…');row.addWidget(browse);browse.clicked.connect(self.browse)
        use=QPushButton('Use postprocessing file');row.addWidget(use);use.clicked.connect(self.use_postprocessing)
        load=QPushButton('Load');row.addWidget(load);load.clicked.connect(self.load_file)
        self.source_label=QLabel('Load any .sNp file. No EM simulation is required.');self.source_label.setWordWrap(True);layout.addWidget(self.source_label)
        form=QFormLayout();layout.addLayout(form)
        row=QHBoxLayout();self.minimum=QDoubleSpinBox();self.maximum=QDoubleSpinBox()
        for spin in (self.minimum,self.maximum):spin.setRange(0,1e6);spin.setDecimals(6)
        self.minimum.setSpecialValueText('File start');self.maximum.setSpecialValueText('File end')
        row.addWidget(QLabel('Min (GHz)'));row.addWidget(self.minimum);row.addWidget(QLabel('Max (GHz)'));row.addWidget(self.maximum)
        self.order=QSpinBox();self.order.setRange(2,1000);self.order.setValue(6)
        row.addWidget(QLabel('Maximum order'));row.addWidget(self.order)
        self.order.setToolTip('Real poles + twice complex pole pairs. The automatic fit may use a lower order; actual order is reported.')
        form.addRow('Fit controls',row)
        row=QHBoxLayout();self.passive=QCheckBox('Enforce passivity');self.passive.setChecked(True);row.addWidget(self.passive)
        self.dc_pin=QCheckBox('Pin to supplied DC point');self.dc_pin.setChecked(True);row.addWidget(self.dc_pin)
        self.noise=QCheckBox('Include passive thermal noise');row.addWidget(self.noise);row.addStretch();form.addRow(row)
        self.dc_info=QLabel('A DC pin needs a finite 0 Hz source sample. It does not create a DC solution or validate an extrapolated target.');self.dc_info.setWordWrap(True);form.addRow(self.dc_info)
        row=QHBoxLayout();self.name=QLineEdit('broadband_model');row.addWidget(QLabel('Subcircuit'));row.addWidget(self.name,1)
        self.dialect=QComboBox()
        for title,key in [('All three dialects','all'),('Ngspice','ngspice'),('VACASK (Spectre syntax)','vacask'),('Xyce','xyce')]:self.dialect.addItem(title,key)
        row.addWidget(QLabel('Netlist'));row.addWidget(self.dialect);form.addRow(row)
        self.advanced_button=QPushButton('Advanced options…');self.advanced_button.setCheckable(True);form.addRow(self.advanced_button)
        self.advanced=QWidget();advanced=QFormLayout(self.advanced);self.advanced.setVisible(False);layout.addWidget(self.advanced)
        self.ceiling=QDoubleSpinBox();self.ceiling.setRange(1,1.2);self.ceiling.setDecimals(3);self.ceiling.setSingleStep(.001);self.ceiling.setValue(1)
        advanced.addRow('Passivity ceiling (1.0 = strict; higher allows violations)',self.ceiling)
        self.convex=QSpinBox();self.convex.setRange(0,100000);self.convex.setValue(100);advanced.addRow('Convex refit state limit (ports × order; 0 = off)',self.convex)
        self.dc_corner=QDoubleSpinBox();self.dc_corner.setRange(.000001,1e12);self.dc_corner.setDecimals(6);self.dc_corner.setValue(160)
        advanced.addRow('DC correction corner (Hz)',self.dc_corner)
        self.dc_leak=QDoubleSpinBox();self.dc_leak.setRange(0,1e6);self.dc_leak.setDecimals(6);self.dc_leak.setValue(0)
        advanced.addRow('Optional DC island leak (µS, changes the model; 0 = off)',self.dc_leak)
        note=QLabel('Without thermal-noise generation, universal macromodel resistors are noiseless. The DC pin may be modified or rejected by snp2le after its checks; the report records the outcome. VACASK syntax is not a separately validated Cadence Spectre backend.')
        note.setWordWrap(True);advanced.addRow(note)
        self.advanced_button.toggled.connect(self.advanced.setVisible)
        row=QHBoxLayout();layout.addLayout(row);row.addWidget(QLabel('Engine Python'))
        self.engine_python=QLineEdit(default_engine_python());row.addWidget(self.engine_python,1)
        engine_browse=QPushButton('Browse…');row.addWidget(engine_browse);engine_browse.clicked.connect(self.browse_engine)
        self.backend=QLabel();self.backend.setWordWrap(True);layout.addWidget(self.backend);self.refresh_backend()
        self.engine_python.editingFinished.connect(self.refresh_backend)
        row=QHBoxLayout();layout.addLayout(row)
        self.run_button=QPushButton('Fit broadband model in new folder…');row.addWidget(self.run_button)
        self.stop_button=QPushButton('Stop fit');self.stop_button.setEnabled(False);row.addWidget(self.stop_button)
        self.compare_button=QPushButton('Compare source / model…');self.compare_button.setEnabled(False);row.addWidget(self.compare_button);row.addStretch()
        self.elapsed_label=QLabel('Elapsed 00:00:00');row.addWidget(self.elapsed_label)
        self.progress=QProgressBar();self.progress.setRange(0,100);self.progress.setValue(0);layout.addWidget(self.progress)
        self.status=QLabel('Ready. Fit error, passivity and DC diagnostics are reported independently.');self.status.setWordWrap(True);layout.addWidget(self.status)
        self.summary=QPlainTextEdit();self.summary.setReadOnly(True);self.summary.setMaximumHeight(145);layout.addWidget(self.summary)
        self.errors=QTableWidget(0,5);self.errors.setHorizontalHeaderLabels(['Response port','Excited port','RMS |ΔS|','Max |ΔS|','Relative RMS (%)'])
        self.errors.setEditTriggers(QTableWidget.NoEditTriggers);self.errors.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch);layout.addWidget(self.errors,1)
        self.log=QPlainTextEdit();self.log.setReadOnly(True);self.log.setMaximumHeight(100);layout.addWidget(self.log)
        row=QHBoxLayout();layout.addLayout(row);self.artifacts=QComboBox();row.addWidget(self.artifacts,1)
        view=QPushButton('View output');row.addWidget(view);view.clicked.connect(self.view_output)
        self.run_button.clicked.connect(self.start);self.stop_button.clicked.connect(self.stop);self.compare_button.clicked.connect(self.compare)
        for widget in (self.file,self.name,self.engine_python):widget.textChanged.connect(self.changed)
        for widget in (self.minimum,self.maximum,self.order,self.ceiling,self.convex,self.dc_corner,self.dc_leak):widget.valueChanged.connect(self.changed)
        for widget in (self.passive,self.dc_pin,self.noise):widget.toggled.connect(self.changed)
        self.dialect.currentIndexChanged.connect(self.changed)
        self.clock=QElapsedTimer();self.timer=QTimer(self);self.timer.setInterval(300);self.timer.timeout.connect(self.update_elapsed)
        QApplication.instance().aboutToQuit.connect(self.shutdown)

    def refresh_backend(self):
        importlib.invalidate_caches()
        python=self.engine_python.text().strip()
        same=Path(python).absolute()==Path(sys.executable).absolute()
        available=Path(python).expanduser().is_file() and (not same or importlib.util.find_spec('snp2le') is not None)
        self.backend.setText(('Backend: snp2le in the selected Python will be checked when fitting. ' if not same else 'Backend: installed snp2le. ')+python if available else
            'Choose a Python with snp2le installed. A separate environment avoids conflicts with simulator or gerber2ems dependencies.')
        return available

    def browse_engine(self):
        path,_=QFileDialog.getOpenFileName(self,'Python executable with snp2le',self.engine_python.text(),'All files (*)')
        if path:self.engine_python.setText(path);self.refresh_backend()

    def browse(self):
        path,_=QFileDialog.getOpenFileName(self,'Broadband model source',self.file.text(),'Touchstone (*.s*p *.S*P);;All files (*)')
        if path:self.file.setText(path);self.load_file()

    def use_postprocessing(self):
        self.file.setText(self.window.postprocessing_tab.files.currentText());self.load_file()

    def load_file(self):
        try:
            self.network,self.source=load_touchstone(self.file.text())
            import numpy as np
            n=self.network
            self.source_label.setText(f"{self.source['path']} | {n.nports} ports, {len(n.f)} samples, {n.f[0]/1e9:g}–{n.f[-1]/1e9:g} GHz | SHA256 {self.source['sha256'][:16]}…")
            self.dc_info.setText('Finite source DC point present: snp2le can attempt a checked DC pin. Its result is reported; an extrapolated source point remains an extrapolated target.' if n.f[0]==0 and np.isfinite(n.s[0]).all() else
                'No finite source DC point. DC pin will be inactive; circuit DC behavior is extrapolated from AC data. Use an explicitly DC-extended source if required.')
        except (OSError,ValueError,IndexError) as error:
            self.network=None;self.source=None;self.source_label.setText('Cannot load source: '+str(error))

    def specification(self):
        return BroadbandSpec(maximum_order=self.order.value(),minimum_hz=self.minimum.value()*1e9,maximum_hz=self.maximum.value()*1e9,
            enforce_passivity=self.passive.isChecked(),passivity_ceiling=self.ceiling.value(),convex_max_states=self.convex.value(),
            thermal_noise=self.noise.isChecked(),dc_pin=self.dc_pin.isChecked(),dc_pin_corner_hz=self.dc_corner.value(),
            dc_island_leak_siemens=self.dc_leak.value()*1e-6,dialect=self.dialect.currentData(),subcircuit=self.name.text())

    def changed(self,*args):
        if self.report:self.status.setText('Settings changed. Displayed diagnostics and output files belong to the last run; fit again to apply these settings.')

    def start(self):
        if self.process and self.process.state()!=QProcess.NotRunning:return
        parent=QFileDialog.getExistingDirectory(self,'Choose parent for a new broadband-model folder',str(Path(self.file.text()).parent))
        if parent:self.start_run(Path(parent)/('broadband_'+datetime.now().strftime('%Y%m%d_%H%M%S_%f')))

    def start_run(self,folder):
        if self.process and self.process.state()!=QProcess.NotRunning:return
        try:
            if not self.refresh_backend():raise ValueError('Install snp2le into the setupEM Python environment first. See Backend above.')
            command,prepared=prepare_broadband_run(self.file.text(),self.specification(),folder,self.engine_python.text().strip())
            self.folder=prepared;self.report=None;self.summary.clear();self.errors.setRowCount(0);self.artifacts.clear();self.log.clear()
            self.compare_button.setEnabled(False);self.run_button.setEnabled(False);self.stop_button.setEnabled(True);self.progress.setValue(0)
            self._buffer='';self._run_settings=dict(file=self.file.text(),specification=asdict(self.specification()),python=self.engine_python.text())
            self.process=QProcess(self);self.process.setWorkingDirectory(str(prepared));self.process.setProcessChannelMode(QProcess.MergedChannels)
            env=QProcessEnvironment.systemEnvironment();env.insert('PYTHONUNBUFFERED','1')
            for name in ('OMP_NUM_THREADS','OPENBLAS_NUM_THREADS','MKL_NUM_THREADS'):env.insert(name,'1')
            self.process.setProcessEnvironment(env);self.process.readyReadStandardOutput.connect(self.read_output)
            self.process.finished.connect(self.finished);self.process.errorOccurred.connect(self.process_error)
            self.status.setText('Fitting all ports in the background. Output: '+str(prepared));self.clock.start();self.timer.start()
            self.process.start(command[0],command[1:])
        except (OSError,ValueError) as error:self.status.setText('Cannot start broadband fit: '+str(error))

    def read_output(self):
        data=bytes(self.process.readAllStandardOutput()).decode('utf-8',errors='replace')
        if not data:return
        with (self.folder/'console.log').open('a',encoding='utf-8') as stream:stream.write(data)
        self._buffer+=data
        while '\n' in self._buffer:
            line,self._buffer=self._buffer.split('\n',1)
            if line.startswith('@setupEM-progress '):
                try:
                    event=json.loads(line.split(' ',1)[1]);self.progress.setValue(int(100*event['fraction']));self.status.setText(event['message'])
                except (ValueError,KeyError):self.log.appendPlainText(line)
            elif line:self.log.appendPlainText(line)

    def update_elapsed(self):
        if not self.clock.isValid():return
        seconds=self.clock.elapsed()//1000
        self.elapsed_label.setText(f'Elapsed {seconds//3600:02d}:{seconds//60%60:02d}:{seconds%60:02d}')

    def finished(self,code,status):
        self.read_output();self.update_elapsed();self.timer.stop();self.run_button.setEnabled(True);self.stop_button.setEnabled(False)
        if self._buffer:self.log.appendPlainText(self._buffer);self._buffer=''
        path=self.folder/'fit_report.json'
        if path.exists():
            try:self.report=json.loads(path.read_text())
            except (ValueError,OSError):self.report=None
        manifest_path=self.folder/'run.json';manifest=json.loads(manifest_path.read_text())
        if code!=0 or status!=QProcess.NormalExit:
            manifest.update(status='failed_or_stopped',exit_code=code);manifest_path.write_text(json.dumps(manifest,indent=2)+'\n')
            self.status.setText('Broadband fit failed or stopped. '+str((self.report or {}).get('error','Review console.log.')))
        elif self.report and self.report.get('ok'):
            self.show_report();self.progress.setValue(100);self.compare_button.setEnabled(True)
            self.status.setText('Fit complete. Review fit, passivity and DC diagnostics. Outputs: '+str(self.folder))
            if self._run_settings!=dict(file=self.file.text(),specification=asdict(self.specification()),python=self.engine_python.text()):
                self.status.setText('Fit complete for the saved run snapshot. Controls have since changed; displayed diagnostics belong to '+str(self.folder))
        else:self.status.setText('No successful fit report was produced. Review the log.')
        for item in sorted(self.folder.iterdir()):
            if item.is_file():self.artifacts.addItem(item.name,str(item))

    def show_report(self):
        r=self.report
        lines=[f"Source snapshot: {r['source']['path']}",
            f"{r['n_ports']}-port universal model; actual order {r['actual_model_order']} (maximum requested {r['maximum_order_requested']})",
            f"Band {r['fit_band_Hz'][0]/1e9:g}–{r['fit_band_Hz'][1]/1e9:g} GHz; {r['samples']} native AC samples; reference {r['reference_ohm']:g} ohm",
            f"Sampled RMS |ΔS|: {r['sampled_rms_abs_S_error']:.6g}; maximum |ΔS|: {r['sampled_max_abs_S_error']:.6g}",
            f"Passivity: {'meets' if r['passive'] else 'does not meet'} ceiling {r['passivity_ceiling']:g}; sigma max {r['sigma_max']}; path: {r['passivity_path']}"]
        for key,title in [('dc_health','DC operating point'),('dc_pin','DC pin'),('noise','Thermal noise')]:
            value=r.get(key);lines.append(value['message'] if isinstance(value,dict) and value.get('message') else title+': not applied')
        lines.extend(r.get('messages',[]));self.summary.setPlainText('\n'.join(lines))
        self.errors.setRowCount(len(r['traces']))
        for row,trace in enumerate(r['traces']):
            values=[trace['response_port'],trace['excited_port'],trace['rms_abs_S_error'],trace['maximum_abs_S_error'],trace['relative_rms_percent']]
            for col,value in enumerate(values):self.errors.setItem(row,col,QTableWidgetItem('undefined' if value is None else f'{value:.7g}'))

    def process_error(self,error):
        self.log.appendPlainText('Process error: '+self.process.errorString())
        if error==QProcess.FailedToStart:self.finished(-1,QProcess.CrashExit)

    def stop(self):
        if self.process and self.process.state()!=QProcess.NotRunning:self.process.kill()

    def shutdown(self):
        self.stop()
        if self.process:self.process.waitForFinished(1000)

    def compare(self):
        if not self.report or not self.report.get('ok'):return
        tab=self.window.postprocessing_tab;plot=tab.plot_tab;ports=self.report['n_ports']
        for stem,label in [('normalized_data','Source (fit snapshot)'),('fitted','Broadband model')]:
            path=str(self.folder/f'{stem}.s{ports}p')
            if not any(plot.files.item(row,1).text()==path for row in range(plot.files.rowCount())):
                plot.add_entry(dict(path=path,label=label,port_a=1,port_b=min(2,ports)))
        plot.mode.setCurrentIndex(1);plot.minimum.setValue(self.report['fit_band_Hz'][0]/1e9);plot.maximum.setValue(self.report['fit_band_Hz'][1]/1e9)
        plot.normalize.setChecked(True);plot.reference.setValue(self.report['reference_ohm'])
        self.window.tabs_widget.setCurrentWidget(tab);tab.subtabs.setCurrentWidget(plot);plot.plot()

    def view_output(self):
        path=self.artifacts.currentData()
        if not path:return
        if Path(path).suffix=='.npz':self.status.setText('fit_arrays.npz contains frequency_hz, data_s and model_s arrays; use Compare for plots.');return
        dialog=QDialog(self);dialog.resize(1000,750);dialog.setWindowTitle(Path(path).name);layout=QVBoxLayout(dialog)
        text=QPlainTextEdit();text.setReadOnly(True);text.setPlainText(Path(path).read_text(errors='replace'));layout.addWidget(text)
        buttons=QDialogButtonBox(QDialogButtonBox.Close);buttons.rejected.connect(dialog.reject);layout.addWidget(buttons);dialog.exec()

    def save_values(self):
        settings=dict(file=self.file.text(),specification=asdict(self.specification()))
        if self.engine_python.text()!=default_engine_python():settings['python']=self.engine_python.text()
        self.window.broadband_settings=settings if settings['file'] or settings['specification']!=asdict(BroadbandSpec()) or 'python' in settings else {}
        return True

    def load_values(self):
        settings=self.window.broadband_settings;spec=BroadbandSpec(**settings.get('specification',{}))
        self.engine_python.setText(settings.get('python',default_engine_python()));self.refresh_backend()
        self.file.setText(settings.get('file',''));self.order.setValue(spec.maximum_order)
        self.minimum.setValue(spec.minimum_hz/1e9);self.maximum.setValue(spec.maximum_hz/1e9)
        self.passive.setChecked(spec.enforce_passivity);self.ceiling.setValue(spec.passivity_ceiling);self.convex.setValue(spec.convex_max_states)
        self.noise.setChecked(spec.thermal_noise);self.dc_pin.setChecked(spec.dc_pin);self.dc_corner.setValue(spec.dc_pin_corner_hz);self.dc_leak.setValue(spec.dc_island_leak_siemens*1e6)
        self.dialect.setCurrentIndex(max(0,self.dialect.findData(spec.dialect)));self.name.setText(spec.subcircuit)
        self.source=None;self.network=None
