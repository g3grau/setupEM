"""Synthetic deep-return fixture: planned standards must satisfy later phase checks."""
import numpy as np
import pytest
pytest.importorskip('gds2openEMS')
from gds2openEMS import stackup_reader,gds_reader,simulation_setup
from gds2openEMS import util_boxwall as boxwall


@pytest.fixture
def deep_return(tmp_path):
    xml=tmp_path/'generic_stack.xml'
    xml.write_text('''<Stackup schemaVersion="3.0"><Materials>
      <Material Name="Metal" Type="Conductor" Conductivity="5.8e7" Color="aaaaaa"/>
      <Material Name="Bulk" Type="Dielectric" Permittivity="11.9" Color="aaaaaa"/>
      <Material Name="Air" Type="Dielectric" Permittivity="1" Color="eeeeee"/>
      </Materials><ELayers LengthUnit="um"><Dielectrics>
      <Dielectric Name="Bulk" Material="Bulk" Zmin="2" Zmax="210"/>
      <Dielectric Name="Air" Material="Air" Zmin="210" Zmax="260"/>
      </Dielectrics><Layers><Substrate Offset="0"/>
      <Layer Name="Ground" Type="conductor" Material="Metal" Layer="1" Zmin="0" Zmax="2"/>
      <Layer Name="Signal" Type="conductor" Material="Metal" Layer="2" Zmin="206.19" Zmax="209.59"/>
      </Layers></ELayers></Stackup>''')
    ma,di,me=stackup_reader.read_substrate(str(xml))
    polygons=gds_reader.all_polygons_list();polygons.add_rectangle(0,-200,500,200,1)
    ports=simulation_setup.all_simulation_ports()
    for i,(lo,hi) in enumerate([(-14.505,-9.505),(7.5,12.5)],1):
        polygons.add_rectangle(0,lo,500,hi,2)
        polygons.add_rectangle(499,lo,500,hi,200+i)
        ports.add_port(simulation_setup.simulation_port(i,1,50,200+i,target_layername='Signal',direction='-x'))
    return dict(unit=1e-6,margin=100,air_around=50,Boundaries=['PEC','PORTWALL','PEC','PEC','PEC','PEC'],
                fstart=0,fstop=25e9,numfreq=41,refined_cellsize=1,cells_per_wavelength=10,
                energy_limit=-60,no_gui=True,simulation_ports=ports,allpolygons=polygons,
                materials_list=ma,dielectrics_list=di,metals_list=me,
                sim_path=str(tmp_path/'output'),model_basename='generic',reference_plane_shift={'xmax':150})


def test_impossible_25ghz_band_fails_before_solver(deep_return,monkeypatch):
    plan=boxwall.prepare(deep_return)
    group=plan['analysis']['groups'][0]
    assert group['phase_valid_to_GHz']<25
    assert any('2L exceeds half a wavelength' in w for w in plan['analysis']['warnings'])
    monkeypatch.setattr(boxwall,'_run_model',lambda *a:pytest.fail('Solver must not be called'))
    with pytest.raises(ValueError,match='before solving calibration standards'):
        boxwall.run(plan)


def test_24ghz_auto_standard_satisfies_postsolve_guard(deep_return):
    deep_return['fstop']=24e9
    plan=boxwall.prepare(deep_return);group=plan['analysis']['groups'][0]
    assert not plan['analysis']['warnings']
    assert 2*group['L']*1e-6*24e9*np.sqrt(group['eps_max'])/299792458<=.5
    assert group['L']>=2*group['D']-.001


def test_user_standard_length_gets_same_preflight_guard(deep_return):
    deep_return['deembedding_length']=944.345
    plan=boxwall.prepare(deep_return)
    group=plan['analysis']['groups'][0]
    assert group['phase_valid_to_GHz']==pytest.approx(23.006817,abs=1e-5)
    assert any('2L exceeds half a wavelength' in w for w in plan['analysis']['warnings'])


def test_gui_explanation_has_both_limits_and_actionable_fix(deep_return):
    from setupEM.openems_preflight import describe_plan,report_text
    report=describe_plan(boxwall.prepare(deep_return))
    text=report_text(report)
    assert not report['ok'] and report['geometry_ok']
    assert 'Effective-index wavelength check' in text
    assert 'Maximum-permittivity half-wave check: FAIL' in text
    assert 'reduce Stop frequency below' in text
    assert 'Increasing dielectric oversize or feed length does not fix' in text
    assert report['groups'][0]['geometry_band_limit_GHz']==pytest.approx(24.95076,rel=1e-4)
    deep_return['fstop']=24e9
    assert describe_plan(boxwall.prepare(deep_return))['ok']


def test_geometry_error_guidance_distinguishes_feed_and_reference_plane():
    from setupEM.openems_preflight import geometry_failure,report_text
    feed=report_text(geometry_failure(ValueError('cross-section changes within D/4; move outward by at least 22.33')))
    assert 'Increase Uniform feed length by at least 22.33 um' in feed
    plane=report_text(geometry_failure(ValueError('reference_plane_shift for xmax = 150 moves past uniform feed, which ends 136.5 from the wall')))
    assert 'more than 13.500 um' in plane and 'changes the measurement reference plane' in plane


def test_preflight_reads_real_inputs_without_output_or_solver(deep_return,tmp_path,monkeypatch):
    import gdspy
    from setupEM.openems_preflight import check_configuration
    lib=gdspy.GdsLibrary();cell=lib.new_cell('GENERIC_PREFLIGHT')
    for p in deep_return['allpolygons'].polygons:
        cell.add(gdspy.Polygon(list(zip(p.pts_x,p.pts_y)),layer=int(p.layernum)))
    path=tmp_path/'fixture.gds';lib.write_gds(str(path))
    v=dict(GdsFile=str(path),SubstrateFile=str(tmp_path/'generic_stack.xml'),purpose=[0],
           fstart=0,fstop=25,numfreq=41,refined_cellsize=1,cells_per_wavelength=10,
           openems_boxwall=dict(side='xmax',signal_layer='Signal',return_kind='metal',return_layer='Ground',
                               feed_length=150,gap=1,width=5),sim_path=str(tmp_path/'must-not-be-created'))
    ports=[dict(portnumber=i,voltage=1,port_Z0=50,source_layernum=200+i,
                from_layername='Ground',to_layername='Signal',direction='Z') for i in (1,2)]
    monkeypatch.setattr(boxwall,'_run_model',lambda *a:pytest.fail('Preflight must not run solver'))
    report=check_configuration(v,ports)
    assert report['geometry_ok'] and not report['ok']
    assert not (tmp_path/'must-not-be-created').exists()
