"""Touchstone metadata must travel with results without changing network data."""
import hashlib
import json
from pathlib import Path
import numpy as np
import pytest

backend=pytest.importorskip('gds2openEMS')
from gds2openEMS import utilities
from gds2openEMS import util_boxwall as boxwall
rf=pytest.importorskip('skrf')


def decode(path):
    text=Path(path).read_text()
    block=text.split('BEGIN SIMULATION PROVENANCE',1)[1].split('END SIMULATION PROVENANCE',1)[0]
    lines=[]
    for line in block.splitlines():
        line=line.lstrip()
        if line.startswith('!'):line=line[1:].lstrip()
        lines.append(line)
    return json.loads('\n'.join(lines))


@pytest.mark.parametrize('references',[50,[50,75]])
def test_comment_header_roundtrips_and_retains_numeric_payload(tmp_path,references):
    f=np.array([1e9,2e9]);s=np.array([[[.1+.01j,.2],[.2,.15]],[[.12,.21],[.21,.16]]])
    settings={'unit':1e-6,'fstop':2e9,'energy_limit':-60,'engine':'gpu','numThreads':4,
              'openems_boxwall':{'return_kind':'metal','width':5},'reference_plane_shift':{'xmax':100}}
    source=tmp_path/'source.gds';source.write_bytes(b'original input')
    snapshot=utilities.touchstone_provenance(settings,sources={'gds':source},generator={'name':'setupEM'})
    settings['_touchstone_provenance']=snapshot
    source.write_bytes(b'changed AFTER capture')
    expected=hashlib.sha256(b'original input').hexdigest()
    documented=tmp_path/'documented.s2p';plain=tmp_path/'plain.s2p'
    utilities.write_snp(s,f,plain,z0=references)
    utilities.write_snp(s,f,documented,z0=references,provenance=utilities.touchstone_provenance(settings))
    parsed=decode(documented)
    assert parsed['sources']['gds']['sha256']==expected
    assert parsed['settings']['engine']=='gpu' and parsed['settings']['numThreads']==4
    assert parsed['result_kind']=='raw' and parsed['exported_utc']
    assert parsed['network']['samples']==2
    assert parsed['network']['last_frequency_Hz']==2e9
    assert 'util_boxwall.py' in parsed['tool_sources']
    payload=lambda p:[line for line in p.read_text().splitlines() if not line.startswith('!')]
    assert payload(documented)==payload(plain)
    a,b=rf.Network(str(plain)),rf.Network(str(documented))
    np.testing.assert_array_equal(a.s,b.s)
    np.testing.assert_array_equal(a.z0,b.z0)


def test_missing_sources_are_explicit_not_invented(tmp_path):
    result=utilities.touchstone_provenance({},sources={'stackup':tmp_path/'missing.xml'})
    assert result['sources']['stackup']['status']=='unavailable: FileNotFoundError'
    assert 'sha256' not in result['sources']['stackup']


def test_calibration_standard_keeps_own_profile_and_original_inputs(tmp_path):
    original={'fstop':50e9,'model_basename':'device','engine':'gpu'}
    snapshot=utilities.touchstone_provenance(original,sources={'gds':tmp_path/'input.gds'})
    standard=dict(original,_touchstone_provenance=snapshot,model_basename='cal_xmax_L',
                  _touchstone_standard={'length_drawing_units':47.36,'length_factor':1,
                                        'profile':[['M1',-2.5,2.5],['M6',-2.5,2.5]]})
    metadata=utilities.touchstone_provenance(standard,result_kind='calibration_standard')
    assert metadata['input_settings']['model_basename']=='device'
    assert metadata['settings']['model_basename']=='cal_xmax_L'
    assert metadata['calibration_standard']['length_drawing_units']==47.36
    assert '_touchstone_provenance' not in metadata['settings']


def test_calibrated_header_replaces_raw_label_and_retains_sources(tmp_path,monkeypatch):
    f=np.array([1e9,2e9]);s=np.broadcast_to(np.array([[.1,.3],[.3,.2]],complex),(2,2,2)).copy()
    raw=tmp_path/'raw.s2p'
    settings={'unit':1e-6,'fstop':2e9,'reference_plane_shift':{'xmax':20}}
    source=tmp_path/'model.gds';source.write_bytes(b'geometry')
    settings['_touchstone_provenance']=utilities.touchstone_provenance(settings,sources={'gds':source})
    utilities.write_snp(np.moveaxis(s,0,-1),f,raw,provenance=utilities.touchstone_provenance(settings))
    raw_bytes=raw.read_bytes()
    standards=[]
    for i in (1,2):
        p=tmp_path/f'standard{i}.s4p'
        rf.Network(f=f,s=np.zeros((2,4,4),complex),z0=50).write_touchstone(str(p),form='ri')
        standards.append(str(p))
    plan={'device':settings,'messages':['Synthetic test fixture'],
          'analysis':{'warnings':[],'groups':[{'side':'xmax','ports':[1,2],'L':80,'shift':20,
                      'eps_max':3.9,'standards':standards}]}}
    monkeypatch.setattr(boxwall,'calibrate_arrays',lambda *a:(None,{'warnings':[]}))
    monkeypatch.setattr(boxwall,'deembed_arrays',lambda raw,groups:raw*.9)
    result=boxwall.deembed_files(plan,raw)
    header=decode(result)
    assert header['result_kind']=='calibrated'
    assert header['sources']['gds']['sha256']==hashlib.sha256(b'geometry').hexdigest()
    assert header['calibration']['reference_planes'][0]['shift']==20
    assert str(raw) in header['calibration']['source_network_sha256']
    assert Path(result).read_text().count('BEGIN SIMULATION PROVENANCE')==1
    assert raw.read_bytes()==raw_bytes
    np.testing.assert_allclose(rf.Network(result).s,s*.9,atol=1e-7)
