"""Replacing generated artifacts preserves inputs and the previous good generation."""
from pathlib import Path
import pytest
from setupEM.generated_outputs import check_outputs,publish_outputs
from setupEM.generated_output_dialog import choose_output
from setupEM import generated_outputs as outputs
from setupEM.raw_preparation import preprocess,verified_report
from setupEM import pin_preparation as pins
from test_raw_preparation import raw_layout
from test_raw_input import window


def test_successful_raw_replacement_and_failure_preserve_input_and_previous_outputs(raw_layout):
    source,options=raw_layout;original=source.read_bytes()
    first=preprocess(options);path=Path(options['output'])
    with pytest.raises(ValueError,match='already exists'):preprocess(options)
    changed=dict(options,do_floating=False)
    second=preprocess(changed,overwrite=True)
    assert second['simplified_drawing_polygons']>first['simplified_drawing_polygons']
    assert verified_report(changed)==second and source.read_bytes()==original
    previous={p:p.read_bytes() for p in (path,path.with_suffix('.prep.json'))}
    with pytest.raises(ValueError):preprocess(dict(changed,drop_datatypes=[2]),overwrite=True)
    assert all(p.read_bytes()==data for p,data in previous.items())
    with pytest.raises(ValueError,match='input'):preprocess(dict(options,output=str(source)),overwrite=True)
    assert source.read_bytes()==original


def test_publication_rolls_back_a_failed_sidecar_replacement(tmp_path,monkeypatch):
    gds=tmp_path/'cleaned.gds';report=tmp_path/'cleaned.prep.json'
    gds.write_bytes(b'previous GDS');report.write_bytes(b'previous report')
    staged=tmp_path/'staged.gds';staged_report=tmp_path/'staged.json'
    staged.write_bytes(b'new GDS');staged_report.write_bytes(b'new report')
    state=check_outputs((gds,report),overwrite=True)
    actual=outputs.os.replace
    def fail(source,target):
        if Path(source)==staged_report:raise OSError('simulated publication failure')
        return actual(source,target)
    monkeypatch.setattr(outputs.os,'replace',fail)
    with pytest.raises(OSError,match='publication failure'):
        publish_outputs(((staged,gds),(staged_report,report)),overwrite=True,expected=state)
    assert gds.read_bytes()==b'previous GDS' and report.read_bytes()==b'previous report'
    assert not list(tmp_path.glob('.setupem_replace_*'))


def test_changed_output_and_input_aliases_are_never_replaced(tmp_path):
    original=tmp_path/'original.gds';original.write_bytes(b'original')
    alias=tmp_path/'alias.gds';outputs.os.link(original,alias)
    with pytest.raises(ValueError,match='input'):check_outputs((alias,),(original,),overwrite=True)
    target=tmp_path/'output.gds';target.write_bytes(b'previous')
    state=check_outputs((target,),overwrite=True)
    stage=tmp_path/'staged';stage.write_bytes(b'generated')
    target.write_bytes(b'changed by someone else')
    with pytest.raises(ValueError,match='changed during preparation'):
        publish_outputs(((stage,target),),overwrite=True,expected=state)
    assert target.read_bytes()==b'changed by someone else' and original.read_bytes()==b'original'


def click_dialog_choice(monkeypatch,choice):
    from PySide6.QtWidgets import QMessageBox
    def execute(box):
        for button in box.buttons():
            if (choice=='cancel' and box.standardButton(button)==QMessageBox.Cancel) or button.text().startswith(choice):
                button.click();return 0
        raise AssertionError('Expected dialog choice missing: '+choice)
    monkeypatch.setattr(QMessageBox,'exec',execute)


