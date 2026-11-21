"""Solver-independent, native-sample parameter extraction for analysis and fitting.

Port numbers in ExtractionSpec are one-based. All returned numeric columns use
SI units; presentation and plotting belong to the UI. No input files are changed.
"""
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import csv
import hashlib
import json
from pathlib import Path

import numpy as np

C0 = 299792458.0


@dataclass(frozen=True)
class ExtractionSpec:
    mode: str = 'inductor'
    port_a: int = 1
    port_b: int = 2
    unused_ports: str = 'matched'
    line_length_m: float = 0.0
    phase_branch: int = 0
    minimum_hz: float = 1e8
    maximum_hz: float = 0.0   # zero = end of source band


@dataclass
class ParameterResult:
    frequency_hz: np.ndarray
    columns: dict
    summary: dict
    warnings: list
    provenance: dict


def load_touchstone(filename):
    import skrf as rf
    path = Path(filename).expanduser().resolve()
    before = hashlib.sha256(path.read_bytes()).hexdigest()
    network = rf.Network(str(path))
    after = hashlib.sha256(path.read_bytes()).hexdigest()
    if before != after:
        raise ValueError('The Touchstone file changed while loading; load it again.')
    return network, dict(path=str(path), sha256=before, loaded_utc=datetime.now(timezone.utc).isoformat(),
                         comments=str(network.comments or ''))


def _differential_impedance(s, refs, pair):
    """Drive +1/-1 A, allowing an arbitrary common-mode voltage only when
    the differential voltage remains unique. No artificial shunt or damping.
    """
    out=np.full(len(s),np.nan+1j*np.nan);valid=np.zeros(len(s),bool)
    for i,matrix in enumerate(s):
        if not np.isfinite(matrix).all():continue
        roots=np.sqrt(refs[i]);drive=np.zeros(len(roots));drive[pair[0]]=1;drive[pair[1]]=-1
        eye=np.eye(len(roots));left=eye-matrix;rhs=roots*drive
        try:
            _,sing,vh=np.linalg.svd(left)
            rank=int((sing>max(sing[0]*1e-12,1e-15)).sum())
            waves=np.linalg.lstsq(left,rhs,rcond=1e-12)[0]
            functional=(roots*drive)@(eye+matrix)
            if np.linalg.norm(left@waves-rhs)>1e-9*np.linalg.norm(rhs):continue
            null=vh[rank:].conj().T
            if null.size and np.linalg.norm(functional@null)>1e-9*max(np.linalg.norm(functional),1):continue
            out[i]=functional@waves;valid[i]=np.isfinite(out[i])
        except np.linalg.LinAlgError:pass
    return out,valid


def _open_pair(s, pair):
    """Terminate unselected real-reference ports in opens, including harmless
    disconnected modes. Require a unique selected-port response.
    """
    other=[i for i in range(s.shape[1]) if i not in pair]
    aa=s[:,pair][:,:,pair];ab=s[:,pair][:,:,other]
    ba=s[:,other][:,:,pair];bb=s[:,other][:,:,other]
    out=np.full(aa.shape,np.nan+1j*np.nan);valid=np.zeros(len(s),bool)
    for i in range(len(s)):
        left=np.eye(len(other))-bb[i];rhs=ba[i]
        if not np.isfinite(left).all() or not np.isfinite(rhs).all():continue
        try:
            _,sing,vh=np.linalg.svd(left)
            rank=int((sing>max(sing[0]*1e-12,1e-15)).sum())
            waves=np.linalg.lstsq(left,rhs,rcond=1e-12)[0]
            if np.linalg.norm(left@waves-rhs)>1e-9*max(np.linalg.norm(rhs),1):continue
            null=vh[rank:].conj().T
            if null.size and np.linalg.norm(ab[i]@null)>1e-9*max(np.linalg.norm(ab[i]),1):continue
            out[i]=aa[i]+ab[i]@waves;valid[i]=np.isfinite(out[i]).all()
        except np.linalg.LinAlgError:pass
    return out,valid


