"""Project-relative defaults route real preprocessing outputs and config snapshots."""
import json
import time
from pathlib import Path
from PySide6.QtWidgets import QApplication,QMessageBox
from setupEM import setupEM as module,path_config
from setupEM.prepare_ports_dialog import PreparePortsDialog
from test_raw_preparation import raw_layout


def test_project_keeps_original_and_config_beside_separate_generated_outputs(tmp_path,raw_layout,monkeypatch):
    app=QApplication.instance() or QApplication([])
    source,options=raw_layout
    config=tmp_path/'machine-paths.json'
    config.write_text(json.dumps(dict(directories=dict(project=str(source.parent),gds='./generated_gds',
        touchstone='./SP',models='./models',fdtd='./fdtd',fem='./fem',stream_map=options['mapfile']))))
    monkeypatch.setenv('SETUPEM_PATH_CONFIG',str(config))
    monkeypatch.setattr(module,'get_preference',lambda app,key,default=None:default)
    module.saved_values.clear();window=module.MainWindow()
    try:
        files=window.file_tab;raw=files.raw_input
        files.set_XML_file(options['stackup']);raw.source.setText(str(source));raw.mapfile.setText(options['mapfile'])
        raw.suggest_output();raw.drop.setText('22')
        assert raw.cleaned.text()==str(source.parent/'generated_gds/cadence_cleaned.gds')
        assert raw.prepared.text()==str(source.parent/'generated_gds/cadence_ems.gds')
        raw.run();deadline=time.monotonic()+30
        while not raw.run_button.isEnabled() and time.monotonic()<deadline:
            app.processEvents();time.sleep(.01)
        assert 'Cleaned GDS ready' in raw.status.text(),raw.log.toPlainText()
        def review(dialog):
            dialog.scan();dialog.generate();return dialog.result()
        monkeypatch.setattr(PreparePortsDialog,'exec',review)
        errors=[];monkeypatch.setattr(QMessageBox,'warning',lambda *args:errors.append(args[-1]))
        raw.prepare_ports();assert not errors
        assert Path(files.gds_file_edit.text())==source.parent/'generated_gds/cadence_ems.gds'
        window.create_model_tab.load_values()
        assert window.create_model_tab.targetdir_edit.text()==str(source.parent/'fem')
        window.create_model_tab.save_values()
        script=source.parent/'fem/cadence_ems.py'
        window.create_model_tab.write_model_code(str(script),'# generated model\n')
        snapshot=window.write_model_config(str(script))
        assert json.loads(Path(snapshot).read_text())['project_root']=='..'
        project=source.parent/'cadence_ems.simcfg'
        data=json.loads(project.read_text())
        assert data['model_script']=='fem/cadence_ems.py' and data['project_root']=='.'
        assert data['solver_directory_preset']=='fem'
        assert 'written_with' not in data
        assert path_config.project_directory(window)==str(source.parent)
        assert path_config.output_directory('models',window)==str(source.parent/'models')
        # Explicit solver target selections continue to win.
        custom=source.parent/'custom-solver';window.saved_values['sim_path']=str(custom)
        window.create_model_tab.load_values()
        assert window.create_model_tab.targetdir_edit.text()==str(custom)
        window.user_inputs_file=str(snapshot)
        assert path_config.project_directory(window)==str(source.parent)
        # A server copy resolves automatic destinations at its new project root.
        relocated=tmp_path/'relocated';relocated.mkdir()
        generated=relocated/'generated_gds';generated.mkdir()
        copied=generated/'cadence_ems.gds';copied.write_bytes(Path(files.gds_file_edit.text()).read_bytes())
        data['saved_values']['GdsFile']='/unavailable/old/project/cadence_ems.gds'
        moved_config=relocated/'cadence_ems.simcfg';moved_config.write_text(json.dumps(data))
        window.load_configuration_from_file(str(moved_config),ask_unsaved=False,quiet=True,script_choice='config')
        assert window.saved_values['sim_path']==str(relocated/'fem')
        assert window.saved_values['GdsFile']==str(copied)
        assert raw.cleaned.text()==str(generated/'cadence_cleaned.gds')
        assert path_config.output_directory('models',window)==str(relocated/'models')
        # A different project's explicit target may equal the previous default.
        # That coincidence must not mark the explicit target as automatic.
        third=tmp_path/'third';third.mkdir()
        explicit=json.loads(moved_config.read_text());explicit.pop('solver_directory_preset')
        explicit['saved_values'].update(GdsFile=str(copied),sim_path=str(relocated/'fem'))
        explicit_config=third/'explicit.simcfg';explicit_config.write_text(json.dumps(explicit))
        window.load_configuration_from_file(str(explicit_config),ask_unsaved=False,quiet=True,script_choice='config')
        assert window.create_model_tab.targetdir_edit.text()==str(relocated/'fem')
    finally:
        raw.shutdown();window._script_dirty=False;window.close();module.saved_values.clear()


