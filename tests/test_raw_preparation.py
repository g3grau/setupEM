from pathlib import Path
import json
import numpy as np
import pytest
import gdstk
from setupEM.raw_preparation import preprocess,verified_report
from setupEM import pin_preparation as pins


@pytest.fixture(params=[1e-6,1e-9])
def raw_layout(tmp_path,request):
    unit=request.param;scale=1e-6/unit
    lib=gdstk.Library(unit=unit,precision=min(unit/1000,1e-9))
    top=gdstk.Cell('CADENCE_TOP');lib.add(top)
    top.add(gdstk.rectangle((0,0),(30*scale,10*scale),layer=8))
    for x,name in ((0,'IN'),(28,'OUT')):
        top.add(gdstk.rectangle((x*scale,2*scale),((x+2)*scale,4*scale),layer=8,datatype=2))
        top.add(gdstk.Label(name,((x+1)*scale,3*scale),layer=8))
    for i in range(20):
        x=40+i*5;top.add(gdstk.rectangle((x*scale,0),((x+2)*scale,2*scale),layer=8))
    top.add(gdstk.rectangle((0,20*scale),(2*scale,22*scale),layer=8,datatype=22))
    top.add(gdstk.rectangle((0,30*scale),(5*scale,35*scale),layer=999))
    child=gdstk.Cell('PIN_CHILD');lib.add(child)
    child.add(gdstk.Label('CHILD_LABEL',(1*scale,1*scale),layer=999))
    top.add(gdstk.Reference(child,(10*scale,30*scale),rotation=np.pi/2))
    lib.add(gdstk.Cell('$$$CONTEXT_INFO$$$'))
    source=tmp_path/'cadence.gds';lib.write_gds(source)
    mapfile=tmp_path/'stream.map';mapfile.write_text('M1 drawing 8 0\nM1 pin 8 2\nM1 label 8 0\n')
    stackup=Path(__file__).parents[1]/'src/setupEM/data/SG13G2_FEM_200um.xml'
    options=dict(source=str(source),stackup=str(stackup),mapfile=str(mapfile),cell='',output=str(tmp_path/'cadence_cleaned.gds'),
        drawing_datatypes=[0],drop_datatypes=[22],excluded_layers=[],fill_minsize=1.,fill_maxsize=20.,fill_mincount=20,
        max_hole_area=1.,via_merge_size=0.,do_floating=True,do_cutouts=True,do_merge=True,
        fill_ground_holes=False,variable_overrides={},port_layer_range=[201,299])
    return source,options


def test_cleanup_preserves_pins_labels_units_and_then_prepares_ports(raw_layout,tmp_path):
    source,options=raw_layout;original=source.read_bytes()
    rows=pins.read_map(Path(options['mapfile']))
    before=pins.inspect(source,rows,'CADENCE_TOP')[2]
    report=preprocess(options)
    assert source.read_bytes()==original and verified_report(options)==report
    clean=Path(options['output']);lib=gdstk.read_gds(clean);top=lib.top_level()[0]
    assert lib.unit==report['unit_m'] and top.name=='CADENCE_TOP' and not top.references
    assert len(top.labels)==3 and len([p for p in top.polygons if (p.layer,p.datatype)==(8,0)])==1
    assert not [p for p in top.polygons if p.datatype==22]
    assert len([p for p in top.polygons if p.layer==999])==1
    after=pins.inspect(clean,rows,'CADENCE_TOP')[2]
    assert [p['names'] for p in after]==[p['names'] for p in before]==[['IN'],['OUT']]
    for a,b in zip(before,after):np.testing.assert_allclose(a['_polygon'],b['_polygon'])
    data=pins.write(clean,tmp_path/'cadence_ems.gds',rows,[(1,'IN'),(2,'OUT')],cellname=report['cell'],preparation=report)
    assert data['raw_preparation']['source']['sha256']==report['source']['sha256']
    assert pins.names_for_gds(tmp_path/'cadence_ems.gds')=={240:'IN',241:'OUT'}


def test_stale_settings_and_sources_cannot_be_forwarded(raw_layout):
    source,options=raw_layout;preprocess(options)
    changed=dict(options,fill_mincount=21)
    with pytest.raises(ValueError,match='settings changed'):verified_report(changed)
    with source.open('ab') as stream:stream.write(b'changed')
    with pytest.raises(ValueError,match='changed'):verified_report(options)
    with pytest.raises(ValueError,match='already exists'):preprocess(options)


def test_pin_datatype_removal_and_wrong_cell_fail_without_output(raw_layout):
    source,options=raw_layout
    with pytest.raises(ValueError,match='contains mapped pins'):preprocess(dict(options,drop_datatypes=[2]))
    with pytest.raises(ValueError,match='cell not found'):preprocess(dict(options,cell='MISSING'))
    assert not Path(options['output']).exists()


def test_repeated_terminal_shape_is_not_published_as_removed_fill(raw_layout):
    source,options=raw_layout
    lib=gdstk.read_gds(source);top=next(c for c in lib.cells if c.name=='CADENCE_TOP');scale=1e-6/lib.unit
    top.add(gdstk.rectangle((40*scale,0),(42*scale,2*scale),layer=8,datatype=2))
    top.add(gdstk.Label('TERMINAL',(41*scale,scale),layer=8));lib.write_gds(source)
    with pytest.raises(ValueError,match='beneath a mapped M1 pin'):preprocess(options)
    assert not Path(options['output']).exists()
    report=preprocess(dict(options,do_floating=False))
    assert report['pin_drawing_overlaps_checked']==3