def _pair(network, spec):
    f = np.asarray(network.f, float)
    if len(f) < 2 or not np.isfinite(f).all() or np.any(np.diff(f) <= 0):
        raise ValueError('Need at least two strictly increasing, finite source frequencies.')
    if network.nports < 2:
        raise ValueError('Load a network with at least two ports.')
    if int(spec.port_a)!=spec.port_a or int(spec.port_b)!=spec.port_b:
        raise ValueError('Port numbers must be integers.')
    pair = [int(spec.port_a)-1, int(spec.port_b)-1]
    if len(set(pair)) != 2 or any(p < 0 or p >= network.nports for p in pair):
        raise ValueError('Choose two different ports present in the source file.')
    positive = f > 0
    s = np.asarray(network.s[positive], complex)
    refs = np.asarray(network.z0[positive], complex)
    if not np.isfinite(refs).all() or np.any(refs.real <= 0) or np.any(abs(refs.imag) > 1e-10):
        raise ValueError('Extraction currently requires finite, real, positive port reference impedances.')
    refs = refs.real
    selected_refs = refs[:,pair]
    valid = np.ones(len(s),bool)
    if spec.unused_ports == 'matched' or network.nports == 2:
        selected = s[:,pair][:,:,pair]
    elif spec.unused_ports == 'open' and spec.mode == 'inductor':
        selected, selected_refs = s, refs
    elif spec.unused_ports == 'open':
        selected, valid = _open_pair(s, pair)
    else:
        raise ValueError('Unused-port termination must be matched or open.')
    if spec.unused_ports not in ('matched','open'):
        raise ValueError('Unused-port termination must be matched or open.')
    return f[positive], selected, selected_refs, valid, int((~positive).sum())


def _finite_max(array):
    values = np.asarray(array)[np.isfinite(array)]
    return float(values.max()) if len(values) else None


def _continuous_phase(values, valid):
    # Do not unwrap across missing/singular samples and pretend the branch is known.
    phase = np.full(len(values), np.nan)
    for indices in np.split(np.flatnonzero(valid), np.flatnonzero(np.diff(np.flatnonzero(valid)) > 1)+1):
        if len(indices):
            phase[indices] = np.unwrap(np.angle(values[indices]))
    return phase


