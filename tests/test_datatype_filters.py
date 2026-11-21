import os,sys
from pathlib import Path
import pytest
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
sys.path.insert(0,str(Path(__file__).parents[1]/'src'))
from setupEM.datatype_filters import parse_datatypes,format_datatypes

@pytest.mark.parametrize('value,expected',[
 ('0:3, 40,50:52,60',[0,1,2,3,40,50,51,52,60]),
 ('30:30,0:2,2',[30,0,1,2]),('[0, 20]',[0,20]),('0,35,4',[0,35,4]),
 ([[0,20]],[0,20]),('',[]),('65535',[65535])])
def test_parse(value,expected):assert parse_datatypes(value)==expected

@pytest.mark.parametrize('text',['-1','65536','5:3','0:65536','1::3','1:3,','1.5','True','*,5'])
def test_invalid_filters(text):
 with pytest.raises(ValueError):parse_datatypes(text)

def test_format_roundtrip_and_wildcard():
 assert format_datatypes(list(range(31))+[40,50,60])=='0:30, 40, 50, 60'
 assert format_datatypes([3,1,2,9,8])=='1:3, 8:9'
 assert format_datatypes(parse_datatypes('*'))=='*'
 assert parse_datatypes(format_datatypes([1,2,3,5]))==[1,2,3,5]

def test_gui_input_and_resizable_preview(monkeypatch):
 from PySide6.QtWidgets import QApplication
 from setupEM import setupEM as module,setup_common as common
 from setupEM.layout_preview import LayoutPreviewWindow
 app=QApplication.instance() or QApplication([])
 monkeypatch.setattr(module,'get_preference',lambda app,key,default=None:default)
 module.saved_values.clear();w=module.MainWindow()
 try:
  w.file_tab.purpose_edit.setText('0:30,40,50,60')
  assert w.file_tab.save_values()
  assert w.saved_values['purpose']==list(range(31))+[40,50,60]
  w.file_tab.load_values()
  assert w.file_tab.purpose_edit.text()=='0:30, 40, 50, 60'
  monkeypatch.setattr(LayoutPreviewWindow,'refresh',lambda self:None)
  preview=LayoutPreviewWindow(w);preview.show();app.processEvents()
  splitter=preview.content_splitter
  assert splitter.handleWidth()==9
  splitter.setSizes([700,300]);app.processEvents();a=splitter.sizes()
  splitter.setSizes([900,120]);app.processEvents();b=splitter.sizes()
  assert b[1]<a[1]
  preview._info_base_text='Datatypes: *';preview._update_info_label()
  assert preview.info_label.text()=='Datatypes: *'
  preview.close()
  warnings=[]
  monkeypatch.setattr(common.QMessageBox,'warning',lambda *args:warnings.append(args))
  w.file_tab.purpose_edit.setText('30:0')
  assert not w.file_tab.save_values()
  assert warnings and w.saved_values['purpose']==list(range(31))+[40,50,60]
 finally:
  w._script_dirty=False;w.close();module.saved_values.clear()
