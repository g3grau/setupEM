"""Backend isolation and solver-independent generated-workflow checks."""
import os
import sys
import runpy
import types
from pathlib import Path

import pytest

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from setupEM.openems_writer import openems_script_text
from setupEM.script_writer import ports_from_struct


def ports():
    return ports_from_struct([dict(portnumber=i, voltage=1, port_Z0=50,
                                   source_layernum=200+i, from_layername='Ground',
                                   to_layername='Signal', direction='Z') for i in (1, 2)])


def values():
    return dict(GdsFile='input.gds', SubstrateFile='stack.xml', purpose=[0, 40],
                cellname='top', fstart=0, fstop=12, refined_cellsize=1,
                merge_polygon_size=1, fill_factor_correction=True,
                variable_overrides={'height': 50}, energy_limit=-60, numThreads=8,
                openems_boundaries=['PEC', 'PEC', 'PMC', 'PMC', 'MUR', 'PML_8'],
                adaptive_mesh_iterations=4, conductor_model='solve_inside_skin')


@pytest.mark.parametrize('action,solves,xmls', [('--prepare-only', 0, 2), ('--preview-only', 0, 0), ('', 2, 0)])
def test_generated_workflow_never_solves_prepare_or_preview(monkeypatch, tmp_path, action, solves, xmls):
    calls = dict(solves=0, previews=0, xmls=0, sij=[], snp=0, setups=0)
    class Ports:
        def __init__(self):
            self.ports = []; self.portlayers = []
        @property
        def portcount(self):
            return len(self.ports)
        def add_port(self, port):
            self.ports.append(port);self.portlayers.append(port.source_layernum)
        def all_active_excitations(self):
            return [[p.portnumber] for p in self.ports if p.voltage]
        def get_reference_impedance(self):
            return 50
    def setup(**kwargs):
        calls['setups'] += 1
        assert kwargs['settings']['fill_factor_correction'] is True
        assert kwargs['settings']['numThreads'] == 8
    def simulate(**kwargs):
        if kwargs['settings']['preview_only']:
            calls['previews'] += 1
        else:
            calls['solves'] += 1
    class CSX:
        def Write2XML(self, path):
            calls['xmls'] += 1
    class FDTD:
        def __init__(self, **kwargs): pass
        def SetGaussExcite(self, center, width):
            assert center == width == 6e9
        def SetBoundaryCond(self, boundaries):
            assert boundaries == values()['openems_boundaries']
        def GetCSX(self): return CSX()
    def sij(i, j, f, *args):
        calls['sij'].append((i,j));return [0j]*len(f)
    def snp(*args, **kwargs):calls['snp'] += 1
    fake = types.ModuleType('gds2openEMS')
    fake.stackup_reader = types.SimpleNamespace(read_substrate=lambda *a, **k: (
        object(), types.SimpleNamespace(get_boundary_layers=lambda: []), types.SimpleNamespace(getlayernumbers=lambda: [1,2])))
    fake.gds_reader = types.SimpleNamespace(read_gds=lambda *a, **k: object())
    fake.simulation_setup = types.SimpleNamespace(all_simulation_ports=Ports,
        simulation_port=lambda **kw: types.SimpleNamespace(**kw), setupSimulation=setup, runSimulation=simulate)
    fake.utilities = types.SimpleNamespace(get_basename=lambda f: 'model',
        create_sim_path=lambda *a: str(tmp_path), get_excitation_path=lambda p,e: str(tmp_path/str(e)),
        calculate_Sij=sij, write_snp=snp)
    monkeypatch.setitem(sys.modules, 'gds2openEMS', fake)
    monkeypatch.setitem(sys.modules, 'openEMS', types.SimpleNamespace(openEMS=FDTD))
    model = tmp_path/'model.py';model.write_text(openems_script_text(values(), ports()))
    monkeypatch.setattr(sys, 'argv', [str(model)]+([action] if action else []))
    monkeypatch.chdir(tmp_path)
    runpy.run_path(str(model), run_name='__main__')
    assert calls['solves'] == solves
    assert calls['xmls'] == xmls
    assert calls['previews'] == (1 if action == '--preview-only' else 0)
    assert calls['snp'] == (0 if action else 1)
    assert set(calls['sij']) == (set() if action else {(1,1),(1,2),(2,1),(2,2)})


