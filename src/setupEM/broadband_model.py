"""Snapshot preparation and diagnostics for the optional snp2le universal engine."""
from dataclasses import dataclass,asdict,is_dataclass
from datetime import datetime,timezone
from pathlib import Path
import hashlib
import json
import sys
import os
import numpy as np
try:
    from .network_parameters import load_touchstone
except ImportError:
    from network_parameters import load_touchstone


@dataclass(frozen=True)
class BroadbandSpec:
    maximum_order: int = 6
    minimum_hz: float = 0.
    maximum_hz: float = 0.
    enforce_passivity: bool = True
    passivity_ceiling: float = 1.
    convex_max_states: int = 100
    thermal_noise: bool = False
    dc_pin: bool = True
    dc_pin_corner_hz: float = 160.
    dc_island_leak_siemens: float = 0.
    dialect: str = 'all'
    subcircuit: str = 'broadband_model'


def default_engine_python():
    override=os.environ.get('EMS_BROADBAND_PYTHON')
    if override:return override
    checkout=Path(__file__).resolve().parents[2]
    for candidate in (checkout/'.tools/snp2le-env/bin/python',checkout/'.tools/snp2le-env/Scripts/python.exe'):
        if candidate.is_file():return str(candidate)
    return sys.executable


def validate_spec(spec):
    if isinstance(spec.maximum_order,bool) or int(spec.maximum_order)!=spec.maximum_order or spec.maximum_order<2:
        raise ValueError('Maximum order must be an integer of at least 2 (real poles + twice complex pole pairs).')
    if not np.isfinite([spec.minimum_hz,spec.maximum_hz,spec.passivity_ceiling,spec.dc_pin_corner_hz,spec.dc_island_leak_siemens]).all():
        raise ValueError('Frequency, passivity and DC options must be finite.')
    if spec.minimum_hz<0 or spec.maximum_hz<0 or (spec.maximum_hz and spec.maximum_hz<=spec.minimum_hz):
        raise ValueError('Fit band must increase; zero means the file edge.')
    if not 1<=spec.passivity_ceiling<=1.2:raise ValueError('Passivity ceiling must be between 1.0 and 1.2.')
    if int(spec.convex_max_states)!=spec.convex_max_states or spec.convex_max_states<0:raise ValueError('Convex state limit must be an integer of zero or more.')
    if spec.dc_pin_corner_hz<=0 or spec.dc_island_leak_siemens<0:raise ValueError('DC pin corner must be positive and leak conductance nonnegative.')
    if spec.dialect not in ('all','ngspice','vacask','xyce'):raise ValueError('Unknown netlist dialect.')
    if not spec.subcircuit.strip():raise ValueError('Enter a subcircuit name.')
    if spec.thermal_noise and (not spec.enforce_passivity or spec.passivity_ceiling!=1):
        raise ValueError('Thermal-noise generation requires strict passivity enforcement (ceiling 1.0).')


def prepare_broadband_run(filename,spec,directory,python_executable=None):
    validate_spec(spec)
    network,source=load_touchstone(filename)
    f=network.f
    if not len(f) or not np.isfinite(f).all() or np.any(f<0) or np.any(np.diff(f)<=0):
        raise ValueError('Source frequencies must be finite, nonnegative and strictly increasing.')
    band=(f>0)&(f>=spec.minimum_hz)&((f<=spec.maximum_hz) if spec.maximum_hz else True)
    if band.sum()<4:raise ValueError('The fit band needs at least four positive native samples.')
    if not np.isfinite(network.s[band]).all():raise ValueError('Selected fit band contains undefined S-parameters.')
    if not np.isfinite(network.z0[band]).all() or np.any(network.z0[band].real<=0):raise ValueError('Reference impedances must be finite with positive real part.')
    folder=Path(directory).expanduser().resolve();folder.mkdir(parents=True,exist_ok=False)
    snapshot=folder/f'input.s{network.nports}p'
    contents=Path(source['path']).read_bytes()
    if hashlib.sha256(contents).hexdigest()!=source['sha256']:raise ValueError('Source changed while preparing the run. Load it again.')
    with snapshot.open('xb') as stream:stream.write(contents)
    interpreter=str(Path(python_executable or default_engine_python()).expanduser().absolute())
    report=dict(schema='setupEM.broadband-model.v1',created_utc=datetime.now(timezone.utc).isoformat(),
        source=source,specification=asdict(spec),input_snapshot=snapshot.name,n_ports=int(network.nports),
        original_port_names=getattr(network,'port_names',None),requested_band_Hz=[spec.minimum_hz,spec.maximum_hz],
        selected_positive_samples=int(band.sum()),has_finite_source_DC=bool(f[0]==0 and np.isfinite(network.s[0]).all()),
        status='prepared',python=interpreter,
        adapter_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        worker_sha256=hashlib.sha256(Path(__file__).with_name('broadband_worker.py').read_bytes()).hexdigest())
    job=folder/'run.json';job.write_text(json.dumps(report,indent=2)+'\n')
    return [interpreter,'-u',str(Path(__file__).with_name('broadband_worker.py')),str(job)],folder


def json_safe(value):
    if is_dataclass(value):value=asdict(value)
    if isinstance(value,dict):return {str(k):json_safe(v) for k,v in value.items()}
    if isinstance(value,(list,tuple)):return [json_safe(v) for v in value]
    if isinstance(value,np.ndarray):return json_safe(value.tolist())
    if isinstance(value,np.generic):return json_safe(value.item())
    if isinstance(value,float) and not np.isfinite(value):return None
    return value


def sample_diagnostics(data,model):
    difference=np.asarray(model)-np.asarray(data)
    rms=np.sqrt(np.mean(abs(difference)**2,axis=0));peak=np.max(abs(difference),axis=0)
    scale=np.sqrt(np.mean(abs(data)**2,axis=0))
    traces=[]
    for i in range(rms.shape[0]):
        for j in range(rms.shape[1]):traces.append(dict(response_port=i+1,excited_port=j+1,
            rms_abs_S_error=float(rms[i,j]),maximum_abs_S_error=float(peak[i,j]),
            relative_rms_percent=float(100*rms[i,j]/scale[i,j]) if scale[i,j]>0 else None))
    return dict(sampled_rms_abs_S_error=float(np.sqrt(np.mean(abs(difference)**2))),
                sampled_max_abs_S_error=float(np.max(abs(difference))),traces=traces)
