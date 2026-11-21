"""Multi-file comparisons on native frequency grids; no smoothing or alignment."""
from dataclasses import dataclass, asdict
from pathlib import Path
from datetime import datetime, timezone
import csv
import hashlib
import json
import numpy as np
try:
    from .network_parameters import ExtractionSpec,load_touchstone,extract_parameters,_open_pair,_continuous_phase
except ImportError:
    from network_parameters import ExtractionSpec,load_touchstone,extract_parameters,_open_pair,_continuous_phase


@dataclass(frozen=True)
class ComparisonEntry:
    path: str
    label: str = ''
    port_a: int = 1
    port_b: int = 2
    unused_ports: str = 'matched'
    style: str = 'markers'


def compare_networks(entries, mode='inductor', minimum_hz=1e8, maximum_hz=0., reference_ohm=None):
    if mode not in ('inductor','raw'):raise ValueError('Choose inductor or raw S-parameter comparison.')
    if (not np.isfinite([minimum_hz,maximum_hz]).all() or minimum_hz<0 or maximum_hz<0 or
            (maximum_hz and maximum_hz<=minimum_hz)):
        raise ValueError('Maximum frequency must exceed minimum, or be zero for file end.')
    if reference_ohm is not None and (not np.isfinite(reference_ohm) or reference_ohm<=0):
        raise ValueError('Common reference impedance must be positive and finite.')
    if not entries:raise ValueError('Add and enable at least one Touchstone file.')
    curves=[];labels=set();reference_signatures=[]
    for number,entry in enumerate(entries,1):
        try:
            network,source=load_touchstone(entry.path)
            requested=entry.label.strip() or Path(source['path']).name
            label=requested;index=2
            while label in labels:label=f'{requested} ({index})';index+=1
            labels.add(label)
            if entry.style not in ('line','markers','points'):raise ValueError('Unknown curve style.')
            if not np.isfinite(network.f).all() or np.any(np.diff(network.f)<=0) or np.any(network.f<0):
                raise ValueError('Source frequencies must be finite, nonnegative and strictly increasing.')
            pair=[entry.port_a-1,entry.port_b-1]
            if any(int(p)!=p or p<0 or p>=network.nports for p in pair):raise ValueError('Selected port is not present in this file.')
            if entry.unused_ports not in ('matched','open'):raise ValueError('Choose matched or open unused ports.')
            original_refs=dict(real_min_ohm=float(network.z0.real.min()),real_max_ohm=float(network.z0.real.max()),
                               max_abs_imag_ohm=float(abs(network.z0.imag).max()))
            if reference_ohm is not None:
                # Change selected wave references without changing physical
                # matched loads at any unselected terminal.
                network=network.copy();new_refs=network.z0.copy();new_refs[:,pair]=reference_ohm
                network.renormalize(new_refs)
            refs=network.z0[:,pair]
            signature=refs[0] if np.allclose(refs,refs[0],rtol=1e-12,atol=1e-12) else None
            reference_signatures.append(signature)
            if mode=='inductor':
                spec=ExtractionSpec(port_a=entry.port_a,port_b=entry.port_b,unused_ports=entry.unused_ports,
                                    minimum_hz=minimum_hz,maximum_hz=maximum_hz)
                result=extract_parameters(network,spec,source)
                f,columns,summary,warnings=result.frequency_hz,result.columns,result.summary,list(result.warnings)
                if entry.style=='points':
                    summary=dict(summary,peak_Q=None,peak_Q_frequency_Hz=None,reactance_zero_Hz=None)
                    warnings.append('Points-only dataset: peak and reactance-zero estimates omitted; no connection between sparse samples is implied.')
            else:
                selected=network.s[:,pair][:,:,pair]
                if entry.unused_ports=='open' and network.nports>len(set(pair)):
                    if len(set(pair))!=2:raise ValueError('Choose two distinct ports for open-terminated multiport reduction.')
                    if not np.isfinite(network.z0).all() or np.any(network.z0.real<=0) or np.any(abs(network.z0.imag)>1e-10):
                        raise ValueError('Open-port reduction requires real, positive reference impedances.')
                    selected,_=_open_pair(network.s,pair)
                mask=(network.f>=minimum_hz)&((network.f<=maximum_hz) if maximum_hz else True)
                if not mask.any():raise ValueError('No native samples in the selected band.')
                f=network.f[mask];columns={};warnings=[]
                for key,i,j in [('aa',0,0),('ba',1,0),('ab',0,1),('bb',1,1)]:
                    s=selected[:,i,j];valid=np.isfinite(s)&(abs(s)>0)
                    with np.errstate(divide='ignore',invalid='ignore'):
                        magnitude=20*np.log10(abs(s))
                    phase=np.rad2deg(_continuous_phase(s,valid))
                    columns.update({key+'_real':s.real[mask],key+'_imag':s.imag[mask],
                                    key+'_dB':magnitude[mask],key+'_phase_deg':phase[mask]})
                summary=dict(samples=len(f),first_frequency_Hz=float(f[0]),last_frequency_Hz=float(f[-1]))
                if not np.isfinite(selected[mask]).all():warnings.append('Undefined raw samples are retained as NaN.')
                warnings.append('Raw S uses each row’s selected terminal pair; phase is unwrapped across valid native samples before band selection. Zero-magnitude phase is undefined.')
            curves.append(dict(label=label,entry=asdict(entry),source=source,frequency_hz=f,columns=columns,
                               original_reference=original_refs,summary=summary,warnings=warnings))
        except (OSError,ValueError,ArithmeticError,IndexError) as error:
            raise ValueError(f'File row {number} ({entry.label or entry.path}): {error}') from error
    warnings=[]
    if mode=='raw' and reference_ohm is None and (any(r is None for r in reference_signatures) or
            any(not np.allclose(reference_signatures[0],r,rtol=1e-9,atol=1e-9) for r in reference_signatures if r is not None)):
        warnings.append('Reference impedances differ or vary with frequency. Raw S curves retain those references; enable a common impedance for a normalized comparison.')
    return dict(mode=mode,minimum_hz=minimum_hz,maximum_hz=maximum_hz,reference_ohm=reference_ohm,
                curves=curves,warnings=warnings)


