import numpy as np
import pytest
import skrf as rf
from setupEM.dc_extension import extend_dc,export_dc


def test_skrf_dc_keeps_native_samples_and_known_series_resistance(tmp_path):
    f=np.array([1e4,2e4,5e4,1e5,2e6])
    z=3+2j*np.pi*f*2e-9
    s=np.zeros((len(f),2,2),complex)
    s[:,0,0]=s[:,1,1]=z/(100+z);s[:,0,1]=s[:,1,0]=100/(100+z)
    net=rf.Network(f=f,s=s,z0=50);before=net.s.copy()
    extended,report=extend_dc(net,{'path':'original.s2p','sha256':'source'})
    assert extended.f[0]==0 and len(extended)==len(net)+1
    np.testing.assert_array_equal(extended.f[1:],net.f)
    np.testing.assert_array_equal(extended.s[1:],before)
    np.testing.assert_array_equal(net.s,before)
    np.testing.assert_allclose(extended.s[0],[[3/103,100/103],[100/103,3/103]],atol=1e-10)
    assert report['samples_used']==2
    path=tmp_path/'dc.s2p';export_dc(extended,report,path)
    loaded=rf.Network(str(path));np.testing.assert_allclose(loaded.s,extended.s,atol=1e-15)
    assert 'EXTRAPOLATED DC' in loaded.comments
    original=path.read_bytes()
    with pytest.raises(FileExistsError):export_dc(extended,report,path)
    assert path.read_bytes()==original


def test_real_fit_unequal_references_roundtrip_and_validation(tmp_path):
    f=np.array([1.,3.,7.,10.])*1e6
    dc=np.array([[.2,.3],[.3,.1]])
    s=dc[None]+f[:,None,None]*np.array([[1e-9,2e-9],[2e-9,-1e-9]])
    net=rf.Network(f=f,s=s,z0=[50,75])
    extended,report=extend_dc(net,{},'cartesian',4)
    np.testing.assert_allclose(extended.s[0],dc,atol=1e-14)
    path=tmp_path/'unequal.s2p';export_dc(extended,report,path)
    loaded=rf.Network(str(path));np.testing.assert_array_equal(loaded.z0,extended.z0)
    np.testing.assert_allclose(loaded.s,extended.s,atol=1e-15)
    with pytest.raises(ValueError,match='Existing DC'):extend_dc(extended,{})
    with pytest.raises(ValueError,match='sample count'):extend_dc(net,{},'cartesian',99)
    net.z0[1,0]=51
    with pytest.raises(ValueError,match='frequency-dependent'):extend_dc(net,{})


def test_nonpassive_estimate_is_reported_without_silent_clipping():
    net=rf.Network(f=[1e6,2e6],s=np.array([[[1.1]],[[1.0]]]),z0=50)
    extended,report=extend_dc(net,{})
    assert extended.s[0,0,0].real==pytest.approx(1.2)
    assert report['dc_max_singular_value']>1
    assert any('nonpassive' in w for w in report['warnings'])


def test_multiport_dc_export_preserves_matrix_order_and_existing_sidecar(tmp_path):
    rng=np.random.default_rng(10)
    s=(rng.normal(size=(6,4,4))+1j*rng.normal(size=(6,4,4)))*.01
    net=rf.Network(f=np.arange(1,7)*1e6,s=s,z0=[25,50,75,100])
    extended,report=extend_dc(net,{},'cartesian',4)
    path=tmp_path/'four.s4p';export_dc(extended,report,path)
    loaded=rf.Network(str(path))
    np.testing.assert_allclose(loaded.s,extended.s,atol=1e-16)
    np.testing.assert_array_equal(loaded.z0,extended.z0)
    blocked=tmp_path/'blocked.dc.json';blocked.write_text('existing report')
    with pytest.raises(FileExistsError):export_dc(extended,report,tmp_path/'blocked.s4p')
    assert blocked.read_text()=='existing report' and not (tmp_path/'blocked.s4p').exists()
