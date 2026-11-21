"""Port pair selection, result readout and extraction settings in the actual GUI."""
import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
import numpy as np
import pytest
import skrf as rf
from PySide6.QtWidgets import QApplication
from setupEM import setupEM as module


@pytest.fixture
def window(monkeypatch):
    app=QApplication.instance() or QApplication([])
    monkeypatch.setattr(module,'get_preference',lambda app,key,default=None:default)
    module.saved_values.clear();w=module.MainWindow()
    yield w
    w._script_dirty=False;w.close();module.saved_values.clear()


def test_tab_loads_four_ports_and_keeps_analysis_settings_out_of_solver(window,tmp_path):
    f=np.linspace(1e8,8e9,81)
    z=np.broadcast_to(np.eye(4),(len(f),4,4)).copy().astype(complex)
    z*=5+2j*np.pi*f[:,None,None]*1e-9
    path=tmp_path/'four.s4p';rf.Network(f=f,z=z,z0=50).write_touchstone(str(path),form='ri')
    tab=window.postprocessing_tab
    window.tabs_widget.setCurrentWidget(tab)
    assert window.tabs_widget.currentWidget() is tab  # No GDS/stackup needed.
    assert window.tabs_widget.tabText(window.tabs_widget.indexOf(tab))=='Postprocessing'
    tab.files.setEditText(str(path));tab.load_file()
    assert tab.port_a.count()==4 and tab.port_b.count()==4
    tab.port_a.setCurrentIndex(3);tab.port_b.setCurrentIndex(1)
    assert not tab.export_button.isEnabled()
    tab.analyze()
    assert tab.result.summary['selected_ports']==[4,2]
    assert tab.export_button.isEnabled()
    assert 'Nearest native sample' in tab.sample_label.text()
    tab.save_values()
    assert window.native_config_extra_struct()['postprocessing']['port_a']==4
    assert 'postprocessing' not in window.saved_values
    tab.port_b.setCurrentIndex(3);tab.analyze()
    assert tab.result is None and 'different ports' in tab.status.text()


def test_line_needs_explicit_length_and_settings_roundtrip(window):
    tab=window.postprocessing_tab
    tab.mode.setCurrentIndex(1);tab.line_length.setValue(150);tab.length_unit.setCurrentText('um')
    tab.phase_branch.setValue(2);tab.minimum.setValue(.5);tab.maximum.setValue(12)
    tab.save_values();config=window.native_config_extra_struct()
    tab.line_length.setValue(20);tab.phase_branch.setValue(0)
    window.apply_native_config_data(config);tab.load_values()
    assert tab.line_length.value()==150 and tab.phase_branch.value()==2
    assert tab.specification().line_length_m==pytest.approx(150e-6)
    assert tab.minimum.value()==.5 and tab.maximum.value()==12
    assert 'de-embedded' in tab.assumptions.text()


def test_unused_tab_does_not_change_native_model_and_saved_ports_survive_unloaded_file(window):
    tab=window.postprocessing_tab
    tab.save_values()
    assert 'postprocessing' not in window.native_config_extra_struct()
    window.apply_analysis_config_data({'postprocessing':dict(file='future.s4p',port_a=4,port_b=2)})
    tab.save_values()
    assert window.postprocessing_settings['port_a']==4
    assert tab.network is None


def test_current_results_does_not_include_calibration_standards(window,tmp_path):
    tab=window.postprocessing_tab
    window.create_model_tab.targetdir_edit.setText(str(tmp_path))
    window.create_model_tab.modelname_edit.setText('device')
    root=tmp_path/'output/device_data';root.mkdir(parents=True)
    (root/'device.s2p').write_text('raw')
    (root/'device_calibrated.s2p').write_text('calibrated')
    (root/'other.S2P').write_text('uppercase')
    (root/'standards').mkdir();(root/'standards/cal.s4p').write_text('standard')
    tab.find_current()
    paths=[tab.files.itemText(i) for i in range(tab.files.count())]
    assert len(paths)==3 and paths[0].endswith('_calibrated.s2p')
    assert tab.network is None


def test_dc_subtab_uses_full_network_and_invalidates_on_source_change(window,tmp_path):
    tab=window.postprocessing_tab
    path=tmp_path/'four.s4p'
    rf.Network(f=np.linspace(1e6,1e9,20),s=np.zeros((20,4,4)),z0=50).write_touchstone(str(path))
    tab.files.setEditText(str(path));tab.subtabs.setCurrentWidget(tab.dc_tab)
    tab.dc_tab.estimate()
    assert tab.dc_tab.result.nports==4 and tab.dc_tab.result.f[0]==0
    assert tab.dc_tab.export_button.isEnabled()
    tab.files.setEditText(str(tmp_path/'missing.s4p'))
    assert tab.dc_tab.result is None and not tab.dc_tab.export_button.isEnabled()
    tab.dc_tab.estimate()
    assert 'Cannot estimate DC' in tab.dc_tab.details.toPlainText()