def export_comparison(result,directory,plot_options=None):
    folder=Path(directory).expanduser().resolve();folder.mkdir(parents=True,exist_ok=False)
    manifest=dict(schema='setupEM.network-comparison.v1',created_utc=datetime.now(timezone.utc).isoformat(),
                  mode=result['mode'],minimum_hz=result['minimum_hz'],maximum_hz=result['maximum_hz'],
                  common_reference_ohm=result['reference_ohm'],plot_options=plot_options or {},
                  sampling='Each source uses its own native frequency samples; no alignment, interpolation or smoothing.',
                  implementation_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                  extraction_sha256=hashlib.sha256(Path(__file__).with_name('network_parameters.py').read_bytes()).hexdigest(),
                  warnings=result['warnings'],curves=[])
    for index,curve in enumerate(result['curves'],1):
        path=folder/f'curve_{index:02d}.csv';columns=curve['columns']
        with path.open('x',newline='',encoding='utf-8') as stream:
            writer=csv.writer(stream);writer.writerow(['frequency_Hz',*columns])
            writer.writerows(zip(curve['frequency_hz'],*columns.values()))
        manifest['curves'].append({key:value for key,value in curve.items() if key not in ('frequency_hz','columns')} |
            dict(csv=path.name,csv_sha256=hashlib.sha256(path.read_bytes()).hexdigest()))
    (folder/'comparison.json').write_text(json.dumps(manifest,indent=2,allow_nan=False)+'\n',encoding='utf-8')
    return folder