def test_output_dialog_supports_cancel_alternate_filename_and_saved_preference(window,tmp_path,monkeypatch):
    from PySide6.QtWidgets import QFileDialog
    from setupEM import setup_common
    target=tmp_path/'cleaned.gds';target.write_bytes(b'previous')
    monkeypatch.setattr(setup_common,'get_preference_bool',lambda *a:False)
    click_dialog_choice(monkeypatch,'cancel')
    assert choose_output(window,'setupEM',target)==(None,False)
    click_dialog_choice(monkeypatch,'Choose another')
    alternate=tmp_path/'different.gds'
    monkeypatch.setattr(QFileDialog,'getSaveFileName',lambda *a,**k:(str(alternate),''))
    assert choose_output(window,'setupEM',target)==(str(alternate),False)
    click_dialog_choice(monkeypatch,'Replace')
    assert choose_output(window,'setupEM',target)==(str(target),True)
    monkeypatch.setattr(setup_common,'get_preference_bool',lambda *a:True)
    monkeypatch.setattr(__import__('PySide6.QtWidgets',fromlist=['QMessageBox']).QMessageBox,'exec',lambda *a:pytest.fail('Automatic policy must not prompt'))
    assert choose_output(window,'setupEM',target)==(str(target),True)
    with pytest.raises(ValueError,match='input'):choose_output(window,'setupEM',target,inputs=(target,))
    assert target.read_bytes()==b'previous'


def test_port_preparation_can_replace_generated_manifest_and_never_its_input(raw_layout):
    source,options=raw_layout;original=source.read_bytes();rows=pins.read_map(Path(options['mapfile']))
    output=source.with_name('ports.gds')
    pins.write(source,output,rows,[(1,'OLD')],cellname='CADENCE_TOP')
    result=pins.write(source,output,rows,[(1,'NEW')],cellname='CADENCE_TOP',overwrite=True)
    assert pins.read_prepared_manifest(output)==result and pins.names_for_gds(output)=={240:'NEW'}
    previous=output.read_bytes();manifest=output.with_suffix('.ports.json').read_bytes()
    with pytest.raises(ValueError):pins.write(source,output,rows,[(999,'INVALID')],cellname='CADENCE_TOP',overwrite=True)
    assert output.read_bytes()==previous and output.with_suffix('.ports.json').read_bytes()==manifest
    with pytest.raises(ValueError,match='input'):pins.write(source,source,rows,[(1,'NEW')],cellname='CADENCE_TOP',overwrite=True)
    assert source.read_bytes()==original


def test_raw_gui_replaces_bundle_and_log_after_worker_success(window,raw_layout,monkeypatch):
    import time
    from PySide6.QtWidgets import QApplication
    from setupEM import setup_common
    source,options=raw_layout;raw=window.file_tab.raw_input
    window.file_tab.set_XML_file(options['stackup']);raw.source.setText(str(source))
    raw.mapfile.setText(options['mapfile']);raw.cleaned.setText(options['output']);raw.drop.setText('22')
    preprocess(raw.options());log=Path(options['output']).with_suffix('.prep.log');log.write_text('previous log')
    monkeypatch.setattr(setup_common,'get_preference_bool',lambda *a:True)
    raw.run();deadline=time.monotonic()+30
    while not raw.run_button.isEnabled() and time.monotonic()<deadline:
        QApplication.processEvents();time.sleep(.01)
    assert 'Cleaned GDS ready' in raw.status.text(),raw.log.toPlainText()
    assert 'previous log' not in log.read_text() and 'Cleaned GDS:' in log.read_text()
    assert verified_report(raw.options())['output']['path']==options['output']
    assert not list(source.parent.glob('.setupem_replace_*'))


def test_overwrite_preference_saves_and_resets_to_confirmation(window,monkeypatch):
    from setupEM import setupEM as module
    saved={}
    monkeypatch.setattr(module,'get_preference_bool',lambda app,key,default=False:default)
    monkeypatch.setattr(module,'set_preference',lambda app,key,value:saved.__setitem__(key,value))
    dialog=module.PreferencesDialog(window)
    assert not dialog.overwrite_generated_gds_checkbox.isChecked()
    dialog.overwrite_generated_gds_checkbox.setChecked(True)
    dialog.accept()
    assert saved['overwrite_generated_gds'] is True
    monkeypatch.setattr(module.QMessageBox,'question',lambda *a,**k:module.QMessageBox.Yes)
    monkeypatch.setattr(module,'clear_preferences',lambda *a:None)
    dialog._reset_to_defaults()
    assert not dialog.overwrite_generated_gds_checkbox.isChecked()
    dialog.deleteLater()
