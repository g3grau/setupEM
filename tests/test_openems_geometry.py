"""Generated feature scripts and saved GUI options; existing exports stay opt-in."""
import os,sys
from pathlib import Path
import pytest
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from setupEM.openems_writer import openems_script_text
from setupEM.script_writer import ports_from_struct


def ports():
 return ports_from_struct([dict(portnumber=i,voltage=1,port_Z0=50,source_layernum=240+i,
  from_layername='M1',to_layername='M6',direction='Z') for i in (1,2)])


def config():
 return dict(side='xmax',signal_layer='M6',return_kind='metal',return_layer='M1',feed_length=100,gap=1,width=0)


def test_boxwall_export_is_explicit_and_preview_safe():
 text=openems_script_text(dict(openems_boxwall=config()),ports())
 compile(text,'model.py','exec')
 assert "settings['openems_boxwall']" in text
 assert 'boxwall.preview(plan)' in text
 assert 'prepare_only=args.prepare_only' in text
 assert 'add_boxwall_feeds' in text
 normal=openems_script_text({},ports())
 assert 'util_boxwall' not in normal and 'util_model_geometry' not in normal


def test_aircut_export_and_incompatible_combination():
 c=dict(metal='AP',valley_height=1,coating_width=.5)
 text=openems_script_text(dict(openems_aircut=c),ports())
 compile(text,'model.py','exec')
 assert 'add_rdl_aircut' in text
 with pytest.raises(ValueError,match='separate experiments'):
  openems_script_text(dict(openems_aircut=c,openems_boxwall=config()),ports())


def test_missing_return_is_not_silently_substituted():
 c=config();c['return_layer']=''
 with pytest.raises(ValueError,match='return layers'):
  openems_script_text(dict(openems_boxwall=c),ports())


@pytest.mark.parametrize('setback',[-1,100,float('nan')])
def test_invalid_reference_setback_rejected_before_generation(setback):
 with pytest.raises(ValueError,match='Reference plane setback'):
  openems_script_text(dict(openems_boxwall=dict(config(),reference_plane_setback=setback)),ports())


def test_generated_reference_plane_retains_ground_transition():
 # Execute the exported reference-plane code, rather than repeating its calculation.
 text=openems_script_text(dict(openems_boxwall=dict(config(),reference_plane_setback=14)),ports())
 code=text.split('feed_config = ',1)[1].split('plan = boxwall.prepare',1)[0]
 import numpy as np
 settings={'openems_boxwall':dict(config(),reference_plane_setback=14),
           'reference_plane_shift':{'xmax':100}}
 exec('feed_config = '+code,{'settings':settings,'np':np})
 assert settings['reference_plane_shift']=={'xmax':86}