def test_solver_network_collection_excludes_standards_and_iteration_snapshots(tmp_path,monkeypatch):
    app=QApplication.instance() or QApplication([])
    config=tmp_path/'paths.json'
    config.write_text(json.dumps(dict(directories=dict(project=str(tmp_path),touchstone='./SP'))))
    monkeypatch.setenv('SETUPEM_PATH_CONFIG',str(config))
    monkeypatch.setattr(module,'get_preference',lambda app,key,default=None:default)
    module.saved_values.clear();window=module.MainWindow()
    try:
        tab=window.create_model_tab;window.OpenEMSMode=True;window.PalaceMode=False
        root=tmp_path/'fdtd';tab.targetdir_edit.setText(str(root))
        window.saved_values.update(sim_path=str(root),model_basename='coil')
        data=root/'output/coil_data';data.mkdir(parents=True)
        raw=data/'coil.s2p';raw.write_text('raw network')
        (data/'coil_calibrated.s2p').write_text('calibrated network')
        for folder in ('standards/cal_xmax_L','iteration1'):
            child=data/folder;child.mkdir(parents=True)
            (child/'excluded.s2p').write_text('internal calibration / AMR')
        tab._publish_project_networks()
        assert sorted(p.name for p in (tmp_path/'SP').iterdir())==['coil.s2p','coil_calibrated.s2p']
        assert raw.read_text()=='raw network'
    finally:
        window._script_dirty=False;window.close();module.saved_values.clear()


def test_new_project_and_raw_switch_rebase_paths_without_touching_previous_project(tmp_path,raw_layout,monkeypatch):
    from setupEM.project_workflow import initialize_project
    app=QApplication.instance() or QApplication([])
    source,options=raw_layout
    presets=tmp_path/'paths.json'
    presets.write_text(json.dumps(dict(directories=dict(project=str(source.parent),gds='./generated_gds',
        fdtd='./fdtd',fem='./fem',touchstone='./SP',models='./models',output='./plots'))))
    monkeypatch.setenv('SETUPEM_PATH_CONFIG',str(presets))
    monkeypatch.setattr(module,'get_preference',lambda app,key,default=None:default)
    module.saved_values.clear();w=module.MainWindow()
    try:
        w.setOpenEMSMode();w.file_tab.set_XML_file(options['stackup'])
        w.frequencies_tab.stop_edit.setText('17')
        project=initialize_project(w,source)
        assert project==source.with_suffix('.simcfg')
        assert w.new_project_action.text().startswith('New Project')
        assert 'Open Project' in w.load_settings_action.text()
        for name in ('generated_gds','fdtd','fem','SP','models','plots'):assert (source.parent/name).is_dir()
        assert w.create_model_tab.targetdir_edit.text()==str(source.parent/'fdtd')
        original_config=project.read_bytes()
        sentinel=source.parent/'fdtd/completed.s2p';sentinel.write_text('keep this completed run')
        w.file_tab.gds_file_edit.setText(str(source));w.saved_values['GdsFile']=str(source)
        w.ports_tab.update_port_from_import([dict(portnumber=1,source_layernum=241,from_layername='Metal1',to_layername='TopMetal2',direction='Z')])
        second=tmp_path/'second';second.mkdir();next_source=second/'new_coil.gds';next_source.write_bytes(source.read_bytes())
        raw=w.file_tab.raw_input;raw.source.setText(str(next_source));raw.suggest_output()
        assert path_config.project_directory(w)==str(second)
        assert raw.cleaned.text()==str(second/'generated_gds/new_coil_cleaned.gds')
        assert raw.prepared.text()==str(second/'generated_gds/new_coil_ems.gds')
        assert w.create_model_tab.targetdir_edit.text()==str(second/'fdtd')
        assert w.create_model_tab.modelname_edit.text()=='new_coil_ems'
        assert not w.saved_values['GdsFile'] and not module.simulation_ports.ports
        assert w.file_tab.XML_file_edit.text()==options['stackup'] and w.frequencies_tab.stop_edit.text()=='17'
        assert project.read_bytes()==original_config and sentinel.read_text()=='keep this completed run'
        assert w.user_inputs_file is None
        new_config=initialize_project(w,next_source)
        assert new_config==second/'new_coil.simcfg' and new_config.is_file()
        assert json.loads(new_config.read_text())['raw_input']['source']==str(next_source)
        # Reusing New on an existing project opens it; it never replaces its config.
        snapshot=new_config.read_bytes();load=w.load_configuration_from_file
        monkeypatch.setattr(w,'load_configuration_from_file',lambda filename:load(filename,quiet=True,script_choice='config'))
        w.frequencies_tab.stop_edit.setText('29')
        assert initialize_project(w,next_source)==new_config
        assert new_config.read_bytes()==snapshot and float(w.frequencies_tab.stop_edit.text())==17
    finally:
        w.file_tab.raw_input.shutdown();w._script_dirty=False;w.close();module.saved_values.clear()


