"""Runtime controls must reach launchers without changing solver defaults."""
import os
import sys
import subprocess
from pathlib import Path

import pytest

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from setupEM.execution_settings import configure_palace_run_script, palace_execution_block, palace_script_lines
from setupEM.openems_writer import openems_script_text
from setupEM.script_writer import ports_from_struct, em_script_text


@pytest.mark.parametrize('value', [None, 0])
def test_openems_automatic_omits_thread_override(value):
    text = openems_script_text({'fstop':10, 'numThreads':value}, ports_from_struct([]))
    assert "settings['numThreads']" not in text
    assert 'numThreads=-1' not in text


def test_openems_fixed_thread_count():
    text = openems_script_text({'fstop':10, 'numThreads':12}, ports_from_struct([]))
    assert "settings['numThreads'] = 12" in text
    with pytest.raises(ValueError):
        openems_script_text({'numThreads':-1}, ports_from_struct([]))


def test_launcher_update_preserves_commands_and_clears_stale_overrides(tmp_path):
    path = tmp_path/'run_sim'
    original = '#!/usr/bin/env bash\n# existing calibration/custom commands\nprintf "%s %s %s" "${PALACE_NP:-unset}" "${OMP_NUM_THREADS:-unset}" "${OPENBLAS_NUM_THREADS:-unset}"\n'
    path.write_text(original)
    values = dict(palace_mpi_processes=32, palace_omp_threads=1, palace_blas_threads=1)
    configure_palace_run_script(path, values)
    configure_palace_run_script(path, values)
    assert path.read_text().count('# BEGIN setupEM') == 1
    env = {'PATH':os.environ['PATH']}
    assert subprocess.check_output(['bash',str(path)],env=env,text=True) == '32 1 1'
    configure_palace_run_script(path, dict(palace_mpi_processes=16))
    assert subprocess.check_output(['bash',str(path)],env=env,text=True) == '16 unset unset'
    configure_palace_run_script(path, {})
    assert path.read_text() == original


def test_portable_export_uses_selected_values_and_can_be_imported(tmp_path):
    from setupEM.script_model import ScriptModel
    values = dict(palace_mpi_processes=32, palace_omp_threads=2)
    text = em_script_text(values, ports_from_struct([]), False)
    assert "settings['palace_mpi_processes'] = 32" in text
    compile(text,'export.py','exec')
    assert ScriptModel(text).site('palace_omp_threads').value == 2
    path = tmp_path/'run_sim';path.write_text('#!/bin/bash\nrun_palace config.json\n')
    # Simulate model creation, without importing or launching Palace.
    exec('\n'.join(palace_script_lines(values)), {'os':os,'settings':dict(values, sim_path=str(tmp_path))})
    assert 'export PALACE_NP=32\n' in path.read_text()
    assert path.read_text().endswith('run_palace config.json\n')
    assert 'export OMP_NUM_THREADS=2\n' in path.read_text()
    assert 'palace_mpi_processes' not in em_script_text(values, ports_from_struct([]), True)


@pytest.mark.parametrize('bad', [-1, 1.5, True, '12; echo unsafe'])
def test_launcher_rejects_invalid_counts(bad):
    with pytest.raises((ValueError, TypeError)):
        palace_execution_block({'palace_mpi_processes':bad})


def test_settings_tab_and_solver_switch_preserve_values(monkeypatch):
    from PySide6.QtWidgets import QApplication
    from setupEM import setupEM as module
    from setupEM import openems_ui
    app = QApplication.instance() or QApplication([])
    monkeypatch.setattr(module, 'get_preference', lambda app,key,default=None:default)
    module.saved_values.clear()
    window=module.MainWindow()
    try:
        tab=window.settings_tab
        assert window.tabs_widget.tabText(window.tabs_widget.indexOf(tab)) == 'Settings'
        tab.palace_mpi.setValue(32);tab.palace_threads.setValue(1)
        openems_ui.select(window,'openems')
        assert module.saved_values['palace_mpi_processes'] == 32
        assert tab.openems_threads.value()==16
        assert tab.openems_calibration_threads.value()==4
        assert tab.openems_total_threads.value()==32
        assert tab.openems_max_jobs.value()==8
        assert tab.openems_group.isAncestorOf(window.mesh_tab.openems_threads)
        assert tab.openems_group.isAncestorOf(window.mesh_tab.openems_engine)
        tab.openems_threads.setValue(12);tab.save_values()
        assert module.saved_values['openems_execution']==dict(total_threads=32,device_threads=12,calibration_threads=4,max_jobs=8)
        openems_ui.select(window,'palace')
        assert tab.palace_mpi.value() == 32 and tab.palace_threads.value() == 1
        openems_ui.select(window,'openems')
        assert tab.openems_threads.value() == 12
        tab.openems_threads.setValue(0);tab.save_values()
        assert module.saved_values['numThreads'] is None
        assert window.native_config_extra_struct()['solver'] == 'openems'
        tab.openems_total_threads.setValue(0);tab.save_values()
        assert module.saved_values['openems_execution'] is None
        openems_ui.select(window,'elmer')
        assert tab.elmer_group.isAncestorOf(window.mesh_tab.threads_box)
    finally:
        window._script_dirty=False;window.close();module.saved_values.clear()


def test_boxwall_scheduler_export_and_validation():
    from setupEM.script_model import ScriptModel
    config=dict(total_threads=32,device_threads=16,calibration_threads=4,max_jobs=8)
    values=dict(fstop=10,openems_execution=config,openems_boxwall=dict(side='xmax',signal_layer='Signal',
        return_layer='Ground',return_kind='metal',feed_length=100,gap=1))
    text=openems_script_text(values,ports_from_struct([]))
    assert ScriptModel(text).site('openems_execution').value==config
    compile(text,'boxwall.py','exec')
    with pytest.raises(ValueError,match='budget'):
        openems_script_text(dict(values,openems_execution=dict(config,device_threads=64)),ports_from_struct([]))
    with pytest.raises(ValueError,match='positive integer'):
        openems_script_text(dict(values,openems_execution=dict(config,device_threads=0)),ports_from_struct([]))
    assert 'openems_execution' not in em_script_text(values,ports_from_struct([]),False)
