"""Isolated adapters for Volker Muehlhaus's separately installed lumpedmodel tools."""
from dataclasses import replace
from pathlib import Path
from datetime import datetime, timezone
import hashlib
import json
import sys
import numpy as np
try:
    from .network_parameters import _pair
except ImportError:
    from network_parameters import _pair

TOOLS={'inductor_fit':'Wideband inductor (SPICE / Spectre)',
       'pi_from_s2p':'Inductor pi model at target frequency',
       'mim_from_s2p':'MIM capacitor at target frequency',
       'rlgc_from_s2p':'RLGC line at target frequency'}


def default_repository():
    try:
        from .path_config import configured_path
    except ImportError:
        from path_config import configured_path
    configured=configured_path('tools','lumpedmodel')
    if configured:return configured
    for path in ('/usr/cadtools/lumpedmodel','/local/cadtools/lumpedmodel'):
        if Path(path).is_dir():return path
    return ''


def prepare_model_run(network, source, spec, repository, directory, tool,
                      target_hz=3e9, basic=False, spectre=False):
    import skrf as rf
    if tool not in TOOLS:raise ValueError('Unknown lumpedmodel tool.')
    script=Path(repository).expanduser().resolve()/tool/(tool+'.py')
    if not script.is_file():raise ValueError(f'Tool not found: {script}. Select your lumpedmodel checkout.')
    # Always produce a genuine selected two-port, including for open unused ports.
    f,s,refs,valid,_=_pair(network,replace(spec,mode='line'))
    band=(f>=spec.minimum_hz)&((f<=spec.maximum_hz) if spec.maximum_hz else True)
    if band.sum()<4:raise ValueError('Select at least four positive-frequency samples for model extraction.')
    if not valid[band].all() or not np.isfinite(s[band]).all():raise ValueError('Selected band contains undefined samples; change the band or terminations.')
    f=f[band]
    if tool!='inductor_fit' and not (f[0]<=target_hz<f[-1]):raise ValueError('Target frequency must be inside the selected band and below its last sample.')
    if tool=='rlgc_from_s2p' and spec.line_length_m<=0:raise ValueError('Enter the physical line length in the Parameters tab first.')
    pair=rf.Network(f=f,s=s[band],z0=refs[band],s_def=network.s_def)
    names=getattr(network,'port_names',None)
    if names:pair.port_names=[names[spec.port_a-1],names[spec.port_b-1]]
    pair.renormalize(50.)  # scripts assume a common real scalar reference
    folder=Path(directory).expanduser().resolve()
    folder.mkdir(parents=True,exist_ok=False)  # no accidental overwrite of prior fits
    input_path=folder/'selected_ports.s2p'
    pair.comments=(network.comments or '')+f'\nsetupEM selected ports {spec.port_a}/{spec.port_b}; unused ports {spec.unused_ports}; renormalized to 50 ohm.\nSource SHA256: '+str(source.get('sha256',''))
    pair.write_touchstone(str(input_path),form='ri')
    args=[str(input_path)]
    if tool=='inductor_fit':
        if basic:args.append('--basic')
        if spectre:args.append('--spectre')
    else:
        args.append(str(target_hz/1e9))
        if tool=='rlgc_from_s2p':args.extend([str(spec.line_length_m*1e6),'50'])
    report=dict(schema='setupEM.lumped-model.v1',created_utc=datetime.now(timezone.utc).isoformat(),
                source=dict(source),tool=tool,script=str(script),script_sha256=hashlib.sha256(script.read_bytes()).hexdigest(),
                selected_ports=[spec.port_a,spec.port_b],unused_ports=spec.unused_ports,
                band_Hz=[float(f[0]),float(f[-1])],target_Hz=float(target_hz) if tool!='inductor_fit' else None,
                line_length_m=spec.line_length_m if tool=='rlgc_from_s2p' else None,
                normalization_ohm=50,scikit_rf_version=rf.__version__,numpy_version=np.__version__,
                adapter_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                python=sys.executable,arguments=args,status='prepared',
                note='No DC point synthesized. Circuit DC values are extrapolated from an AC fit; inspect fit diagnostics.')
    (folder/'run.json').write_text(json.dumps(report,indent=2)+'\n')
    return [sys.executable,'-u',str(Path(__file__).with_name('lumped_model_worker.py')),str(script),*args],folder
