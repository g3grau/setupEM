"""Explain calibrated openEMS launch limits before meshing or solving."""
import math
import re

C0 = 299792458.0


def describe_plan(plan):
    """Use the backend's actual planned geometry, not a separate launch model."""
    unit = plan['device']['unit']
    fstop = plan['device']['fstop']
    to_um = unit * 1e6
    warnings = list(plan['analysis']['warnings'])
    lines = [f'Requested stop frequency: {fstop / 1e9:g} GHz']
    guidance = []
    groups = []
    for g in plan['analysis']['groups']:
        D, length = g['D'], g['L']
        neff, nmax = g['n_eff_estimate'], math.sqrt(g['eps_max'])
        effective = C0 / (5 * length * unit * neff)
        phase = C0 / (4 * length * unit * nmax)
        small_port = C0 / (10 * D * unit * neff)
        feasible = min(small_port, C0 / (8 * D * unit * nmax))
        # n_eff in the serialized plan is rounded: allow its rounding error only.
        passed = lambda limit: fstop <= limit * (1 + 3e-5)
        row = dict(side=g['side'], D=D, L=length, effective_limit_GHz=effective / 1e9,
                   phase_limit_GHz=phase / 1e9, small_port_limit_GHz=small_port / 1e9,
                   geometry_band_limit_GHz=feasible / 1e9,
                   effective_ok=passed(effective), phase_ok=passed(phase), small_port_ok=passed(small_port))
        groups.append(row)
        status = lambda ok: 'PASS' if ok else 'FAIL'
        lines += [f"{g['side']}: cross-section D={D*to_um:g} um; standards L={length*to_um:g}, 2L={2*length*to_um:g} um",
                  f"  Effective-index wavelength check: {status(row['effective_ok'])} (limit {effective/1e9:.3f} GHz)",
                  f"  Maximum-permittivity half-wave check: {status(row['phase_ok'])} (limit {phase/1e9:.3f} GHz)",
                  f"  Small-port cross-section check: {status(row['small_port_ok'])} (limit {small_port/1e9:.3f} GHz)"]
        if g.get('uniform_from_wall') is not None:
            lines.append(f"  Uniform feed {g['uniform_from_wall']*to_um:g} um; minimum D/4={D*to_um/4:.3f} um; reference shift={g['shift']*to_um:g} um")
        if not all(row[k] for k in ('effective_ok', 'phase_ok', 'small_port_ok')):
            trial = math.floor(feasible / 1e9 * .96 * 10) / 10
            guidance.append(f"{g['side']}: reduce Stop frequency below {feasible/1e9:.3f} GHz "
                            f"(for example {trial:g} GHz), then check again. The standards will be replanned. "
                            'Alternatively use a closer return conductor or another validated calibration method. '
                            'Increasing dielectric oversize or feed length does not fix this bandwidth limit.')
        if g['shift'] and g.get('uniform_from_wall') is not None and g['shift'] > g['uniform_from_wall'] + 1e-6:
            guidance.append('Keep the reference plane within the uniform feed; retain any transition on the device side.')
    okay = not warnings and all(g[k] for g in groups for k in ('effective_ok', 'phase_ok', 'small_port_ok'))
    if warnings and not guidance:
        guidance.append('Review the backend warnings below. Do not start calibration until the geometry or settings are corrected.')
    notes = list(plan['analysis'].get('notes', []))
    return dict(ok=okay, geometry_ok=True, title='Calibration preflight passed' if okay else 'Calibration needs changes',
                lines=lines, guidance=guidance, warnings=warnings, notes=notes, groups=groups)


def geometry_failure(error):
    detail = str(error)
    guidance = []
    if 'cross-section' in detail and 'D/4' in detail:
        extra = re.search(r'outward by at least ([\d.eE+-]+)', detail)
        guidance.append('Increase Uniform feed length' +
                        (f' by at least {extra.group(1)} um, with some margin' if extra else '') +
                        '. This moves the PEC port wall; dielectric oversize does not. Then check again.')
    elif 'reference_plane_shift' in detail and 'uniform feed' in detail:
        amounts = re.search(r'= ([\d.eE+-]+).*ends ([\d.eE+-]+)', detail)
        needed = max(0, float(amounts[1]) - float(amounts[2])) if amounts else None
        guidance.append('A transition lies between the terminal and the uniform feed. '
                        'Remove an artificial patch in a separate GDS variant if it is not part of the device, '
                        'or explicitly retain the transition using Reference plane setback toward wall' +
                        (f' of more than {needed:.3f} um' if needed is not None else '') + '. '
                        'A setback changes the measurement reference plane; it does not correct the geometry.')
    else:
        guidance.append('Check the selected GDS, stackup, signal/return layers and rectangular terminal markers. '
                        'Resolve the geometry detail below, then check again.')
    return dict(ok=False, geometry_ok=False, title='Calibration geometry could not be checked',
                lines=[], guidance=guidance, warnings=[detail], notes=[], groups=[])