def test_export_is_vendor_independent_and_does_not_leak_fem_settings():
    text = openems_script_text(values(), ports())
    compile(text, 'model.py', 'exec')
    for unwanted in ('gds2palace', 'gmsh', 'IHP', 'TSMC', 'adaptive_mesh_iterations', 'solve_inside_skin'):
        assert unwanted not in text
    assert "direction='z'" in text


@pytest.mark.parametrize('change', [dict(fstop=0), dict(openems_boundaries=['ABC']*6),
    dict(margin=[1,2,3,4]), dict(energy_limit=0), dict(numfreq=1), dict(air_around=[1,2]),
    dict(refined_cellsize=0)])
def test_export_rejects_unsupported_or_invalid_settings(change):
    with pytest.raises(ValueError):
        openems_script_text(dict(values(), **change), ports())


def test_gui_solver_roundtrip_and_launch_modes(monkeypatch):
    from PySide6.QtWidgets import QApplication, QMessageBox
    from setupEM import setupEM as module
    app = QApplication.instance() or QApplication([])
    monkeypatch.setattr(module, 'get_preference', lambda app, key, default=None: default)
    monkeypatch.setattr(QMessageBox, 'warning', lambda *a, **k: QMessageBox.Ok)
    module.saved_values.clear()
    window = module.MainWindow()
    try:
        window.apply_native_config_data(dict(solver='openems', ports=[]))
        assert window.OpenEMSMode and not window.PalaceMode and not window.ElmerMode
        assert window.solver_selector.currentData() == 'openems'
        assert not window.mesh_tab.openems_group.isHidden()
        assert window.mesh_tab.AMR_group.isHidden()
        window.mesh_tab.openems_energy.setValue(-60)
        window.mesh_tab.openems_threads.setValue(12)
        assert window.mesh_tab.save_values()
        data = window.native_config_extra_struct()
        assert data['solver'] == 'openems'
        window.setPalaceMode()
        assert window.mesh_tab.openems_group.isHidden()
        assert not window.mesh_tab.label_amr_conformal.isHidden()
        window.apply_native_config_data(data)
        assert window.mesh_tab.openems_energy.value() == -60
        assert window.mesh_tab.openems_threads.value() == 12
        tab = window.create_model_tab
        assert tab.model_launch_args('model.py') == ['model.py', '--prepare-only']
        module.saved_values['preview_only'] = True
        assert tab.model_launch_args('model.py') == ['model.py', '--preview-only']
        tab._openems_run_requested = True
        assert tab.model_launch_args('model.py') == ['model.py']
        assert window.file_tab._current_solver() == 'openems'
    finally:
        window._script_dirty = False
        window.close()
        module.saved_values.clear()


def test_exported_settings_can_be_read_back_without_running_model():
    from setupEM.script_model import ScriptModel
    m = ScriptModel(openems_script_text(values(), ports()))
    assert m.site('fstop').value == 12e9
    assert m.site('energy_limit').value == -60
    assert m.site('numThreads').value == 8
    assert m.site('openems_boundaries').value == values()['openems_boundaries']
    assert len([p for p in m.ports if p.static]) == 2


def test_conformal_setting_is_written_without_adaptive_iterations():
    from setupEM.script_writer import em_script_text
    text = em_script_text(dict(adaptive_mesh_iterations=0, adaptive_mesh_conformal=True), ports(), False)
    assert "settings['adaptive_mesh_conformal'] = True" in text
