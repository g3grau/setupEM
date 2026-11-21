import json
import time
from pathlib import Path
import pytest
from PySide6.QtWidgets import QApplication,QMessageBox
from setupEM import setupEM as module
from setupEM.prepare_ports_dialog import PreparePortsDialog
from test_raw_preparation import raw_layout


@pytest.fixture
def window(monkeypatch):
    app=QApplication.instance() or QApplication([])
    monkeypatch.setattr(module,'get_preference',lambda app,key,default=None:default)
    module.saved_values.clear();window=module.MainWindow()
    yield window
    window.file_tab.raw_input.shutdown();window._script_dirty=False;window.close();module.saved_values.clear()


def test_raw_to_cleaned_to_reviewed_ports_updates_only_final_simulation_input(window,raw_layout,monkeypatch):
    source,options=raw_layout;original=source.read_bytes();files=window.file_tab;raw=files.raw_input
    files.set_XML_file(options['stackup'])
    raw.source.setText(str(source));raw.mapfile.setText(options['mapfile']);raw.cleaned.setText(options['output']);raw.drop.setText('22')
    previous=files.gds_file_edit.text();raw.run()
    deadline=time.monotonic()+30
    while not raw.run_button.isEnabled() and time.monotonic()<deadline:
        QApplication.processEvents();time.sleep(.01)
    assert raw.run_button.isEnabled() and 'Cleaned GDS ready' in raw.status.text(),raw.log.toPlainText()
    assert files.gds_file_edit.text()==previous
    assert Path(options['output']).with_suffix('.prep.log').exists()
    assert not list(source.parent.glob('.setupem_raw_job_*'))
    errors=[];monkeypatch.setattr(QMessageBox,'warning',lambda *args:errors.append(args[-1]))
    def review(dialog):
        dialog.scan();assert dialog.table.rowCount()==2
        dialog.generate();return dialog.result()
    monkeypatch.setattr(PreparePortsDialog,'exec',review)
    raw.prepare_ports()
    assert not errors
    assert files.gds_file_edit.text()==str(source.with_name('cadence_ems.gds'))
    assert window.saved_values['cellname']=='CADENCE_TOP'
    assert window.saved_values['purpose']==[0]  # pins/filler purposes do not leak from a prior '*' filter
    assert 'Prepared _ems.gds is now selected' in raw.status.text()
    manifest=json.loads(source.with_name('cadence_ems.ports.json').read_text())
    assert [p['name'] for p in manifest['ports']]==['IN','OUT']
    assert manifest['raw_preparation']['source']['path']==str(source)
    assert source.read_bytes()==original and files.input_scroll.widgetResizable()
    config=window.native_config_extra_struct()
    assert config['raw_input']['source']==str(source)
    raw.source.clear();window.apply_analysis_config_data(config)
    assert raw.source.text()==str(source) and raw.drop.text()=='22'


def test_unverified_cleaned_file_never_replaces_simulation_input(window,tmp_path):
    raw=window.file_tab.raw_input;previous=window.file_tab.gds_file_edit.text()
    raw.source.setText(str(tmp_path/'missing.gds'));raw.prepare_ports()
    assert 'Cannot prepare ports' in raw.status.text()
    assert window.file_tab.gds_file_edit.text()==previous
    assert 'raw_input' in window.native_config_extra_struct()


def test_unused_raw_section_does_not_add_settings_to_existing_models(window):
    assert 'raw_input' not in window.native_config_extra_struct()


def test_failed_worker_keeps_simulation_input_and_cleans_owned_job_directory(window,tmp_path):
    raw=window.file_tab.raw_input;previous=window.file_tab.gds_file_edit.text()
    source=tmp_path/'invalid.gds';source.write_text('not a GDS file')
    stackup=Path(__file__).parents[1]/'src/setupEM/data/SG13G2_FEM_200um.xml'
    window.file_tab.XML_file_edit.setText(str(stackup))
    raw.source.setText(str(source));raw.cleaned.setText(str(tmp_path/'cleaned.gds'));raw.run()
    deadline=time.monotonic()+30
    while not raw.run_button.isEnabled() and time.monotonic()<deadline:
        QApplication.processEvents();time.sleep(.01)
    assert raw.run_button.isEnabled() and 'failed or stopped' in raw.status.text()
    assert window.file_tab.gds_file_edit.text()==previous and not (tmp_path/'cleaned.gds').exists()
    assert not list(tmp_path.glob('.setupem_raw_job_*'))