def test_gui_features_roundtrip_and_solver_visibility(monkeypatch):
 from PySide6.QtWidgets import QApplication
 from setupEM import setupEM as module,openems_ui
 app=QApplication.instance() or QApplication([])
 monkeypatch.setattr(module,'get_preference',lambda app,key,default=None:default)
 module.saved_values.clear()
 w=module.MainWindow()
 try:
  w.setOpenEMSMode()
  assert w.openems_boxwall_group.isHidden()
  assert not w.openems_aircut_group.isHidden()
  w.ports_tab.port_kind_box.setCurrentIndex(w.ports_tab.port_kind_box.findData('boxwall'))
  w.openems_signal.setCurrentText('M6');w.openems_return.setCurrentText('M1')
  w.openems_reference_setback.setValue(13.485)
  from PySide6.QtWidgets import QTableWidgetItem
  table=w.ports_tab.portslist
  table.setItem(0,2,QTableWidgetItem('241'))
  table.setItem(0,6,QTableWidgetItem('Z'))
  openems_ui.refresh_port_overview(w)
  assert table.item(0,9).text()=='xmax / SWX → −X'
  assert table.item(0,10).text()=='M6'
  assert table.item(0,6).text()=='Z' and table.isColumnHidden(6)
  assert w.ports_tab.bottom_layout.itemAt(0).layout() is w.ports_tab.buttons_layout
  w.openems_wall_side.setCurrentText('ymin')
  assert table.item(0,9).text()=='ymin / SW-Y → +Y'
  w.openems_wall_side.setCurrentText('xmax')
  openems_ui.save(w)
  assert w.saved_values['openems_boxwall']=={'ports':{'1':dict(config(),reference_plane_setback=13.485)}}
  w.ports_tab.port_kind_box.setCurrentIndex(w.ports_tab.port_kind_box.findData('via'))
  openems_ui.load(w)
  assert (w.ports_tab.port_kind_box.currentData()=='boxwall')
  assert w.openems_signal.currentText()=='M6'
  assert w.openems_reference_setback.value()==13.485
  w.setPalaceMode()
  assert w.openems_boxwall_group.isHidden() and w.openems_aircut_group.isHidden()
  assert not table.isColumnHidden(6) and table.isColumnHidden(9)
  w.setOpenEMSMode()
  assert (w.ports_tab.port_kind_box.currentData()=='boxwall')
 finally:
  w._script_dirty=False;w.close();module.saved_values.clear()


def test_saved_geometry_preview_does_not_regenerate(tmp_path, monkeypatch):
 from PySide6.QtWidgets import QApplication
 from PySide6.QtCore import QProcess
 from setupEM import setupEM as module,openems_ui
 app=QApplication.instance() or QApplication([])
 monkeypatch.setattr(module,'get_preference',lambda app,key,default=None:default)
 module.saved_values.clear();w=module.MainWindow()
 try:
  path=tmp_path/'output'/'device_data'/'sub-1'/'device.xml'
  path.parent.mkdir(parents=True);path.write_text('<ContinuousStructure/>')
  original=path.read_bytes()
  w.saved_values.update(sim_path=str(tmp_path),model_basename='device')
  calls=[]
  monkeypatch.setattr(QProcess,'startDetached',lambda program,args:(calls.append((program,args)) or (True,123)))
  openems_ui.preview_saved_geometry(w)
  assert calls[0][1]==[str(path)]
  assert path.read_bytes()==original
  w.setOpenEMSMode();assert not w.openems_saved_preview.isHidden()
  grid=w.create_model_tab.buttons_grid
  index=grid.indexOf(w.openems_saved_preview)
  assert index>=0 and grid.getItemPosition(index)[0]>grid.getItemPosition(grid.indexOf(w.create_model_tab.create_run_btn))[0]
  w.setPalaceMode();assert w.openems_saved_preview.isHidden()
 finally:
  w._script_dirty=False;w.close();module.saved_values.clear()


