import json
from pathlib import Path
import time
import numpy as np
import pytest
from PySide6.QtWidgets import QApplication
from setupEM import setupEM as module
from test_broadband_model import engine_python,source_network


@pytest.fixture
def window(monkeypatch):
    app=QApplication.instance() or QApplication([])
    monkeypatch.setattr(module,'get_preference',lambda app,key,default=None:default)
    module.saved_values.clear();window=module.MainWindow()
    yield window
    window.broadband_tab.shutdown();window._script_dirty=False;window.close();module.saved_values.clear()


def test_broadband_tab_is_independent_and_default_does_not_change_native_configs(window):
    tab=window.broadband_tab;post=window.postprocessing_tab
    window.tabs_widget.setCurrentWidget(post);post.subtabs.setCurrentWidget(tab)
    assert window.tabs_widget.currentWidget() is post and post.subtabs.currentWidget() is tab
    assert window.tabs_widget.indexOf(tab)==-1
    assert post.subtabs.tabText(post.subtabs.indexOf(tab))=='Broadband Model'
    assert post.subtabs.indexOf(tab)==post.subtabs.indexOf(post.lumped_tab)+1
    tab.save_values();assert 'broadband' not in window.native_config_extra_struct()
    tab.order.setValue(12);tab.minimum.setValue(.5);tab.maximum.setValue(8);tab.dc_leak.setValue(.01)
    post.save_values();config=window.native_config_extra_struct();tab.order.setValue(6)
    window.apply_analysis_config_data(config)
    assert tab.order.value()==12 and tab.minimum.value()==.5 and tab.maximum.value()==8
    assert tab.specification().dc_island_leak_siemens==pytest.approx(1e-8)
    assert 'broadband' not in window.saved_values


def test_real_fit_and_plot_handoff_run_without_simulation(window,tmp_path,engine_python):
    source=tmp_path/'original.s4p';source_network(source,4,False);original=source.read_bytes()
    tab=window.broadband_tab;tab.engine_python.setText(engine_python);tab.file.setText(str(source));tab.load_file()
    assert '4 ports' in tab.source_label.text() and 'No finite source DC' in tab.dc_info.text()
    folder=tmp_path/'fit';tab.start_run(folder)
    deadline=time.monotonic()+120
    while not tab.run_button.isEnabled() and time.monotonic()<deadline:
        QApplication.processEvents();time.sleep(.01)
    assert tab.run_button.isEnabled() and tab.report and tab.report.get('ok'),tab.log.toPlainText()
    assert tab.errors.rowCount()==16 and tab.progress.value()==100 and tab.compare_button.isEnabled()
    assert 'actual order' in tab.summary.toPlainText() and 'DC operating point' in tab.summary.toPlainText()
    tab.compare();plot=window.postprocessing_tab.plot_tab
    assert window.tabs_widget.currentWidget() is window.postprocessing_tab
    assert plot.result['mode']=='raw' and len(plot.result['curves'])==2
    assert plot.plot_window.isVisible()
    model=plot.result['curves'][1];data=plot.result['curves'][0]
    assert max(abs(model['columns']['ba_real']-data['columns']['ba_real']))<.002
    count=plot.files.rowCount();tab.compare();assert plot.files.rowCount()==count
    assert source.read_bytes()==original


def test_failed_source_and_missing_backend_preserve_existing_results(window,tmp_path):
    tab=window.broadband_tab;tab.engine_python.setText(str(tmp_path/'missing-python'))
    tab.file.setText(str(tmp_path/'missing.s2p'));tab.start_run(tmp_path/'run')
    assert 'Cannot start' in tab.status.text() and not (tmp_path/'run').exists()
