from dataclasses import replace
from pathlib import Path
import hashlib
import json
import os
import subprocess
import numpy as np
import pytest
import skrf as rf
from setupEM.broadband_model import BroadbandSpec,prepare_broadband_run,sample_diagnostics,validate_spec,default_engine_python


@pytest.fixture
def engine_python():
    python=default_engine_python()
    probe=subprocess.run([python,'-c','import snp2le'],capture_output=True,text=True,timeout=20)
    if probe.returncode:pytest.skip('Optional snp2le engine is not installed in '+python)
    return python


def source_network(path,ports=2,dc=True):
    f=np.linspace(1e6,10e9,101)
    if dc:f=np.r_[0.,f]
    y=np.zeros((len(f),ports,ports),complex)
    for a in range(0,ports,2):
        branch=1/(3+a+2j*np.pi*f*1e-9)
        y[:,a,a]=y[:,a+1,a+1]=branch+.001
        y[:,a,a+1]=y[:,a+1,a]=-branch
    net=rf.Network(f=f,y=y,z0=50);net.comments='Synthetic RL fixture; known shunt conductance; no proprietary stackup.'
    net.write_touchstone(str(path),form='ri')
    return net


@pytest.mark.parametrize('ports',[2,4])
def test_real_universal_worker_preserves_all_ports_and_exports_diagnostics(tmp_path,ports,engine_python):
    path=tmp_path/f'source.s{ports}p';net=source_network(path,ports,dc=ports==2);original=path.read_bytes()
    command,folder=prepare_broadband_run(path,BroadbandSpec(maximum_order=6,subcircuit='RF fixture'),tmp_path/'fit',engine_python)
    env=dict(os.environ,OPENBLAS_NUM_THREADS='1',OMP_NUM_THREADS='1',MKL_NUM_THREADS='1')
    process=subprocess.run(command,cwd=folder,env=env,capture_output=True,text=True,timeout=120)
    assert process.returncode==0,process.stdout+process.stderr
    manifest=json.loads((folder/'run.json').read_text());report=json.loads((folder/'fit_report.json').read_text())
    assert manifest['status']=='complete' and manifest['n_ports']==ports and report['ok']
    assert manifest['source']['sha256']==hashlib.sha256(original).hexdigest()
    assert (folder/manifest['input_snapshot']).read_bytes()==original and path.read_bytes()==original
    assert report['n_ports']==ports and len(report['traces'])==ports**2
    assert 0<report['actual_model_order']<=6
    fitted=rf.Network(str(folder/f'fitted.s{ports}p'));data=rf.Network(str(folder/f'normalized_data.s{ports}p'))
    np.testing.assert_array_equal(fitted.f,net.f[net.f>0])
    np.testing.assert_array_equal(fitted.f,data.f)
    assert report['sampled_max_abs_S_error']<.002
    assert '@setupEM-progress' in process.stdout
    if ports==2:assert report['dc_pin'] is not None
    else:assert any('No finite source DC' in line for line in report['messages'])
    for extension in ('spice','inc','cir'):
        text=(folder/(report['subcircuit']+'.'+extension)).read_text()
        assert report['subcircuit'] in text and manifest['source']['sha256'] in text
        assert 'Synthetic RL fixture' in text
    with np.load(folder/'fit_arrays.npz') as arrays:assert arrays['model_s'].shape==(101,ports,ports)
    with pytest.raises(FileExistsError):prepare_broadband_run(path,BroadbandSpec(),folder)


def test_spec_rejects_invalid_band_and_unsupported_noise_conditions(tmp_path):
    default=BroadbandSpec()
    for spec in (replace(default,maximum_order=1),replace(default,maximum_hz=1,minimum_hz=2),
                 replace(default,dc_pin_corner_hz=0),replace(default,passivity_ceiling=1.3),
                 replace(default,thermal_noise=True,enforce_passivity=False)):
        with pytest.raises(ValueError):validate_spec(spec)
    source=tmp_path/'source.s2p';source_network(source)
    with pytest.raises(ValueError,match='four positive'):prepare_broadband_run(source,replace(default,minimum_hz=20e9),tmp_path/'bad')
    assert not (tmp_path/'bad').exists()


def test_trace_diagnostics_report_zero_response_as_undefined_relative_error():
    data=np.zeros((5,2,2),complex);model=data.copy();model[:,0,0]=.01
    result=sample_diagnostics(data,model)
    assert result['sampled_rms_abs_S_error']==pytest.approx(.005)
    assert result['traces'][0]['relative_rms_percent'] is None


def test_requested_thermal_noise_is_generated_and_reported(tmp_path,engine_python):
    path=tmp_path/'source.s2p';source_network(path,2,True)
    command,folder=prepare_broadband_run(path,BroadbandSpec(thermal_noise=True),tmp_path/'thermal',engine_python)
    process=subprocess.run(command,cwd=folder,env=dict(os.environ,OPENBLAS_NUM_THREADS='1',OMP_NUM_THREADS='1'),capture_output=True,text=True,timeout=120)
    assert process.returncode==0,process.stdout+process.stderr
    report=json.loads((folder/'fit_report.json').read_text())
    assert report['noise']['ok'] and report['engine_state']['thermal_noise']
    assert report['noise']['n_sources']==2