def check_configuration(values, port_rows):
    """Read inputs and build the calibration plan only. No mesh, output files or solver."""
    from gds2openEMS import stackup_reader, gds_reader, simulation_setup
    from gds2openEMS import util_model_geometry, util_boxwall
    try:
        v = values
        cfg = v['openems_boxwall']
        if v.get('openems_aircut'):
            raise ValueError('Use box-wall calibration and RDL air cuts as separate experiments.')
        pp = simulation_setup.all_simulation_ports()
        for row in sorted(port_rows, key=lambda p: p['portnumber']):
            direction = row['direction'].lower()
            layers = ({'from_layername': row['from_layername'], 'to_layername': row['to_layername']}
                      if direction.endswith('z') else {'target_layername': row['target_layername']})
            pp.add_port(simulation_setup.simulation_port(portnumber=row['portnumber'],
                        voltage=row.get('voltage', 1), port_Z0=row.get('port_Z0', 50),
                        source_layernum=row['source_layernum'], direction=direction, **layers))
        ma, di, me = stackup_reader.read_substrate(v['SubstrateFile'], variable_overrides=v.get('variable_overrides', {}))
        numbers = me.getlayernumbers() + pp.portlayers
        polys = gds_reader.read_gds(v['GdsFile'], numbers, purposelist=v.get('purpose', range(65536)),
                    cellname=v.get('cellname', ''), metals_list=me, gds_boundary_layers=di.get_boundary_layers(),
                    merge_polygon_size=v.get('merge_polygon_size', 0))
        s = dict(unit=v.get('unit', 1e-6), margin=v.get('margin', 200), air_around=v.get('air_around', 0),
                 Boundaries=v.get('openems_boundaries', ['PEC'] * 6), fstart=v.get('fstart', 0) * 1e9,
                 fstop=v.get('fstop', 50) * 1e9, numfreq=v.get('numfreq', 401),
                 refined_cellsize=v.get('refined_cellsize', 1), cells_per_wavelength=v.get('cells_per_wavelength', 20),
                 energy_limit=v.get('energy_limit', -50), no_gui=True, simulation_ports=pp,
                 allpolygons=polys, materials_list=ma, dielectrics_list=di, metals_list=me,
                 sim_path=v.get('sim_path', '.'), model_basename=v.get('model_basename', 'preflight'))
        s = util_model_geometry.add_boxwall_feeds(s, cfg, source_gds=v['GdsFile'])
        setback = float(cfg.get('reference_plane_setback', 0))
        length = float(cfg['feed_length'])
        if not math.isfinite(setback) or not 0 <= setback < length:
            raise ValueError('Reference plane setback must be finite, nonnegative and shorter than the feed.')
        s['reference_plane_shift'] = {cfg['side']: length - setback}
        if 'deembedding_length' in v:
            s['deembedding_length'] = v['deembedding_length']
        return describe_plan(util_boxwall.prepare(s))
    except (ValueError, KeyError, OSError, RuntimeError) as error:
        return geometry_failure(error)
    except SystemExit as error:
        # Some upstream input readers exit on invalid input. A check must never
        # close the GUI together with that reader.
        return geometry_failure(ValueError(f'Input reader stopped ({error.code}). Check the GDS and stackup files.'))


def report_text(report):
    sections = [report['title']] + report['lines']
    if report['guidance']:
        sections += ['', 'How to fix:'] + report['guidance']
    if report['warnings']:
        sections += ['', 'Backend details:'] + report['warnings']
    if report['notes']:
        sections += ['', 'Geometry notes:'] + report['notes']
    sections += ['', 'These are calibration applicability checks, not a convergence or accuracy guarantee.']
    return '\n'.join(sections)
