"""Explicit DC estimates; native positive-frequency samples remain unchanged."""
from datetime import datetime, timezone
from pathlib import Path
import hashlib
import json
import numpy as np


def extend_dc(network, source, method='skrf', samples=4):
    import skrf as rf
    f=np.asarray(network.f)
    if len(f) and f[0]==0:
        raise ValueError('Source already contains a DC point (0 Hz). Existing DC is never replaced; use the original file or load a source without DC.')
    if len(f)<2 or not np.isfinite(f).all() or f[0]<=0 or np.any(np.diff(f)<=0):
        raise ValueError('Need at least two strictly increasing, finite positive frequencies.')
    if not np.isfinite(network.s).all():raise ValueError('Source contains undefined S-parameters.')
    refs=np.asarray(network.z0)
    if not np.isfinite(refs).all() or np.any(refs.real<=0) or np.any(abs(refs.imag)>1e-10):
        raise ValueError('DC estimation requires real, positive reference impedances.')
    if not np.allclose(refs,refs[0],rtol=1e-12,atol=1e-12):
        raise ValueError('Renormalize frequency-dependent reference impedances before estimating DC.')
    if method=='skrf':
        # Request only two output points to bound memory independently of fmin/df.
        # Only row zero is used; skrf resampling never changes our native rows.
        dc=network.extrapolate_to_dc(points=2,kind='linear').s[0].real
        used=2
    elif method=='cartesian':
        used=int(samples)
        if used<2 or used>len(f):raise ValueError('Low-frequency fit sample count must be between 2 and the source sample count.')
        x=f[:used]/f[used-1]
        dc=np.linalg.lstsq(np.column_stack([np.ones(used),x]),network.s[:used].real.reshape(used,-1),rcond=None)[0][0].reshape(network.nports,network.nports)
    else:raise ValueError('Unknown DC estimation method.')
    if not np.isfinite(dc).all():raise ValueError('DC estimate is undefined.')
    reference=network.s[0].real-f[0]*(network.s[1].real-network.s[0].real)/(f[1]-f[0])
    max_singular=float(np.linalg.svd(dc,compute_uv=False)[0])
    warnings=['Extrapolated DC is not a magnetostatic/conduction solution or a validated DC resistance. Review against known connectivity and resistance.',
              'Adding a DC point alone does not establish broadband passivity, causality, or transient accuracy. No passivity correction is applied.']
    if max_singular>1+1e-8:warnings.append('The DC estimate is nonpassive (largest S singular value exceeds 1). Do not use without review.')
    if f[0]>f[1]-f[0]:warnings.append('The gap to DC exceeds the first frequency step; lower-frequency simulation would improve confidence.')
    result=rf.Network(f=np.r_[0.,f],s=np.concatenate([dc[None],network.s]),
                      z0=np.concatenate([refs[:1],refs]),name=network.name,s_def=network.s_def)
    result.port_names=getattr(network,'port_names',None)
    report=dict(schema='setupEM.dc-extension.v1',created_utc=datetime.now(timezone.utc).isoformat(),
                source=dict(source),method=method,scikit_rf_version=rf.__version__,samples_used=used,
                implementation_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),numpy_version=np.__version__,
                estimation_band_Hz=[float(f[0]),float(f[used-1])],native_positive_samples_unchanged=True,
                dc_s_real=dc.tolist(),dc_max_singular_value=max_singular,
                max_difference_from_two_point_cartesian=float(np.max(abs(dc-reference))),warnings=warnings)
    if network.nports==2:
        try:
            from .network_parameters import _differential_impedance
        except ImportError:
            from network_parameters import _differential_impedance
        impedance,valid=_differential_impedance(dc[None].astype(complex),refs[:1].real,[0,1])
        report['estimated_differential_DC_resistance_ohm']=float(impedance[0].real) if valid[0] else None
    result.comments=(network.comments or '')+'\nsetupEM: EXTRAPOLATED DC, not solved. Method: '+method+f'; {used} lowest AC samples. Native AC samples retained.\nSource SHA256: '+str(source.get('sha256',''))+'\nSee companion JSON for assumptions and diagnostics.\n'
    return result,report


def export_dc(network, report, filename):
    """Exclusive derivative + provenance; preserve all port references in comments."""
    path=Path(filename).expanduser().resolve()
    if path.suffix.lower()!=f'.s{network.nports}p':raise ValueError(f'Use a .s{network.nports}p filename.')
    sidecar=path.with_suffix('.dc.json');created=[]
    try:
        for item in (path,sidecar):
            with item.open('x'):pass
            created.append(item)
        equal=np.all(network.z0==network.z0[0,0])
        text=network.write_touchstone(filename=path.name,return_string=True,form='ri',write_z0=not equal,format_spec_A='{:.17g}',format_spec_B='{:.17g}',format_spec_freq='{:.17g}')
        if not equal:
            # Use standard Touchstone 2 references, rather than relying on
            # HFSS impedance comments that circuit simulators may ignore.
            header=(f'# {network.frequency.unit} S RI R 50\n[Number of Ports] {network.nports}\n'
                    f'[Number of Frequencies] {len(network)}\n[Reference] '+
                    ' '.join(f'{z.real:.17g}' for z in network.z0[0])+'\n')
            if network.nports==2:header+='[Two-Port Data Order] 21_12\n'
            header+='[Network Data]'
            text='[Version] 2.0\n'+'\n'.join(header if line.startswith('#') else line
                for line in text.splitlines() if not line.startswith('! Port Impedance '))+'\n[End]\n'
        path.write_text(text,encoding='utf-8')
        output=dict(report,output=dict(path=str(path),sha256=hashlib.sha256(path.read_bytes()).hexdigest()))
        sidecar.write_text(json.dumps(output,indent=2,allow_nan=False)+'\n',encoding='utf-8')
    except Exception:
        for item in created:item.unlink(missing_ok=True)
        raise
    return path,sidecar
