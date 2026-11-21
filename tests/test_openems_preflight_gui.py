"""Invalid calibration bands may be previewed, but cannot launch solvers."""
import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from types import SimpleNamespace
from PySide6.QtWidgets import QApplication,QPlainTextEdit,QMessageBox
from setupEM import openems_ui,openems_preflight


def test_gui_displays_guidance_and_blocks_only_run_for_invalid_band(monkeypatch):
    app=QApplication.instance() or QApplication([])
    report=dict(ok=False,geometry_ok=True,title='Calibration needs changes',
                lines=['Maximum-permittivity half-wave check: FAIL'],
                guidance=['Reduce Stop frequency below 24.95 GHz'],warnings=[],notes=[],groups=[])
    monkeypatch.setattr(openems_preflight,'check_configuration',lambda *a:report)
    dialogs=[]
    monkeypatch.setattr(QMessageBox,'warning',lambda *a:dialogs.append(a[2]))
    panel=QPlainTextEdit()
    window=SimpleNamespace(saved_values={'openems_boxwall':{'side':'xmax'}},
        native_config_extra_struct=lambda:{'ports':[]},openems_calibration_report=panel)
    assert openems_ui.check_calibration(window,for_run=False)
    assert not dialogs
    assert not openems_ui.check_calibration(window,for_run=True)
    assert 'Reduce Stop frequency' in dialogs[-1]
    assert 'half-wave check: FAIL' in panel.toPlainText()
    report.update(geometry_ok=False)
    assert not openems_ui.check_calibration(window,for_run=False)
    panel.close()


def test_start_blocks_before_writing_model_or_starting_process(monkeypatch):
    from setupEM import setupEM as module
    from PySide6.QtCore import QProcess
    app=QApplication.instance() or QApplication([])
    monkeypatch.setattr(module,'get_preference',lambda app,key,default=None:default)
    module.saved_values.clear()
    window=module.MainWindow()
    try:
        window.setOpenEMSMode()
        window.saved_values['openems_boxwall']={'side':'xmax'}
        monkeypatch.setattr(window,'save_all_tabs',lambda:True)
        monkeypatch.setattr(openems_preflight,'check_configuration',lambda *a:dict(
            ok=False,geometry_ok=True,title='Calibration needs changes',lines=['Phase check: FAIL'],
            guidance=['Reduce Stop frequency'],warnings=[],notes=[],groups=[]))
        monkeypatch.setattr(QMessageBox,'warning',lambda *a:None)
        tab=window.create_model_tab
        monkeypatch.setattr(tab,'model_code',lambda *a:__import__('pytest').fail('Must not generate a run'))
        tab.run_model()
        assert tab.process.state()==QProcess.NotRunning
        assert 'Reduce Stop frequency' in window.openems_run_calibration_report.toPlainText()
    finally:
        window._script_dirty=False;window.close();module.saved_values.clear()
