"""Explicit project initialization and safe raw-layout context switches."""
import json
from pathlib import Path
from PySide6.QtCore import QProcess
from PySide6.QtWidgets import QFileDialog,QMessageBox
try:
    from .path_config import project_directory,output_directory,browse_start,configured_path
except ImportError:
    from path_config import project_directory,output_directory,browse_start,configured_path


def ensure_idle(window):
    raw=window.file_tab.raw_input;tab=window.create_model_tab
    for process in (raw.process,tab.process):
        if process and process.state()!=QProcess.NotRunning:
            raise ValueError('Stop the current preparation/simulation before switching projects.')


def adopt_raw_layout(window,filename):
    """Keep technology/numerics; detach the previous design and its output paths."""
    source=Path(filename).expanduser().resolve()
    if not source.is_file():raise ValueError('Raw GDS file not found: '+str(source))
    ensure_idle(window)
    raw=window.file_tab.raw_input;tab=window.create_model_tab
    if not window.confirm_unsaved_script():return False
    window._stop_preserve_mode();window.hide_info_bar()
    window.user_inputs_file=None;window._project_root=str(source.parent)
    window.protected_source_model_path=None;window.backup_before_overwrite=None
    window.piece_set=None;window.current_piece=None;window.script_runs=[]
    tab._active_run=None;tab._run_queue=[];tab._piece_runner=None
    tab.refresh_runs_table()
    viewer=getattr(window,'result_viewer_window',None)
    if viewer is not None:viewer.close()
    values=window.saved_values
    for key in ('openems_boxwall','reference_plane_shift','port_wall_extension','deembedding_length'):
        values.pop(key,None)
    window._openems_port_feeds={};window._openems_legacy_feed=None
    values.update(GdsFile='',cellname='',model_basename=source.stem+'_ems')
    window.file_tab.gds_file_edit.clear()
    window.file_tab.cellname_box.clear();window.file_tab.cellname_box.addItem('(default)')
    window.ports_tab.update_port_from_import([]);window.ports_tab.load_values();window.ports_tab.save_values()
    raw.source.setText(str(source));raw._accepted_source=str(source)
    raw.cell.clear();raw.cleaned.clear();raw.prepared.clear()
    raw._suggested_output='';raw._suggested_prepared=''
    raw.suggest_output()
    kind='fdtd' if window.OpenEMSMode else 'fem'
    destination=output_directory(kind,window,str(source),str(source.parent))
    values['sim_path']=destination;tab._suggested_targetdir=destination
    tab.targetdir_edit.setText(destination);tab.modelname_edit.setText(source.stem+'_ems')
    raw.status.setText('Project changed to '+str(source.parent)+'. Output names reset; old active GDS and port definitions cleared. Technology and numerical settings retained.')
    return True


def prepare_folders(window):
    folders=[]
    for kind in ('gds','touchstone','models','fdtd','fem','output'):
        directory=output_directory(kind,window,create=True)
        if directory and directory not in folders:folders.append(directory)
    return folders


def initialize_project(window,filename):
    ensure_idle(window)
    source=Path(filename).expanduser().resolve()
    if not source.is_file():raise ValueError('Raw GDS file not found: '+str(source))
    import gdstk
    try:gdstk.gds_info(source)  # Validate before creating project artifacts.
    except (OSError,ValueError,RuntimeError) as error:raise ValueError('Cannot read Raw GDS: '+str(error)) from error
    config=source.with_suffix('.'+window.CONFIG_SUFFIX)
    if config.exists():
        # Existing project state wins; New must never overwrite a saved project.
        window.load_configuration_from_file(str(config))
        if getattr(window,'user_inputs_file',None)!=str(config):return None
        prepare_folders(window)
        return config
    if not adopt_raw_layout(window,source):return None
    if not window.save_all_tabs():return None
    folders=prepare_folders(window)
    data=dict(application=window.APP_NAME,data_format='1.0',project_root='.',saved_values=dict(window.saved_values))
    data.update(window.native_config_extra_struct())
    kind='fdtd' if window.OpenEMSMode else 'fem'
    if configured_path('directories',kind):data['solver_directory_preset']=kind
    with config.open('x',encoding='utf-8') as stream:json.dump(data,stream,indent=4)
    window.user_inputs_file=str(config);window._project_root=None
    try:
        from .setup_common import RECENT_SETTINGS_KEY
    except ImportError:
        from setup_common import RECENT_SETTINGS_KEY
    window._add_recent_file(RECENT_SETTINGS_KEY,str(config))
    window.file_tab.raw_input.status.setText('Project ready: '+str(config)+f'. Prepared {len(folders)} output folder(s) from the directory presets.')
    return config


def new_project_dialog(window):
    filename,_=QFileDialog.getOpenFileName(window,'New project from original Raw GDS',
        browse_start('project',fallback=project_directory(window)),'GDSII (*.gds *.GDS);;All files (*)')
    if not filename:return
    try:initialize_project(window,filename)
    except (ValueError,OSError,ImportError) as error:QMessageBox.warning(window,'Cannot initialize project',str(error))
