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
        assert starts[0]==str(root/'gds') and starts[2]==str(root/'projects')
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


def test_relative_presets_follow_each_project_and_keep_tool_paths_stable(configured,tmp_path,monkeypatch):
    from types import SimpleNamespace
    _,config,data=configured
    data['directories'].update(gds='./generated_gds',touchstone='./SP',models='./models',fdtd='./fdtd',fem='./fem')
    data['tools']['lumpedmodel']='./tools/lumpedmodel'
    config.write_text(json.dumps(data))
    first=tmp_path/'first';second=tmp_path/'second';first.mkdir();second.mkdir()
    windows=[]
    for root in (first,second):
        file=root/'project.simcfg';file.write_text('{}')
        windows.append(SimpleNamespace(user_inputs_file=str(file),saved_values={}))
    monkeypatch.chdir(tmp_path)  # changing cwd cannot change the resolved paths
    for window,root in zip(windows,(first,second)):
        project=paths.project_directory(window)
        assert project==str(root)
        assert paths.output_directory('gds',window)==str(root/'generated_gds')
        assert paths.output_directory('models',window)==str(root/'models')
        assert not (root/'generated_gds').exists()
        assert paths.browse_start('gds',project=project)==str(root)
    assert paths.configured_path('tools','lumpedmodel')==str(config.parent/'tools/lumpedmodel')
    created=paths.output_directory('models',windows[0],create=True)
    assert Path(created).is_dir() and not (second/'models').exists()
    # A snapshot beside generated solver code points back to the project root.
    child=first/'fdtd';child.mkdir();snapshot=child/'run.simcfg';snapshot.write_text('{"project_root":".."}')
    windows[0].user_inputs_file=str(snapshot)
    assert paths.output_directory('touchstone',windows[0])==str(first/'SP')


def test_specific_file_presets_and_relative_expansion(configured,tmp_path,monkeypatch):
    root,config,data=configured
    stack=root/'stackup'/'chosen.xml';stack.write_text('<stackup/>')
    data['directories']['stackup']=str(stack)
    data['directories']['gds']='./${GENERATED_FOLDER}'
    config.write_text(json.dumps(data));monkeypatch.setenv('GENERATED_FOLDER','generated')
    assert paths.browse_start('stackup')==str(stack)
    assert paths.configured_path('directories','gds',project=str(tmp_path))==str(tmp_path/'generated')
    assert './${GENERATED_FOLDER}' in config.read_text()


def test_collected_networks_preserve_prior_results(tmp_path):
    source=tmp_path/'solver';source.mkdir();target=tmp_path/'SP'
    network=source/'inductor.s2p';network.write_text('original network')
    first=paths.collect_touchstone([network],target)
    assert first==[str(target/network.name)]
    assert paths.collect_touchstone([network],target)==first
    network.write_text('new network')
    second=paths.collect_touchstone([network],target)
    assert second!=first and Path(first[0]).read_text()=='original network'
    assert Path(second[0]).read_text()=='new network'
    assert paths.collect_touchstone([network],target)==second
    assert len(list(target.iterdir()))==2
