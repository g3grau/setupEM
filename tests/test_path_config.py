import json
from pathlib import Path
import pytest
from setupEM import path_config as paths
from setupEM.lumped_models import default_repository
from setupEM.broadband_model import default_engine_python


@pytest.fixture
def configured(tmp_path,monkeypatch):
    root=tmp_path/'server';root.mkdir()
    for name in ('gds','stackup','sp','projects','maps','output','lumpedmodel'):(root/name).mkdir()
    config=tmp_path/'paths.json'
    data=dict(schema='setupEM.paths.v1',directories=dict(gds='${EMS_ROOT}/gds',stackup='${EMS_ROOT}/stackup',touchstone='${EMS_ROOT}/sp',
        project='${EMS_ROOT}/projects',stream_map='${EMS_ROOT}/maps',output='${EMS_ROOT}/output'),
        tools=dict(lumpedmodel='${EMS_ROOT}/lumpedmodel',broadband_python='${EMS_ROOT}/fit/bin/python'))
    config.write_text(json.dumps(data));monkeypatch.setenv('SETUPEM_PATH_CONFIG',str(config));monkeypatch.setenv('EMS_ROOT',str(root))
    monkeypatch.delenv('EMS_BROADBAND_PYTHON',raising=False)
    return root,config,data


def test_portable_paths_defaults_and_explicit_selection_priority(configured,tmp_path):
    root,config,data=configured
    assert paths.browse_start('gds')==str(root/'gds')
    assert paths.browse_start('touchstone')==str(root/'sp')
    assert default_repository()==str(root/'lumpedmodel')
    assert default_engine_python()==str(root/'fit/bin/python')
    current=tmp_path/'current.s2p';current.write_text('source')
    assert paths.browse_start('touchstone',str(current))==str(current)
    assert paths.browse_start('gds','Please choose a file ===>')==str(root/'gds')
    assert paths.browse_start('output',fallback=str(tmp_path))==str(root/'output')


def test_environment_expansion_is_live_and_source_stays_portable(configured,tmp_path,monkeypatch):
    root,config,data=configured
    assert default_repository()==str(root/'lumpedmodel')
    monkeypatch.setenv('EMS_ROOT',str(tmp_path/'different'))
    assert default_repository()==str(tmp_path/'different/lumpedmodel')
    assert '${EMS_ROOT}' in config.read_text()
    monkeypatch.setenv('EMS_BROADBAND_PYTHON','/explicit/python')
    assert default_engine_python()=='/explicit/python'


def test_import_validates_and_preserves_previous_defaults(tmp_path,monkeypatch):
    monkeypatch.delenv('SETUPEM_PATH_CONFIG',raising=False);monkeypatch.setenv('XDG_CONFIG_HOME',str(tmp_path/'config'))
    source=tmp_path/'snippet.json';source.write_text(json.dumps(dict(tools=dict(lumpedmodel='~/cadtools/lumpedmodel'))))
    destination,backup=paths.install_config(source)
    assert destination==tmp_path/'config/setupEM/paths.json' and backup is None
    first=destination.read_bytes();destination2,backup=paths.install_config(source)
    assert destination2==destination and backup.read_bytes()==first
    source.write_text('{"tools":{"lumpedmodel":123}}')
    with pytest.raises(ValueError):paths.install_config(source)
    assert destination.read_bytes()==first
    source.write_text('{"executable_python_code":"print(1)"}')
    with pytest.raises(ValueError):paths.install_config(source)


def test_invalid_active_config_warns_and_falls_back(configured):
    root,config,_=configured;config.write_text('{bad')
    with pytest.warns(RuntimeWarning,match='Cannot use setupEM path defaults'):
        assert paths.browse_start('gds',fallback=str(root))==str(root)


def test_gui_dialog_defaults_and_tool_paths(configured,monkeypatch):
    from PySide6.QtWidgets import QApplication,QFileDialog
    from setupEM import setupEM as module
    from setupEM import setup_common as common
    app=QApplication.instance() or QApplication([])
    monkeypatch.setattr(module,'get_preference',lambda app,key,default=None:default)
    monkeypatch.setattr(common,'get_preference',lambda app,key,default=None:default)
    root,_,_=configured;module.saved_values.clear();window=module.MainWindow()
    try:
        assert window.postprocessing_tab.lumped_tab.repository.text()==str(root/'lumpedmodel')
        assert window.broadband_tab.engine_python.text()==str(root/'fit/bin/python')
        window.postprocessing_tab.lumped_tab.basic.setChecked(True)
        window.postprocessing_tab.save_values()
        assert 'repository' not in window.postprocessing_settings['lumped']
        starts=[]
        monkeypatch.setattr(QFileDialog,'getOpenFileName',lambda *args,**kwargs:(starts.append(args[2]) or '', ''))
        window.file_tab.browse_gds_file();window.file_tab.browse_XML_file();window.file_tab.raw_input.browse_source()
        window.file_tab.raw_input.browse_map();window.postprocessing_tab.browse();window.broadband_tab.browse()
        assert starts[0]==str(root/'gds') and starts[2]==str(root/'gds')
        assert starts[3]==str(root/'maps') and starts[4:]==[str(root/'sp')]*2
        # Explicit XML preference may precede the snippet; unset preferences use it.
        assert starts[1]==str(root/'stackup')
        assert window._open_dialog_folder()==str(root/'projects')
    finally:
        window._script_dirty=False;window.close();module.saved_values.clear()


def test_preferences_import_button_installs_validated_snippet(configured,tmp_path,monkeypatch):
    from PySide6.QtWidgets import QApplication,QFileDialog,QMessageBox
    from setupEM import setupEM as module
    app=QApplication.instance() or QApplication([])
    monkeypatch.setattr(module,'get_preference',lambda app,key,default=None:default)
    _,config,_=configured;candidate=tmp_path/'import.json'
    candidate.write_text(json.dumps(dict(tools=dict(lumpedmodel='/server/lumpedmodel'))))
    monkeypatch.setattr(QFileDialog,'getOpenFileName',lambda *args,**kwargs:(str(candidate),''))
    messages=[];errors=[]
    monkeypatch.setattr(QMessageBox,'information',lambda *args:messages.append(args[-1]))
    monkeypatch.setattr(QMessageBox,'warning',lambda *args:errors.append(args[-1]))
    module.saved_values.clear();window=module.MainWindow();dialog=module.PreferencesDialog(window)
    try:
        dialog.import_paths_button.click()
        assert messages and not errors and default_repository()=='/server/lumpedmodel'
        assert list(config.parent.glob(config.name+'.backup-*'))
        previous=config.read_bytes();candidate.write_text('{"tools":{"lumpedmodel":false}}')
        dialog.import_paths_button.click()
        assert errors and config.read_bytes()==previous
    finally:
        dialog.reject();window._script_dirty=False;window.close();module.saved_values.clear()
