"""DC extension and isolated lumpedmodel sub-tabs, sharing the loaded source."""
from pathlib import Path
from datetime import datetime
import hashlib
import json
from PySide6.QtCore import QProcess, QProcessEnvironment
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (QWidget,QVBoxLayout,QHBoxLayout,QFormLayout,QLabel,QComboBox,
    QSpinBox,QDoubleSpinBox,QPushButton,QPlainTextEdit,QLineEdit,QFileDialog,QCheckBox,
    QDialog,QDialogButtonBox,QApplication,QScrollArea)
try:
    from .dc_extension import extend_dc,export_dc
    from .lumped_models import TOOLS,default_repository,prepare_model_run
    from .path_config import browse_start
except ImportError:
    from dc_extension import extend_dc,export_dc
    from lumped_models import TOOLS,default_repository,prepare_model_run
    from path_config import browse_start


class DCExtensionTab(QWidget):
    def __init__(self,analysis):
        super().__init__(analysis);self.analysis=analysis;self.result=None;self.report=None
        layout=QVBoxLayout(self)
        help=QLabel('Estimate DC from the lowest AC samples of the full loaded network (all ports). '
                    'This is an extrapolation, not a solved DC point. Native positive-frequency samples stay unchanged. '
                    'Export a separate file after reviewing the real DC S matrix and diagnostics below.')
        help.setWordWrap(True);layout.addWidget(help)
        form=QFormLayout();layout.addLayout(form)
        self.method=QComboBox();self.method.addItem('scikit-rf: two-point magnitude / phase extrapolation','skrf')
        self.method.addItem('Real S: linear fit over lowest N samples','cartesian');form.addRow('DC estimate',self.method)
        self.samples=QSpinBox();self.samples.setRange(2,1000);self.samples.setValue(4);form.addRow('Samples for real-S fit',self.samples)
        row=QHBoxLayout();layout.addLayout(row)
        self.calculate=QPushButton('Estimate DC');self.export_button=QPushButton('Export separate .sNp + DC report…')
        self.export_button.setEnabled(False);row.addWidget(self.calculate);row.addWidget(self.export_button);row.addStretch()
        self.details=QPlainTextEdit();self.details.setReadOnly(True);layout.addWidget(self.details,1)
        self.calculate.clicked.connect(self.estimate);self.export_button.clicked.connect(self.export)
        self.method.currentIndexChanged.connect(self.invalidate);self.samples.valueChanged.connect(self.invalidate)
        self.method.currentIndexChanged.connect(lambda:self.samples.setEnabled(self.method.currentData()=='cartesian'))
        self.samples.setEnabled(False)

    def invalidate(self,*args):
        self.result=None;self.report=None;self.export_button.setEnabled(False);self.details.clear()

    def estimate(self):
        self.invalidate()
        try:
            self.analysis.ensure_source()
            self.result,self.report=extend_dc(self.analysis.network,self.analysis.source,self.method.currentData(),self.samples.value())
            import numpy as np
            r=self.report
            lines=[f"Source: {r['source'].get('path','')}",
                   f"Method: {self.method.currentText()}",
                   f"Lowest {r['samples_used']} AC samples: {r['estimation_band_Hz'][0]/1e9:g}–{r['estimation_band_Hz'][1]/1e9:g} GHz",
                   f"Added one DC sample; {len(self.result)-1} native AC samples preserved.",
                   '', 'Real DC S matrix (row = response port, column = excited port):',
                   np.array2string(self.result.s[0].real,precision=9), '',
                   f"Largest DC singular value: {r['dc_max_singular_value']:.9g} (passive requires ≤ 1)",
                   f"Difference from two-point real-S estimate: {r['max_difference_from_two_point_cartesian']:.6g} (maximum |ΔS|)"]
            if r.get('estimated_differential_DC_resistance_ohm') is not None:
                lines.append(f"Estimated differential DC resistance (ports 1/2): {r['estimated_differential_DC_resistance_ohm']:.9g} ohm")
            lines+=['','Review before circuit simulation:']+['• '+message for message in r['warnings']]
            self.details.setPlainText('\n'.join(lines));self.export_button.setEnabled(True)
        except (ValueError,OSError,ArithmeticError) as error:self.details.setPlainText('Cannot estimate DC: '+str(error))

    def export(self):
        if self.result is None:return
        source=Path(self.report['source']['path'])
        path,_=QFileDialog.getSaveFileName(self,'Save DC-extended derivative',str(source.with_name(source.stem+'_dc'+source.suffix)),f'Touchstone (*.s{self.result.nports}p)')
        if not path:return
        try:
            output,report=export_dc(self.result,self.report,path)
            self.details.appendPlainText(f'\nSaved {output}\nReport: {report}')
        except (ValueError,OSError) as error:self.details.appendPlainText('Export failed: '+str(error))