def test_raw_switch_is_rejected_while_a_job_runs_or_script_changes_are_cancelled(tmp_path,raw_layout,monkeypatch):
    from types import SimpleNamespace
    from PySide6.QtCore import QProcess
    app=QApplication.instance() or QApplication([])
    source,options=raw_layout
    monkeypatch.setattr(module,'get_preference',lambda app,key,default=None:default)
    module.saved_values.clear();w=module.MainWindow()
    try:
        w.file_tab.set_XML_file(options['stackup']);raw=w.file_tab.raw_input
        raw.source.setText(str(source));raw.suggest_output()
        previous=(raw.cleaned.text(),raw.prepared.text(),w.create_model_tab.targetdir_edit.text())
        next_source=tmp_path/'next.gds';next_source.write_bytes(source.read_bytes())
        raw.process=SimpleNamespace(state=lambda:QProcess.Running)
        raw.source.setText(str(next_source));raw.suggest_output()
        assert raw.source.text()==str(source) and 'Stop the current' in raw.status.text()
        assert (raw.cleaned.text(),raw.prepared.text(),w.create_model_tab.targetdir_edit.text())==previous
        raw.process=None
        monkeypatch.setattr(w,'confirm_unsaved_script',lambda:False)
        raw.source.setText(str(next_source));raw.suggest_output()
        assert raw.source.text()==str(source)
        assert (raw.cleaned.text(),raw.prepared.text(),w.create_model_tab.targetdir_edit.text())==previous
    finally:
        raw.process=None;w._script_dirty=False
        monkeypatch.setattr(w,'confirm_unsaved_script',lambda:True)
        w.close();module.saved_values.clear()


def test_project_menu_actions_initialize_and_restore_output_folders(tmp_path,raw_layout,monkeypatch):
    from PySide6.QtWidgets import QFileDialog
    app=QApplication.instance() or QApplication([])
    source,options=raw_layout
    presets=tmp_path/'menu-paths.json'
    presets.write_text(json.dumps(dict(directories=dict(gds='./generated_gds',fdtd='./fdtd',fem='./fem',touchstone='./SP',models='./models',output='./plots'))))
    monkeypatch.setenv('SETUPEM_PATH_CONFIG',str(presets))
    monkeypatch.setattr(module,'get_preference',lambda app,key,default=None:default)
    monkeypatch.setattr(QMessageBox,'information',lambda *args:None)
    module.saved_values.clear();w=module.MainWindow()
    try:
        w.file_tab.set_XML_file(options['stackup'])
        monkeypatch.setattr(QFileDialog,'getOpenFileName',lambda *a,**k:(str(source),''))
        w.new_project_action.trigger()
        project=source.with_suffix('.simcfg')
        assert project.exists() and w.user_inputs_file==str(project)
        sp=source.parent/'SP';sp.rmdir()
        monkeypatch.setattr(QFileDialog,'getOpenFileName',lambda *a,**k:(str(project),''))
        w.load_settings_action.trigger()
        assert sp.is_dir() and path_config.project_directory(w)==str(source.parent)
    finally:
        w.file_tab.raw_input.shutdown();w._script_dirty=False;w.close();module.saved_values.clear()
