import json
import numpy as np
import pytest
import skrf as rf
from setupEM.network_comparison import ComparisonEntry,compare_networks,export_comparison


def write_network(path,f,ports=2,refs=50):
    z=np.broadcast_to(np.eye(ports),(len(f),ports,ports)).astype(complex).copy()
    z*=2+2j*np.pi*f[:,None,None]*1e-9
    net=rf.Network(f=f,z=z,z0=refs);net.write_touchstone(str(path),form='ri',write_z0=np.ndim(refs)>0)
    return net


def test_inductor_comparison_native_grids_names_points_and_export(tmp_path):
    first=tmp_path/'first.s2p';second=tmp_path/'second.s2p'
    f1=np.linspace(1e8,8e9,81);f2=np.linspace(2e8,6e9,23)
    write_network(first,f1);write_network(second,f2)
    original=first.read_bytes()
    result=compare_networks([ComparisonEntry(str(first),'Reference'),ComparisonEntry(str(second),style='points')])
    a,b=result['curves'];assert a['label']=='Reference' and b['label']=='second.s2p'
    np.testing.assert_array_equal(a['frequency_hz'],f1);np.testing.assert_array_equal(b['frequency_hz'],f2)
    np.testing.assert_allclose(a['columns']['L_H'],2e-9,rtol=1e-12)
    assert b['summary']['peak_Q'] is None
    folder=export_comparison(result,tmp_path/'comparison')
    report=json.loads((folder/'comparison.json').read_text())
    assert report['curves'][0]['source']['path']==str(first)
    assert len(np.loadtxt(folder/'curve_02.csv',skiprows=1,delimiter=','))==len(f2)
    with pytest.raises(FileExistsError):export_comparison(result,folder)
    assert first.read_bytes()==original


def test_multiport_open_selection_matches_independent_impedance_reduction(tmp_path):
    path=tmp_path/'four.s4p';f=np.linspace(1e8,8e9,21)
    z=np.broadcast_to(np.array([[60,2,4,5],[2,70,6,7],[4,6,80,8],[5,7,8,90]],complex),(len(f),4,4))
    rf.Network(f=f,z=z,z0=50).write_touchstone(str(path),form='ri')
    result=compare_networks([ComparisonEntry(str(path),port_a=4,port_b=2,unused_ports='open')],mode='raw')
    curve=result['curves'][0]
    expected=rf.Network(f=f,z=z[:,[3,1]][:,:,[3,1]],z0=50)
    np.testing.assert_allclose(curve['columns']['ba_real'],expected.s[:,1,0].real,atol=1e-15)
    np.testing.assert_allclose(curve['columns']['ab_imag'],expected.s[:,0,1].imag,atol=1e-15)


def test_raw_preserves_dc_unequal_refs_and_explicit_normalization(tmp_path):
    a=tmp_path/'a.s2p';b=tmp_path/'b.s2p';f=np.array([0,1e8,2e8,5e8])
    write_network(a,f,refs=50);write_network(b,f,refs=75)
    entries=[ComparisonEntry(str(a),'same'),ComparisonEntry(str(b),'same')]
    result=compare_networks(entries,'raw',minimum_hz=0)
    assert result['warnings'] and result['curves'][1]['label']=='same (2)'
    np.testing.assert_array_equal(result['curves'][0]['frequency_hz'],f)
    normalized=compare_networks(entries,'raw',minimum_hz=0,reference_ohm=50)
    assert not normalized['warnings']
    np.testing.assert_allclose(normalized['curves'][0]['columns']['ba_real'],normalized['curves'][1]['columns']['ba_real'],atol=1e-15)


def test_raw_phase_unwrap_precedes_band_crop_and_does_not_bridge_zero(tmp_path):
    f=np.linspace(1e8,10e9,101);s=np.zeros((len(f),2,2),complex);s[:,1,0]=.5*np.exp(-2j*np.pi*f*1e-9)
    path=tmp_path/'delay.s2p';rf.Network(f=f,s=s,z0=50).write_touchstone(str(path),form='ri')
    entry=ComparisonEntry(str(path))
    full=compare_networks([entry],'raw',0)['curves'][0]
    cropped=compare_networks([entry],'raw',5e9)['curves'][0]
    np.testing.assert_allclose(cropped['columns']['ba_phase_deg'],full['columns']['ba_phase_deg'][f>=5e9])
    assert np.isnan(full['columns']['aa_phase_deg']).all()
    assert np.isneginf(full['columns']['aa_dB']).all()


def test_failed_source_does_not_silently_disappear(tmp_path):
    path=tmp_path/'a.s2p';write_network(path,np.linspace(1e8,8e9,21))
    with pytest.raises(ValueError,match='File row 2'):
        compare_networks([ComparisonEntry(str(path)),ComparisonEntry(str(tmp_path/'missing.s2p'))])
    with pytest.raises(ValueError,match='port'):
        compare_networks([ComparisonEntry(str(path),port_a=3)])


def test_normalizing_selected_ports_preserves_original_matched_loads(tmp_path):
    path=tmp_path/'three.s3p';f=np.linspace(1e8,8e9,11)
    z=np.broadcast_to(np.array([[60,5,8],[5,65,10],[8,10,70]],complex),(len(f),3,3))
    rf.Network(f=f,z=z,z0=[25,75,100]).write_touchstone(str(path),form='ri',write_z0=True)
    result=compare_networks([ComparisonEntry(str(path))],'raw',reference_ohm=50)
    expected_z=z[:,:2,:2]-z[:,:2,2:]@np.linalg.inv(z[:,2:,2:]+100)@z[:,2:,:2]
    expected=rf.Network(f=f,z=expected_z,z0=50)
    np.testing.assert_allclose(result['curves'][0]['columns']['ba_real'],expected.s[:,1,0].real,atol=1e-15)
