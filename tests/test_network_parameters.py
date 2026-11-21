"""Analytical circuits and distributed lines, independent of any PDK or solver."""
import json
import numpy as np
import pytest
import skrf as rf
from setupEM.network_parameters import ExtractionSpec,extract_parameters,export_parameters,load_touchstone


def network_from_differential(f,zd,z0=50):
    z=np.ones((len(f),2,2),complex)*100
    z+=zd[:,None,None]*np.array([[1,-1],[-1,1]])/4
    return rf.Network(f=f,z=z,z0=z0)


def test_series_inductor_with_unequal_references():
    f=np.linspace(1e8,8e9,101);zd=2+2j*np.pi*f*2e-9
    n=network_from_differential(f,zd,z0=np.broadcast_to([50,75],(len(f),2)))
    original=n.s.copy()
    result=extract_parameters(n)
    np.testing.assert_allclose(result.columns['L_H'],2e-9,rtol=1e-10)
    np.testing.assert_allclose(result.columns['R_ohm'],2,rtol=1e-10)
    np.testing.assert_allclose(result.columns['Q'],zd.imag/2,rtol=1e-10)
    np.testing.assert_array_equal(n.s,original)


def test_floating_inductor_has_unique_differential_voltage():
    f=np.linspace(1e8,8e9,31);zd=2+2j*np.pi*f*2e-9
    reflection=zd/(100+zd);transmission=100/(100+zd)
    s=np.empty((len(f),2,2),complex)
    s[:,0,0]=s[:,1,1]=reflection;s[:,0,1]=s[:,1,0]=transmission
    n=rf.Network(f=f,s=s,z0=50)
    result=extract_parameters(n)
    np.testing.assert_allclose(result.columns['R_ohm'],2,atol=1e-10)
    np.testing.assert_allclose(result.columns['L_H'],2e-9,rtol=1e-10)


@pytest.mark.parametrize('termination',['matched','open'])
def test_multiselect_uses_physical_unused_port_termination(termination):
    f=np.linspace(1e8,4e9,31)
    resistance=np.diag([3,4,5,6])+np.ones((4,4))*.2
    inductance=(np.diag([2,3,4,5])+np.ones((4,4))*.3)*1e-9
    z=resistance[None]+2j*np.pi*f[:,None,None]*inductance
    refs=np.broadcast_to([50,60,70,80],(len(f),4))
    n=rf.Network(f=f,z=z,z0=refs)
    pair=[3,1];other=[0,2]
    effective=z[:,pair][:,:,pair]
    if termination=='matched':
        aa=z[:,pair][:,:,other];bb=z[:,other][:,:,other]+np.diag([50,70])
        ba=z[:,other][:,:,pair]
        effective=effective-aa@np.linalg.solve(bb,ba)
    expected=effective[:,0,0]-effective[:,0,1]-effective[:,1,0]+effective[:,1,1]
    result=extract_parameters(n,ExtractionSpec(port_a=4,port_b=2,unused_ports=termination))
    np.testing.assert_allclose(result.columns['R_ohm'],expected.real,rtol=1e-9)
    np.testing.assert_allclose(result.columns['X_ohm'],expected.imag,rtol=1e-9)
    assert result.summary['selected_ports']==[4,2]
    assert result.summary['unused_ports']==termination


def test_native_peak_and_reactance_zero_no_smoothing():
    f=np.array([.1,1,2,3,4])*1e9;zd=1+1j*np.array([1,10,12,6,-4])
    result=extract_parameters(network_from_differential(f,zd))
    assert result.summary['peak_Q']==pytest.approx(12)
    assert result.summary['peak_Q_frequency_Hz']==2e9
    assert result.summary['reactance_zero_Hz']==pytest.approx(3.6e9)
    assert result.columns['L_H'][-1]<0


def line_network(f,length,R=120,L=400e-9,G=.002,C=160e-12):
    w=2*np.pi*f;z=R+1j*w*L;y=G+1j*w*C
    gamma=np.sqrt(z*y);zc=np.sqrt(z/y)
    A=np.cosh(gamma*length);D=A;B=zc*np.sinh(gamma*length);Cc=np.sinh(gamma*length)/zc
    den=A+B/50+Cc*50+D
    s=np.empty((len(f),2,2),complex)
    s[:,0,0]=(A+B/50-Cc*50-D)/den
    s[:,1,1]=(-A+B/50-Cc*50+D)/den
    s[:,1,0]=2/den;s[:,0,1]=2*(A*D-B*Cc)/den
    return rf.Network(f=f,s=s,z0=50),gamma,zc