class LumpedModelsTab(QWidget):
    def __init__(self,analysis):
        super().__init__(analysis);self.analysis=analysis;self.folder=None;self.process=None
        layout=QVBoxLayout(self)
        label=QLabel('Run the separately installed lumpedmodel tools by Volker Muehlhaus (GPL-3.0-or-later). '
                     'Uses the port pair, unused-port terminations, frequency band and line length from Parameters. '
                     'Selected data is renormalized to 50 ohm for these scripts. No synthetic DC point is fitted. '
                     'Each run creates a new folder with source provenance, logs and available model/plot files. '
                     'Fitted circuit DC values need review against physical resistance and connectivity.')
        label.setWordWrap(True);layout.addWidget(label)
        form=QFormLayout();layout.addLayout(form)
        row=QHBoxLayout();self.repository=QLineEdit(default_repository());row.addWidget(self.repository)
        browse=QPushButton('Browse…');row.addWidget(browse);form.addRow('lumpedmodel checkout',row)
        browse.clicked.connect(self.browse_repository)
        self.tool=QComboBox()
        for key,title in TOOLS.items():self.tool.addItem(title,key)
        form.addRow('Model',self.tool)
        self.target=QDoubleSpinBox();self.target.setRange(.000001,1e6);self.target.setDecimals(6);self.target.setValue(3)
        form.addRow('Target frequency (GHz)',self.target)
        self.basic=QCheckBox('Basic fixed topology (one segment, one skin section)');form.addRow(self.basic)
        self.spectre=QCheckBox('Spectre netlist instead of SPICE');form.addRow(self.spectre)
        self.description=QLabel();self.description.setWordWrap(True);layout.addWidget(self.description)
        row=QHBoxLayout();layout.addLayout(row)
        self.run_button=QPushButton('Run in new output folder…');self.stop_button=QPushButton('Stop fit');self.stop_button.setEnabled(False)
        row.addWidget(self.run_button);row.addWidget(self.stop_button);row.addStretch()
        self.log=QPlainTextEdit();self.log.setReadOnly(True);layout.addWidget(self.log,1)
        row=QHBoxLayout();layout.addLayout(row);self.artifacts=QComboBox();row.addWidget(self.artifacts,1)
        view=QPushButton('View selected output');row.addWidget(view);view.clicked.connect(self.view_artifact)
        self.run_button.clicked.connect(self.start);self.stop_button.clicked.connect(self.stop)
        self.tool.currentIndexChanged.connect(self.update_controls);self.update_controls()
        QApplication.instance().aboutToQuit.connect(self.shutdown)

    def update_controls(self):
        wide=self.tool.currentData()=='inductor_fit'
        self.target.setEnabled(not wide);self.basic.setEnabled(wide);self.spectre.setEnabled(wide)
        self.description.setText('Wideband inductor fit: oxide/substrate network, skin effect and optional distributed coil segments. Writes SPICE/Spectre, model S2P and comparison plots.' if wide else
            'Target-frequency extraction: fixed element values need not reproduce the entire band. The pi tool also reports a series-branch fit; inspect its warnings. These tools write component reports and any available plots; only the wideband inductor tool writes a netlist.')

    def browse_repository(self):
        path=QFileDialog.getExistingDirectory(self,'Select lumpedmodel repository',self.repository.text())
        if path:self.repository.setText(path)

    def start(self):
        if self.process and self.process.state()!=QProcess.NotRunning:return
        default=browse_start('output',fallback=str(Path(self.analysis.source['path']).parent) if self.analysis.source else '')
        path=QFileDialog.getExistingDirectory(self,'Choose parent for a new model-run folder',str(default))
        if not path:return
        folder=Path(path)/('lumped_'+self.tool.currentData()+'_'+datetime.now().strftime('%Y%m%d_%H%M%S_%f'))
        self.start_run(folder)

    def start_run(self,folder):
        if self.process and self.process.state()!=QProcess.NotRunning:return
        try:
            self.analysis.ensure_source()
            command,self.folder=prepare_model_run(self.analysis.network,self.analysis.source,self.analysis.specification(),
                self.repository.text(),folder,self.tool.currentData(),self.target.value()*1e9,self.basic.isChecked(),self.spectre.isChecked())
        except (ValueError,OSError,ArithmeticError) as error:
            self.log.setPlainText('Cannot prepare model: '+str(error));return
        self.log.setPlainText('Output: '+str(self.folder)+'\n');self.artifacts.clear()
        self.process=QProcess(self);self.process.setWorkingDirectory(str(self.folder))
        env=QProcessEnvironment.systemEnvironment();env.insert('MPLBACKEND','Agg');env.insert('PYTHONUNBUFFERED','1')
        for name in ('OMP_NUM_THREADS','OPENBLAS_NUM_THREADS','MKL_NUM_THREADS'):env.insert(name,'1')
        self.process.setProcessEnvironment(env);self.process.setProcessChannelMode(QProcess.MergedChannels)
        self.process.readyReadStandardOutput.connect(self.read_output)
        self.process.finished.connect(self.finished);self.process.errorOccurred.connect(self.process_error)
        self.run_button.setEnabled(False);self.stop_button.setEnabled(True)
        self.process.start(command[0],command[1:])

    def read_output(self):
        data=bytes(self.process.readAllStandardOutput()).decode('utf-8',errors='replace')
        if data:
            with (self.folder/'console.log').open('a',encoding='utf-8') as log:log.write(data)
            cursor=self.log.textCursor();cursor.movePosition(cursor.MoveOperation.End);cursor.insertText(data);self.log.setTextCursor(cursor)

    def finished(self,code,status):
        self.read_output();self.run_button.setEnabled(True);self.stop_button.setEnabled(False)
        report_path=self.folder/'run.json';report=json.loads(report_path.read_text())
        report.update(status='complete' if code==0 and status==QProcess.NormalExit else 'failed_or_stopped',exit_code=code)
        report['outputs']=[dict(name=p.name,sha256=hashlib.sha256(p.read_bytes()).hexdigest()) for p in sorted(self.folder.iterdir()) if p.is_file() and p.name!='run.json']
        report_path.write_text(json.dumps(report,indent=2)+'\n')
        self.artifacts.clear()
        for path in sorted(self.folder.iterdir()):
            if path.is_file():self.artifacts.addItem(path.name,str(path))
        self.log.appendPlainText(f'\nExit {code}. Review outputs and diagnostics in {self.folder}')

    def process_error(self,error):
        self.log.appendPlainText('Process error: '+self.process.errorString())
        if error==QProcess.FailedToStart:self.finished(-1,QProcess.CrashExit)

    def stop(self):
        if self.process and self.process.state()!=QProcess.NotRunning:self.process.kill()

    def shutdown(self):
        self.stop()
        if self.process:self.process.waitForFinished(1000)

    def view_artifact(self):
        value=self.artifacts.currentData()
        if not value:return
        path=Path(value);dialog=QDialog(self);dialog.setWindowTitle(path.name);dialog.resize(1000,750);layout=QVBoxLayout(dialog)
        if path.suffix=='.png':
            scroll=QScrollArea();label=QLabel();label.setPixmap(QPixmap(str(path)));scroll.setWidget(label);layout.addWidget(scroll)
        else:
            text=QPlainTextEdit();text.setReadOnly(True);text.setPlainText(path.read_text(errors='replace'));layout.addWidget(text)
        buttons=QDialogButtonBox(QDialogButtonBox.Close);buttons.rejected.connect(dialog.reject);layout.addWidget(buttons);dialog.exec()
