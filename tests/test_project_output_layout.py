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