def test_boxwall_editor_is_independent_per_port_and_disables_via_controls(monkeypatch):
 from PySide6.QtWidgets import QApplication
 from setupEM import setupEM as module,openems_ui
 app=QApplication.instance() or QApplication([])
 monkeypatch.setattr(module,'get_preference',lambda app,key,default=None:default)
 module.saved_values.clear();w=module.MainWindow()
 try:
  w.setOpenEMSMode()
  rows=[dict(portnumber=i,source_layernum=240+i,from_layername='M1',to_layername='M6',direction='Z') for i in (1,2)]
  w.ports_tab.update_port_from_import(rows);table=w.ports_tab.portslist
  table.selectRow(0);w.ports_tab.port_kind_box.setCurrentIndex(w.ports_tab.port_kind_box.findData('boxwall'))
  w.openems_signal.setCurrentText('M6');w.openems_return.setCurrentText('M1')
  assert not w.ports_tab.from_box.isEnabled() and not w.ports_tab.to_box.isEnabled()
  assert w.ports_tab.from_box.isHidden() and w.ports_tab.to_box.isHidden()
  assert w.ports_tab.direction_box.isHidden() and not w.openems_boxwall_group.isHidden()
  assert not w.ports_tab.direction_box.isEnabled()
  assert 'ground' in w.ports_tab.from_label.text() and 'signal' in w.ports_tab.to_label.text()
  table.selectRow(1)
  assert not (w.ports_tab.port_kind_box.currentData()=='boxwall')
  assert w.ports_tab.from_box.isEnabled() and w.ports_tab.to_box.isEnabled()
  assert w.ports_tab.direction_box.isEnabled()
  assert not w.ports_tab.from_box.isHidden() and w.openems_boxwall_group.isHidden()
  w.ports_tab.port_kind_box.setCurrentIndex(w.ports_tab.port_kind_box.findData('inplane'))
  assert w.ports_tab.direction_box.currentText()=='X'
  assert w.ports_tab.from_box.isHidden() and not w.ports_tab.target_box.isHidden()
  w.ports_tab.port_kind_box.setCurrentIndex(w.ports_tab.port_kind_box.findData('via'))
  assert w.ports_tab.direction_box.currentText()=='Z' and not w.ports_tab.from_box.isHidden()
  openems_ui.save(w)
  assert set(w.saved_values['openems_boxwall']['ports'])=={'1'}
  assert not table.isColumnHidden(6)  # Ordinary via direction remains visible in a mixed table.
  assert table.item(0,14).text()=='Boxwall feed' and table.item(1,14).text()=='Via port'
  w.ports_tab.port_kind_box.setCurrentIndex(w.ports_tab.port_kind_box.findData('boxwall'));w.openems_wall_side.setCurrentText('ymin')
  w.openems_signal.setCurrentText('M7');w.openems_return.setCurrentText('M2')
  w.openems_feed_length.setValue(140);w.openems_feed_width.setValue(4)
  w.openems_calibration_report.setPlainText('Last checked complete model')
  table.selectRow(0)
  assert w.openems_calibration_report.toPlainText()=='Last checked complete model'
  assert w.openems_signal.currentText()=='M6' and w.openems_return.currentText()=='M1'
  assert w.openems_wall_side.currentText()=='xmax' and w.openems_feed_length.value()==100
  assert w.openems_feed_width.value()==0
  w.ports_tab.port_kind_box.setCurrentIndex(w.ports_tab.port_kind_box.findData('via'))
  openems_ui.save(w)
  saved=w.saved_values['openems_boxwall']
  assert set(saved['ports'])=={'2'} and saved['ports']['2']['side']=='ymin'
  assert w.ports_tab.save_values()
  assert module.simulation_ports.ports[0].target_layername is None
  assert module.simulation_ports.ports[1].target_layername=='M7'
  table.selectRow(1)
  assert w.openems_signal.currentText()=='M7' and not w.ports_tab.from_box.isEnabled()
  # Reading back config selects only this port; legacy shared files still migrate.
  openems_ui.load(w)
  assert (w.ports_tab.port_kind_box.currentData()=='boxwall') and w.openems_feed_width.value()==4
  w.saved_values['openems_boxwall']=config();openems_ui.load(w);openems_ui.save(w)
  assert set(w.saved_values['openems_boxwall']['ports'])=={'1','2'}
 finally:
  w._script_dirty=False;w.close();module.saved_values.clear()


def test_per_port_export_preserves_mixed_ordinary_definitions():
 cfg={'ports':{'1':config(),'2':dict(config(),side='ymin',signal_layer='M7',return_layer='M2')}}
 text=openems_script_text(dict(openems_boxwall=cfg),ports())
 assert "'ports': {'1':" in text
 assert "if 'ports' not in feed_config:" in text
 compile(text,'per_port.py','exec')
 with pytest.raises(ValueError,match='Unknown boxwall port'):
  openems_script_text(dict(openems_boxwall={'ports':{'3':config()}}),ports())