@pytest.mark.parametrize('lossless',[False,True])
def test_distributed_rlgc_and_phase_wraps(lossless):
    f=np.linspace(1e7,20e9,1001);length=.025
    R,G=(0,0) if lossless else (120,.002)
    n,gamma,zc=line_network(f,length,R=R,G=G)
    result=extract_parameters(n,ExtractionSpec(mode='line',line_length_m=length,minimum_hz=0))
    np.testing.assert_allclose(result.columns['beta_rad_per_m'],gamma.imag,rtol=1e-10,atol=1e-8)
    np.testing.assert_allclose(result.columns['Zc_real_ohm'],zc.real,rtol=1e-10)
    np.testing.assert_allclose(result.columns['L_H_per_m'],400e-9,rtol=1e-10)
    np.testing.assert_allclose(result.columns['C_F_per_m'],160e-12,rtol=1e-10)
    np.testing.assert_allclose(result.columns['R_ohm_per_m'],R,rtol=1e-8,atol=1e-8)
    np.testing.assert_allclose(result.columns['G_S_per_m'],G,rtol=1e-8,atol=1e-10)
    assert result.summary['max_uniform_line_residual']<1e-9
    # Selecting a high display band must NOT restart phase unwrapping there.
    high=extract_parameters(n,ExtractionSpec(mode='line',line_length_m=length,minimum_hz=10e9))
    np.testing.assert_allclose(high.columns['beta_rad_per_m'],gamma.imag[f>=10e9],rtol=1e-10)


def test_length_and_port_validation():
    n,_,_=line_network(np.linspace(1e8,1e9,11),.001)
    with pytest.raises(ValueError,match='physical uniform-line length'):extract_parameters(n,ExtractionSpec(mode='line'))
    with pytest.raises(ValueError,match='different ports'):extract_parameters(n,ExtractionSpec(port_a=1,port_b=1))
    with pytest.raises(ValueError,match='fewer than two'):extract_parameters(n,ExtractionSpec(minimum_hz=20e9))


def test_csv_and_source_provenance_roundtrip_preserves_input(tmp_path):
    f=np.linspace(1e8,1e9,11);n=network_from_differential(f,2+2j*np.pi*f*2e-9)
    path=tmp_path/'source.s2p';n.write_touchstone(str(path),form='ri')
    original=path.read_bytes();loaded,source=load_touchstone(path)
    result=extract_parameters(loaded,source=source)
    csv_path,json_path=export_parameters(result,tmp_path/'derived.csv')
    saved=json.loads(json_path.read_text())
    assert saved['source']['sha256']==source['sha256']
    assert saved['specification']['port_a']==1
    assert 'frequency_Hz,L_H,R_ohm,X_ohm,Q' in csv_path.read_text()
    assert path.read_bytes()==original
    with pytest.raises(ValueError,match='already exists'):export_parameters(result,csv_path)


def test_line_open_unused_disconnected_ports_and_unequal_references():
    f=np.linspace(1e8,5e9,201)
    n,gamma,zc=line_network(f,.01)
    n.renormalize([50,75])
    s=np.zeros((len(f),4,4),complex)
    s[:,:2,:2]=n.s
    # Perfectly open, uncoupled extra ports make the full Z matrix undefined,
    # but cannot change the selected line's response.
    s[:,2,2]=s[:,3,3]=1
    full=rf.Network(f=f,s=s,z0=np.broadcast_to([50,75,60,80],(len(f),4)))
    result=extract_parameters(full,ExtractionSpec(mode='line',line_length_m=.01,unused_ports='open'))
    np.testing.assert_allclose(result.columns['beta_rad_per_m'],gamma.imag,rtol=1e-9)
    np.testing.assert_allclose(result.columns['L_H_per_m'],400e-9,rtol=1e-9)
    assert result.summary['invalid_samples']==0


def test_nonuniform_line_is_flagged_as_effective_approximation():
    f=np.linspace(1e8,8e9,201)
    n,_,_=line_network(f,.01)
    # Unequal shunt loading at the output is a launch, not a uniform line.
    line_abcd=n.a
    shunt=np.broadcast_to(np.eye(2),(len(f),2,2)).copy().astype(complex)
    shunt[:,1,0]=2j*np.pi*f*1e-12
    bad=rf.Network(f=f,a=line_abcd@shunt,z0=50)
    result=extract_parameters(bad,ExtractionSpec(mode='line',line_length_m=.01))
    assert result.summary['max_uniform_line_residual']>.02
    assert any('effective approximation' in warning for warning in result.warnings)


def test_singular_sample_is_not_smoothed_or_regularized(tmp_path):
    f=np.array([1,2,3])*1e9
    n=network_from_differential(f,2+2j*np.pi*f*2e-9)
    s=n.s.copy();s[1]=np.eye(2);n.s=s
    result=extract_parameters(n)
    assert result.summary['invalid_samples']==1
    assert np.isnan(result.columns['L_H'][1])
    assert result.frequency_hz.tolist()==f.tolist()
    assert result.columns['L_H'][0]==pytest.approx(2e-9)
    path,meta=export_parameters(result,tmp_path/'with_gap.csv')
    assert 'nan' in path.read_text()
    json.loads(meta.read_text())


def test_dc_is_excluded_and_line_branch_offset_is_explicit():
    f=np.array([0,1,2])*1e9
    n=network_from_differential(f,2+2j*np.pi*f*2e-9)
    result=extract_parameters(n)
    assert result.summary['dc_or_nonpositive_samples_excluded']==1
    assert result.frequency_hz.tolist()==[1e9,2e9]
    n,gamma,_=line_network(np.linspace(1e8,2e9,31),.01)
    shifted=extract_parameters(n,ExtractionSpec(mode='line',line_length_m=.01,phase_branch=1))
    np.testing.assert_allclose(shifted.columns['beta_rad_per_m'],gamma.imag+2*np.pi/.01,rtol=1e-9)
    assert shifted.provenance['specification']['phase_branch']==1