def test_lumped_subtab_process_preserves_input_and_records_failure(window,tmp_path):
    import time,json
    from PySide6.QtCore import QProcess
    tab=window.postprocessing_tab;model=tab.lumped_tab
    path=tmp_path/'source.s2p'
    rf.Network(f=np.linspace(1e8,8e9,20),s=np.zeros((20,2,2)),z0=50).write_touchstone(str(path))
    original=path.read_bytes();tab.files.setEditText(str(path))
    script=tmp_path/'repo/inductor_fit/inductor_fit.py';script.parent.mkdir(parents=True)
    script.write_text('print("fitter diagnostic",flush=True)\nraise ValueError("example failure")\n')
    model.repository.setText(str(script.parent.parent))
    folder=tmp_path/'run';model.start_run(folder)
    deadline=time.monotonic()+30
    while not model.run_button.isEnabled() and time.monotonic()<deadline:
        QApplication.processEvents();time.sleep(.01)
    assert model.process.state()==QProcess.NotRunning
    assert model.run_button.isEnabled() and not model.stop_button.isEnabled()
    assert 'example failure' in model.log.toPlainText()
    report=json.loads((folder/'run.json').read_text())
    assert report['status']=='failed_or_stopped' and report['source']['path']==str(path)
    assert path.read_bytes()==original
    model.basic.setChecked(True);tab.dc_tab.method.setCurrentIndex(1)
    tab.save_values();config=window.native_config_extra_struct()
    window.apply_analysis_config_data(config)
    assert model.basic.isChecked() and tab.dc_tab.method.currentData()=='cartesian'


def test_plot_subtab_compares_native_grids_and_roundtrips_legend_rows(window,tmp_path):
    tab=window.postprocessing_tab;plot=tab.plot_tab
    paths=[]
    for name,count in [('first',81),('second',23)]:
        f=np.linspace(1e8,8e9,count);z=np.zeros((count,2,2),complex)
        z[:,0,0]=z[:,1,1]=2+2j*np.pi*f*1e-9
        path=tmp_path/(name+'.s2p');rf.Network(f=f,z=z,z0=50).write_touchstone(str(path),form='ri');paths.append(path)
    window.tabs_widget.setCurrentWidget(tab);tab.subtabs.setCurrentWidget(plot)
    assert tab.subtabs.tabText(tab.subtabs.currentIndex())=='Plot'
    plot.add_entry(dict(path=str(paths[0]),label='Reference'))
    plot.add_entry(dict(path=str(paths[1])))
    plot.plot()
    assert plot.export_button.isEnabled() and len(plot.figure.axes)==6
    assert [line.get_label() for line in plot.figure.axes[0].lines[:2]]==['Reference','second.s2p']
    assert len(plot.figure.axes[0].lines[0].get_xdata())==81
    assert len(plot.figure.axes[0].lines[1].get_xdata())==23
    assert plot.readout.rowCount()==2 and plot.readout.item(0,2).text()=='2'
    plot.files.item(1,2).setText('Variant')
    assert plot.result is None and not plot.export_button.isEnabled()
    tab.save_values();config=window.native_config_extra_struct()
    window.apply_analysis_config_data(config)
    assert plot.files.rowCount()==2 and plot.files.item(1,2).text()=='Variant'
    assert plot.result is None and tab.network is None
    plot.mode.setCurrentIndex(1);plot.minimum.setValue(0);plot.plot()
    assert plot.result['mode']=='raw' and len(plot.figure.axes)==8
    assert plot.readout.columnCount()==6 and plot.readout.rowCount()==2


def test_plot_export_writes_figure_and_comparison_provenance(window,tmp_path,monkeypatch):
    from PySide6.QtWidgets import QFileDialog
    f=np.linspace(1e8,8e9,21);z=np.broadcast_to(np.eye(2),(21,2,2)).copy().astype(complex)
    z*=2+2j*np.pi*f[:,None,None]*1e-9
    path=tmp_path/'source.s2p';rf.Network(f=f,z=z,z0=50).write_touchstone(str(path),form='ri')
    original=path.read_bytes();plot=window.postprocessing_tab.plot_tab
    plot.add_entry(dict(path=str(path)));plot.plot()
    monkeypatch.setattr(QFileDialog,'getExistingDirectory',lambda *args:str(tmp_path))
    plot.export()
    folder=next(tmp_path.glob('comparison_*'))
    assert (folder/'comparison.png').stat().st_size>1000
    assert (folder/'comparison.svg').stat().st_size>1000
    assert (folder/'curve_01.csv').exists() and (folder/'comparison.json').exists()
    assert path.read_bytes()==original


def test_separate_plot_windows_reopen_and_keep_native_readouts_synchronized(window,tmp_path):
    f=np.linspace(1e8,8e9,81);z=np.broadcast_to(np.eye(2),(81,2,2)).copy().astype(complex)
    z*=2+2j*np.pi*f[:,None,None]*1e-9
    path=tmp_path/'source.s2p';rf.Network(f=f,z=z,z0=50).write_touchstone(str(path),form='ri')
    window.show();tab=window.postprocessing_tab;tab.files.setEditText(str(path));tab.load_file()
    view=tab.plot_window;figure=tab.figure
    assert view.isWindow() and view.isVisible() and tab.canvas.window() is view
    view.marker.setValue(5);assert tab.marker.value()==5
    assert 'Nearest native sample' in view.readout.toPlainText()
    view.close();assert not view.isVisible()
    tab.show_plot_button.click();assert view.isVisible() and tab.figure is figure
    tab.minimum.setValue(.5)
    assert 'Settings changed' in view.readout.toPlainText() and not tab.export_button.isEnabled()
    tab.analyze();assert tab.figure is figure and 'Settings changed' not in view.readout.toPlainText()
    plot=tab.plot_tab;plot.add_entry(dict(path=str(path)));plot.plot()
    assert plot.plot_window.isVisible() and plot.canvas.window() is plot.plot_window
    plot.plot_window.marker.setValue(2);assert plot.marker.value()==2 and tab.marker.value()==5
    assert 'Native GHz' in plot.plot_window.readout.toPlainText()
    plot.plot_window.close();plot.show_plot_button.click();assert plot.plot_window.isVisible()
    window._script_dirty=False;window.close();QApplication.processEvents()
    assert not view.isVisible() and not plot.plot_window.isVisible()
