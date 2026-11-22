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
    assert raw.preview_buttons['cleaned'].isEnabled()
    before=dict(window.saved_values)
    raw.preview('cleaned')
    assert 'Previewing' in raw.status.text(),raw.status.text()
    assert window.saved_values==before and files.gds_file_edit.text()==previous
    assert raw._preview_windows[-1].canvas.scene().items()
    raw._preview_windows[-1].close()
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
    assert raw.prepared.text()==files.gds_file_edit.text()
    assert raw.preview_buttons['prepared'].isEnabled()
    before=dict(window.saved_values)
    raw.preview('prepared')
    assert 'Previewing' in raw.status.text(),raw.status.text()
    assert window.saved_values==before
    raw._preview_windows[-1].close()
    files.set_gds_file(str(source))
    raw.use_prepared()
    assert files.gds_file_edit.text()==raw.prepared.text()
    assert source.read_bytes()==original and files.input_scroll.widgetResizable()
    config=window.native_config_extra_struct()
    assert config['raw_input']['source']==str(source)
    raw.source.clear();window.apply_analysis_config_data(config)
    assert raw.source.text()==str(source) and raw.drop.text()=='22'
    assert raw.prepared.text()==str(source.with_name('cadence_ems.gds'))
    previous=files.gds_file_edit.text()
    manifest_path=source.with_name('cadence_ems.ports.json')
    manifest['output_sha256']='stale'
    manifest_path.write_text(json.dumps(manifest))
    raw.use_prepared()
    assert 'Cannot select' in raw.status.text() and files.gds_file_edit.text()==previous


def test_stackup_precedes_preprocessing_and_active_input(window):
    files=window.file_tab
    assert files.main_layout.indexOf(files.XML_group)<files.main_layout.indexOf(files.raw_input)<files.main_layout.indexOf(files.gds_group)
    assert files.prepare_ports_btn.isHidden()


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


def test_raw_prompt_is_not_saved_as_a_filename(window):
    raw=window.file_tab.raw_input
    assert raw.source.placeholderText()=='Please choose a file ===>'
    assert raw.source.text()=='' and raw.state()['source']==''
    assert not raw.preview_buttons['raw'].isEnabled()
    assert 'raw_input' not in window.native_config_extra_struct()


def test_preview_names_unmapped_stackup_layers_from_stream_map(window,raw_layout):
    import gdstk
    from PySide6.QtWidgets import QLabel
    source,options=raw_layout;raw=window.file_tab.raw_input
    window.file_tab.set_XML_file(options['stackup'])
    raw.source.setText(str(source));raw.mapfile.setText(options['mapfile'])
    lib=gdstk.read_gds(source)
    cell=next(c for c in lib.cells if c.name=='CADENCE_TOP')
    cell.add(gdstk.rectangle((0,40),(2,42),layer=998));lib.write_gds(source)
    with Path(options['mapfile']).open('a') as stream:
        stream.write('\nMetal1 pin 998 0\nMetal1 pin 999 0\n')
    previous=dict(window.saved_values)
    raw.preview('raw')
    assert 'Previewing' in raw.status.text(),raw.status.text()
    view=raw._preview_windows[-1]
    labels=[label.text() for label in view.findChildren(QLabel)]
    assert 'Metal1 [8]' in labels  # Physical stackup name is retained.
    assert 'Metal1 [998]' in labels and 'Metal1 [999]' in labels
    assert view._layer_layernum_by_name['Metal1']==8
    assert view._layer_layernum_by_name['Metal1 [998]']==998
    assert view._layer_layernum_by_name['Metal1 [999]']==999
    assert window.saved_values==previous
    # This preview is a snapshot; editing the map doesn't relabel an open view.
    raw.mapfile.clear();view.refresh()
    assert 'Metal1 [999]' in [label.text() for label in view.findChildren(QLabel)]
    view.close()