def extract_parameters(network, spec=ExtractionSpec(), source=None):
    if spec.mode not in ('inductor','line'):
        raise ValueError('Choose inductor or transmission line extraction.')
    if (not np.isfinite([spec.minimum_hz,spec.maximum_hz]).all() or spec.minimum_hz < 0 or
            spec.maximum_hz < 0 or (spec.maximum_hz and spec.maximum_hz <= spec.minimum_hz)):
        raise ValueError('Frequency range must be finite, nonnegative, with maximum greater than minimum (or zero for file end).')
    f, s, refs, valid, dc_count = _pair(network, spec)
    if len(f) < 2:
        raise ValueError('Need at least two positive-frequency samples; DC is excluded.')
    w = 2*np.pi*f
    warnings = []
    mask=(f>=spec.minimum_hz)&((f<=spec.maximum_hz) if spec.maximum_hz else True)
    if mask.sum()<2:
        raise ValueError('The selected band contains fewer than two positive native samples.')
    summary = dict(mode=spec.mode, source_port_count=network.nports, selected_ports=[spec.port_a,spec.port_b],
                   unused_ports=spec.unused_ports, dc_or_nonpositive_samples_excluded=dc_count)
    if network.nports > 2:
        warnings.append('Unused ports are '+('matched to their own Touchstone reference impedances.'
                         if spec.unused_ports=='matched' else 'open-circuited (zero terminal current).'))
    if spec.mode == 'inductor':
        drive_pair = [spec.port_a-1,spec.port_b-1] if spec.unused_ports=='open' and network.nports>2 else [0,1]
        zd, invertible = _differential_impedance(s, refs, drive_pair)
        valid &= invertible
        with np.errstate(divide='ignore',invalid='ignore'):
            columns = dict(L_H=zd.imag/w, R_ohm=zd.real, X_ohm=zd.imag, Q=zd.imag/zd.real)
        valid &= np.isfinite(zd)
        definition = 'I_a=+I, I_b=-I; Zdiff=Zaa-Zab-Zba+Zbb; L=Im(Zdiff)/(2*pi*f); R=Re(Zdiff); Q=Im(Zdiff)/Re(Zdiff).'
    else:
        if not np.isfinite(spec.line_length_m) or spec.line_length_m <= 0:
            raise ValueError('Enter the physical uniform-line length; it must be positive.')
        if int(spec.phase_branch) != spec.phase_branch:
            raise ValueError('Phase branch offset must be an integer.')
        a,b,c,d = s[:,0,0],s[:,0,1],s[:,1,0],s[:,1,1]
        valid &= np.isfinite(s).all(axis=(1,2)) & (abs(c)>1e-14)
        r1,r2 = refs[:,0],refs[:,1]
        with np.errstate(divide='ignore',invalid='ignore',over='ignore'):
            A=((1+a)*(1-d)+b*c)/(2*c)*np.sqrt(r1/r2)
            B=((1+a)*(1+d)-b*c)/(2*c)*np.sqrt(r1*r2)
            C=((1-a)*(1-d)-b*c)/(2*c)/np.sqrt(r1*r2)
            D=((1-a)*(1+d)+b*c)/(2*c)*np.sqrt(r2/r1)
            zc=np.sqrt(B/C)
            zc=np.where(zc.real<0,-zc,zc)
            propagation=.5*(A+D)+.5*(B/zc+C*zc)
            valid &= np.isfinite(zc) & np.isfinite(propagation) & (abs(propagation)>1e-30) & (abs(C)>1e-20)
            phase=_continuous_phase(propagation,valid)+2*np.pi*spec.phase_branch
            gamma=(np.log(abs(propagation))+1j*phase)/spec.line_length_m
            series=gamma*zc;shunt=gamma/zc
            fitA=.5*(np.exp(gamma*spec.line_length_m)+np.exp(-gamma*spec.line_length_m))
            fitS=.5*(np.exp(gamma*spec.line_length_m)-np.exp(-gamma*spec.line_length_m))
            reference=np.sqrt(r1*r2)
            error=np.sqrt(abs(A-fitA)**2+abs(D-fitA)**2+abs((B-zc*fitS)/reference)**2+abs((C-fitS/zc)*reference)**2)
            norm=np.sqrt(abs(A)**2+abs(D)**2+abs(B/reference)**2+abs(C*reference)**2)
            residual=error/np.maximum(norm,1e-30)
            columns=dict(Zc_real_ohm=zc.real,Zc_imag_ohm=zc.imag,alpha_Np_per_m=gamma.real,
                         alpha_dB_per_mm=20/np.log(10)*gamma.real/1000,beta_rad_per_m=gamma.imag,
                         R_ohm_per_m=series.real,L_H_per_m=series.imag/w,
                         G_S_per_m=shunt.real,C_F_per_m=shunt.imag/w,
                         effective_permittivity=(C0*gamma.imag/w)**2,uniform_line_residual=residual)
        reciprocity=abs(A*D-B*C-1)
        symmetry=abs(A-D)/np.maximum(abs(A)+abs(D),1e-30)
        summary.update(line_length_m=spec.line_length_m,phase_branch_offset=spec.phase_branch,
                       phase_anchor_frequency_Hz=float(f[0]),
                       phase_anchor='Unwrapped from first positive source sample, assuming its principal phase plus branch offset.',
                       max_reciprocity_residual=_finite_max(reciprocity[mask]),max_symmetry_residual=_finite_max(symmetry[mask]),
                       max_uniform_line_residual=_finite_max(residual[mask]))
        warnings.append('Uniform reciprocal transmission line assumed. Launches/transitions must already be de-embedded; this extraction does not remove fixtures.')
        warnings.append('Phase unwrapping assumes a known low-frequency branch and sufficiently fine frequency spacing. Branch offset is in full 2*pi turns at the first source sample.')
        if (_finite_max(residual[mask]) or 0)>.02:
            warnings.append('Uniform-line reconstruction error exceeds 2%; RLGC values are an effective approximation, not a validated uniform-line model.')
        if np.any(np.diff(np.flatnonzero(valid))>1):
            warnings.append('Singular samples break phase continuity; each valid segment needs its own phase-branch review.')
        definition='ABCD uniform-line extraction; Zc=sqrt(B/C); exp(gamma*l)=(A+D)/2+(B/Zc+C*Zc)/2; R+jwL=gamma*Zc; G+jwC=gamma/Zc.'
    if not (valid&mask).any():
        raise ValueError('No usable samples: the selected network conversion is singular or nonfinite. Check unused-port termination and frequency range.')
    invalid=int((mask&~valid).sum())
    if invalid:
        warnings.append(f'{invalid} singular/nonfinite sample(s) retained as NaN; no regularization or interpolation was applied.')
    for key, value in columns.items():
        value=np.array(value,float,copy=True);value[~valid]=np.nan
        columns[key]=value[mask]
    f=f[mask]
    summary.update(samples=len(f),first_frequency_Hz=float(f[0]),last_frequency_Hz=float(f[-1]),invalid_samples=invalid)
    if spec.mode=='inductor':
        x,r,q=columns['X_ohm'],columns['R_ohm'],columns['Q']
        crossings=np.flatnonzero(np.isfinite(x[:-1])&np.isfinite(x[1:])&(x[:-1]>0)&(x[1:]<=0))
        resonance=None
        if len(crossings):
            i=int(crossings[0]);resonance=float(f[i]-x[i]*(f[i+1]-f[i])/(x[i+1]-x[i]))
        allowed=np.isfinite(q)&(r>0)&(x>0)
        noninductive=np.flatnonzero(np.isfinite(x)&(x<=0))
        if len(noninductive):allowed[np.arange(len(f))>=noninductive[0]]=False
        candidates=np.flatnonzero(allowed)
        peak=int(candidates[np.argmax(q[candidates])]) if len(candidates) else None
        summary.update(peak_Q=float(q[peak]) if peak is not None else None,
                       peak_Q_frequency_Hz=float(f[peak]) if peak is not None else None,
                       reactance_zero_Hz=resonance)
        if np.any(r[np.isfinite(r)]<0):warnings.append('Negative differential resistance is present; review calibration, passivity and convergence.')
        if np.any(x[np.isfinite(x)]<=0):warnings.append('The selected band includes capacitive response; negative L/Q is retained rather than presented as inductive operation.')
    else:
        if np.any(columns['beta_rad_per_m'] < 0):warnings.append('Negative phase constant: review the initial phase-branch offset and line-end selection.')
        adjacent=valid[1:]&valid[:-1]
        steps=np.angle(propagation[1:][adjacent]/propagation[:-1][adjacent])
        if np.any(abs(steps)>.8*np.pi):warnings.append('Large inter-sample phase steps: a finer frequency grid may be needed for unambiguous phase unwrapping.')
        if np.any(columns['alpha_Np_per_m'] < -1e-6):warnings.append('Negative attenuation is present; check the model, calibration and propagation direction.')
        if any(np.any(columns[key] < -tolerance) for key,tolerance in
               [('R_ohm_per_m',1e-6),('L_H_per_m',1e-15),('G_S_per_m',1e-10),('C_F_per_m',1e-18)]):
            warnings.append('Negative RLGC parameter(s) are present; review the phase branch, calibration and uniform-line assumption.')
    try:
        from .cli_common import package_version
    except ImportError:
        from cli_common import package_version
    provenance=dict(schema='setupEM.network-parameters.v1',specification=asdict(spec),
                    analysis_tool={'name':'setupEM','version':package_version(),
                                   'module_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest()},
                    source=dict(source or {}),definition=definition,
                    sampling='Native positive-frequency samples. No smoothing. Band selection does not extrapolate.',
                    summary_estimates='Q peak uses native samples in selected inductive band; reactance zero linearly interpolates adjacent samples.',
                    other_port_boundary='Matched to source reference impedances' if spec.unused_ports=='matched' else 'Open-circuit terminals',
                    summary=summary,warnings=warnings)
    return ParameterResult(f,columns,summary,warnings,provenance)


def export_parameters(result, filename):
    """Exclusive CSV+JSON export; preserve the source network and existing exports."""
    path=Path(filename).expanduser()
    if path.suffix.lower()!='.csv':path=path.with_suffix('.csv')
    metadata=path.with_suffix('.json')
    if path.exists() or metadata.exists():
        raise ValueError('An export with this name already exists; choose a new filename.')
    source=result.provenance.get('source',{}).get('path')
    if source and path.resolve()==Path(source).resolve():
        raise ValueError('Refusing to overwrite the input network.')
    info=dict(result.provenance,exported_utc=datetime.now(timezone.utc).isoformat())
    text=json.dumps(info,indent=2,allow_nan=False)+'\n'
    # Claim both names before writing any content. Clean up only files created here.
    csv_stream=path.open('x',newline='',encoding='utf-8')
    try:
        json_stream=metadata.open('x',encoding='utf-8')
    except Exception:
        csv_stream.close();path.unlink();raise
    try:
        with csv_stream,json_stream:
            writer=csv.writer(csv_stream);writer.writerow(['frequency_Hz']+list(result.columns))
            writer.writerows(zip(result.frequency_hz,*result.columns.values()))
            json_stream.write(text)
    except Exception:
        path.unlink(missing_ok=True);metadata.unlink(missing_ok=True);raise
    return path,metadata
