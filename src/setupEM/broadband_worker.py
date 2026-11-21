"""Isolated snp2le core conversion. Its process-global redirects never touch Qt."""
from pathlib import Path
from datetime import datetime,timezone
from dataclasses import asdict
import hashlib
import json
import sys
import threading
import numpy as np
try:
    from .broadband_model import BroadbandSpec,validate_spec,json_safe,sample_diagnostics
except ImportError:
    from broadband_model import BroadbandSpec,validate_spec,json_safe,sample_diagnostics


def run(job):
    folder=job.parent;manifest=json.loads(job.read_text());spec=BroadbandSpec(**manifest['specification']);validate_spec(spec)
    from snp2le.core import engine,io,netlist
    from snp2le.core.state import ConverterState
    import snp2le,skrf as rf
    snapshot=folder/manifest['input_snapshot']
    if hashlib.sha256(snapshot.read_bytes()).hexdigest()!=manifest['source']['sha256']:
        raise ValueError('Input snapshot hash mismatch; no fit performed.')
    network=io.load_touchstone(str(snapshot))
    state=ConverterState(mode='universal',max_order=spec.maximum_order,
        enforce_passivity=spec.enforce_passivity,passivity_ceiling=spec.passivity_ceiling,
        convex_max_states=spec.convex_max_states,thermal_noise=spec.thermal_noise,dc_pin=spec.dc_pin,
        dc_pin_fc=spec.dc_pin_corner_hz,dc_island_leak=spec.dc_island_leak_siemens,
        f_min=spec.minimum_hz or None,f_max=spec.maximum_hz or None,source_path=manifest['source']['path'])
    stream=sys.stdout;lock=threading.Lock()
    def progress(fraction,message):
        # snp2le temporarily redirects sys.stdout/stderr while fitting.
        with lock:
            stream.write('@setupEM-progress '+json.dumps(dict(fraction=float(fraction),message=message))+'\n');stream.flush()
    result=engine.convert(state,network,progress=progress)
    core=Path(engine.__file__).parent
    report=dict(ok=bool(result.ok),error=result.error,source=manifest['source'],specification=manifest['specification'],
        tool=dict(name='snp2le',version=snp2le.__version__,
        scikit_rf_version=rf.__version__,core_hashes={str(p.relative_to(core)):hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(core.rglob('*.py'))}),
        engine_state=asdict(state),n_ports=int(result.n_ports),maximum_order_requested=spec.maximum_order,
        actual_model_order=result.model_order,n_poles=result.n_poles,engine_rms_error=result.rms_error,
        passive=result.passive,passivity_ceiling=result.passivity_ceiling,passivity_path=result.passivity_path,
        sigma_max=result.sigma_max,sigma_max_frequency_Hz=result.sigma_max_freq,
        dc_health=result.dc,dc_pin=result.dc_pin,noise=result.noise,band_limited=result.band_limited,
        messages=list(result.messages),subcircuit=netlist.safe_subckt_name(spec.subcircuit),
        dc_sampling='Fitted Touchstone exports contain positive-frequency fit samples. DC behavior is in the circuit model and diagnostics, not an invented solver sample.')
    if not result.ok:raise ConversionFailure(report)
    if spec.thermal_noise and (result.noise is None or not result.noise.ok):
        report.update(ok=False,error='Requested thermal noise was not generated; no netlists exported. Review noise diagnostics.')
        raise ConversionFailure(report)
    if not np.isfinite(result.model_s).all():raise ValueError('Engine returned undefined model samples.')
    uniform,_=io.uniform_reference(network);reference=float(uniform.z0[0,0].real)
    report.update(reference_ohm=reference,fit_band_Hz=[float(result.freq[0]),float(result.freq[-1])],
                  samples=int(len(result.freq)),**sample_diagnostics(result.data_s,result.model_s))
    if not manifest['has_finite_source_DC']:
        report['messages'].append('No finite source DC point: circuit DC behavior is extrapolated from AC data. DC pin is inactive.')
    if not result.passive:report['messages'].append('The returned fit does not meet the selected passivity ceiling. Review before circuit simulation.')
    if spec.passivity_ceiling>1:report['messages'].append('The selected ceiling permits nonpassivity; a ceiling above 1.0 is not strict passivity.')
    result.ir.name=report['subcircuit']
    result.ir.comments=['setupEM universal broadband fit; source: '+manifest['source']['path'],
        'Source SHA256: '+manifest['source']['sha256'],
        f'Fit band: {report["fit_band_Hz"][0]:g} to {report["fit_band_Hz"][1]:g} Hz; maximum order {spec.maximum_order}',
        'See run.json and fit_report.json for original metadata and diagnostics.']+result.ir.comments
    result.ir.notes.extend('Source metadata: '+line for line in manifest['source'].get('comments','').splitlines())
    dialects=('ngspice','vacask','xyce') if spec.dialect=='all' else (spec.dialect,)
    for dialect in dialects:
        path=folder/(report['subcircuit']+'.'+netlist.EXTENSION[dialect])
        with path.open('x',encoding='utf-8') as file:file.write(netlist.render(result.ir,dialect))
    for name,s in [('normalized_data',result.data_s),('fitted',result.model_s)]:
        path=folder/f'{name}.s{result.n_ports}p'
        if path.exists():raise FileExistsError(path)
        net=rf.Network(f=result.freq,s=s,z0=reference)
        net.port_names=getattr(network,'port_names',None)
        net.comments=manifest['source'].get('comments','')+f'\nsetupEM: {name}, snp2le universal fit. Source SHA256: '+manifest['source']['sha256']+'\nPositive native fit frequencies; not a new EM simulation. See fit_report.json.\n'
        net.write_touchstone(str(path),form='ri')
    with (folder/'fit_arrays.npz').open('xb') as stream:
        np.savez_compressed(stream,frequency_hz=result.freq,data_s=result.data_s,model_s=result.model_s)
    return json_safe(report)


class ConversionFailure(Exception):
    def __init__(self,report):self.report=report;super().__init__(report['error'])


if __name__=='__main__':
    job=Path(sys.argv[1]).resolve();manifest=json.loads(job.read_text())
    code=0
    try:report=run(job)
    except ConversionFailure as error:report=json_safe(error.report);code=1
    except Exception as error:
        import traceback
        traceback.print_exc();report=dict(ok=False,error=f'{type(error).__name__}: {error}');code=1
    (job.parent/'fit_report.json').write_text(json.dumps(report,indent=2,allow_nan=False)+'\n')
    manifest.update(status='complete' if code==0 else 'failed',exit_code=code,finished_utc=datetime.now(timezone.utc).isoformat(),
        outputs=[dict(name=p.name,sha256=hashlib.sha256(p.read_bytes()).hexdigest()) for p in sorted(job.parent.iterdir()) if p.is_file() and p.name not in ('run.json','console.log')])
    job.write_text(json.dumps(manifest,indent=2)+'\n')
    print('Broadband model '+manifest['status']+': '+str(job.parent),flush=True)
    sys.exit(code)
