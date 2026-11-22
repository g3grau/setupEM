from pathlib import Path
import hashlib
import json
import os
import sys
import pytest
import gdspy
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
sys.path.insert(0,str(Path(__file__).parents[1]/'src'))
from setupEM import pin_preparation as pins


@pytest.fixture
def original(tmp_path):
    lib=gdspy.GdsLibrary(unit=1e-6,precision=1e-9)
    child=lib.new_cell('PIN_CHILD_'+tmp_path.name)
    child.add(gdspy.Rectangle((0,0),(2,4),layer=136))
    child.add(gdspy.Label('PLUS',(1,2),layer=36))
    top=lib.new_cell('PIN_TOP_'+tmp_path.name)
    top.add(gdspy.CellReference(child,(10,20),rotation=90))
    top.add(gdspy.Rectangle((20,20),(22,24),layer=136))
    top.add(gdspy.Label('MINUS',(21,22),layer=136))
    top.add(gdspy.Rectangle((0,0),(30,30),layer=36))
    top.add(gdspy.Rectangle((-1,-1),(0,0),layer=240))
    path=tmp_path/'original.gds';lib.write_gds(str(path))
    return path,[('M6','drawing',36,0),('M6','pin',136,0),('reserved','drawing',241,0)]


def test_hierarchy_names_and_non_destructive_output(original,tmp_path):
    source,rows=original;before=source.read_bytes()
    lib,cell,inventory=pins.inspect(source,rows)
    assert [p['names'] for p in inventory]==[['PLUS'],['MINUS']]
    assert all(p['match']=='inside' for p in inventory)
    output=tmp_path/'prepared_ems.gds'
    data=pins.write(source,output,rows,[(2,'OUT'),(1,'IN')])
    assert source.read_bytes()==before
    assert [p['source_layernum'] for p in data['ports']]==[242,243]
    assert [p['portnumber'] for p in data['ports']]==[1,2]
    assert pins.names_for_gds(output)=={242:'OUT',243:'IN'}
    lib=gdspy.GdsLibrary();lib.read_gds(str(output),units='import')
    top=lib.cells[cell.name]
    assert len(top.references)==1
    assert len(top.get_polygons(by_spec=True)[(136,0)])==2
    assert {label.text for label in top.labels if label.layer in (242,243)}=={'IN','OUT'}
    assert data['unit_m']==pytest.approx(1e-6)
    with pytest.raises(ValueError,match='exists'):pins.write(source,output,rows,[(1,'IN')])
    with pytest.raises(ValueError,match='input'):pins.write(source,source,rows,[(1,'IN')])
    assert source.read_bytes()==before
    output.write_bytes(output.read_bytes()+b'changed')
    assert pins.names_for_gds(output)=={}


def test_unmatched_labels_require_review(original):
    source,rows=original
    rows=[('M6','pin',136,0)]
    lib,cell,inventory=pins.inspect(source,rows)
    assert inventory[0]['match']=='nearest'
    assert inventory[0]['names']==['MINUS']


def test_dialog_inventory_selection_and_named_port_headers(original,monkeypatch):
    from PySide6.QtWidgets import QApplication,QTableWidgetItem
    from PySide6.QtCore import Qt
    from setupEM import setupEM as module,openems_ui
    from setupEM.prepare_ports_dialog import PreparePortsDialog
    app=QApplication.instance() or QApplication([])
    monkeypatch.setattr(module,'get_preference',lambda app,key,default=None:default)
    module.saved_values.clear();w=module.MainWindow()
    try:
        source,rows=original
        w.file_tab.gds_file_edit.setText(str(source))
        w.saved_values['cellname']=''
        dialog=PreparePortsDialog(w)
        dialog.mapping.setPlainText('\n'.join(f'{n} {p} {l} {d}' for n,p,l,d in rows))
        dialog.scan()
        assert dialog.table.rowCount()==2
        assert dialog.table.item(0,0).checkState()==Qt.Checked
        assert dialog.table.item(0,2).text()=='PLUS'
        dialog.table.item(0,2).setText('INPUT')
        dialog.generate()
        assert dialog.result_data['ports'][0]['name']=='INPUT'
        w.file_tab.gds_file_edit.setText(dialog.output.text())
        w.ports_tab.portslist.setItem(0,2,QTableWidgetItem('242'))
        w.ports_tab.refresh_missing_layer_annotations()
        assert w.ports_tab.portslist.verticalHeaderItem(0).text()=='1 · INPUT'
        w.setOpenEMSMode()
        openems_ui.refresh_port_overview(w)
        assert w.ports_tab.portslist.verticalHeaderItem(0).text()=='1 · INPUT'
        assert hasattr(w.file_tab,'prepare_ports_btn')
        dialog.close()
    finally:
        w._script_dirty=False;w.close();module.saved_values.clear()


def test_preview_layer_names_use_verified_manifest_and_keep_numeric_fallback(tmp_path):
    import hashlib
    import json
    from setupEM.pin_preparation import preview_layer_names
    gds=tmp_path/'example.gds';gds.write_bytes(b'layout fixture')
    mapfile=tmp_path/'stream.map';mapfile.write_text('M1 drawing 8 0\nM1 pin 8 2\nLABEL text 999 0\n')
    assert preview_layer_names(gds,mapfile)=={8:'M1',999:'LABEL'}
    assert preview_layer_names(gds)=={}
    manifest=dict(schema='setupEM.ports.v1',ports=[],output_sha256=hashlib.sha256(gds.read_bytes()).hexdigest(),
        mapping=[['SAVED_LAYER','drawing',999,0]])
    gds.with_suffix('.ports.json').write_text(json.dumps(manifest))
    assert preview_layer_names(gds,mapfile)=={999:'SAVED_LAYER'}
    gds.write_bytes(b'changed layout')
    assert preview_layer_names(gds,mapfile)=={}  # Never attach stale manifest names.
