"""Technology-independent openEMS model export; no solver bindings required to export."""
import math
import hashlib
from pathlib import Path

if __package__ in (None, ''):
    from cli_common import package_version
else:
    from .cli_common import package_version

BOUNDARIES = ('PEC', 'PMC', 'MUR', 'PML_8')


def openems_script_text(values, ports):
    """Write a full two-port/N-port FDTD workflow from setupEM's shared inputs.

    GUI frequency values are GHz. FEM boundary types are deliberately not mapped.
    """
    v = values
    fstart, fstop = float(v.get('fstart', 0)), float(v.get('fstop', 50))
    if not (math.isfinite(fstart) and math.isfinite(fstop) and 0 <= fstart < fstop):
        raise ValueError('openEMS requires 0 <= fstart < fstop.')
    boundaries = v.get('openems_boundaries', ['PEC'] * 6)
    if len(boundaries) != 6 or any(b not in BOUNDARIES for b in boundaries):
        raise ValueError('Choose six openEMS boundaries: PEC, PMC, MUR or PML_8.')
    margin = v.get('margin', 200)
    if isinstance(margin, (tuple, list)):
        if len(set(margin)) != 1:
            raise ValueError('openEMS currently requires the same dielectric margin on all four sides.')
        margin = margin[0]
    numeric = {'unit': float(v.get('unit', 1e-6)), 'margin': float(margin),
               'refined_cellsize': float(v.get('refined_cellsize', 1)),
               'cells_per_wavelength': float(v.get('cells_per_wavelength', 20))}
    if any(not math.isfinite(x) or x < 0 for x in numeric.values()) or any(
            numeric[k] <= 0 for k in ('unit', 'refined_cellsize', 'cells_per_wavelength')):
        raise ValueError('openEMS mesh sizes/unit must be positive and margin nonnegative.')
    numfreq = int(v.get('numfreq', 401))
    thread_value = v.get('numThreads')
    threads = None if thread_value is None else int(thread_value)
    energy = float(v.get('energy_limit', -50))
    if numfreq < 2 or (threads is not None and threads < 0) or not math.isfinite(energy) or energy >= 0:
        raise ValueError('openEMS needs at least two frequency points, nonnegative threads and a negative energy limit.')
    if sorted(p.portnumber for p in ports.ports) != list(range(1, len(ports.ports) + 1)):
        raise ValueError('openEMS full-S-matrix ports must be numbered consecutively from 1.')
    air = v.get('air_around', 0)
    air_values = air if isinstance(air, (list, tuple)) else [air]
    if len(air_values) not in (1, 6) or any(not math.isfinite(float(x)) or float(x) < 0 for x in air_values):
        raise ValueError('Air padding must be nonnegative, either one value or six values.')
    merging = float(v.get('merge_polygon_size', 0))
    if not math.isfinite(merging) or merging < 0:
        raise ValueError('Via merging distance must be finite and nonnegative.')
    boxwall = v.get('openems_boxwall') or None
    execution = v.get('openems_execution') if boxwall else None
    if execution:
        for key in ('total_threads','device_threads','calibration_threads','max_jobs'):
            value=execution.get(key)
            if isinstance(value,bool) or not isinstance(value,int) or value<1:
                raise ValueError('Box-wall execution '+key+' must be a positive integer.')
        if max(execution['device_threads'],execution['calibration_threads'])>execution['total_threads']:
            raise ValueError('Each job thread count must fit within the total concurrent thread budget.')
        if v.get('openems_engine')=='gpu' and execution['max_jobs']>1:
            raise ValueError('Concurrent box-wall jobs require the CPU engine; set maximum concurrent jobs to 1 for GPU.')
    aircut = v.get('openems_aircut') or None
    if boxwall and aircut:
        raise ValueError('Use box-wall calibration and RDL air cuts as separate experiments for now.')
    if boxwall:
        if 'ports' in boxwall:
            entries=boxwall['ports']
            if not isinstance(entries,dict) or not entries:raise ValueError('Select at least one boxwall port.')
            numbers={p.portnumber for p in ports.ports}
            for key in entries:
                if str(key) not in {str(n) for n in numbers}:raise ValueError('Unknown boxwall port: '+str(key))
            feeds=list(entries.values())
        else:feeds=[boxwall]
        for feed in feeds:
            if feed.get('side') not in ('xmin','xmax','ymin','ymax'):
                raise ValueError('Choose a lateral box-wall side.')
            for key in ('signal_layer','return_layer'):
                if not feed.get(key):raise ValueError('Choose signal and return layers for box-wall feeds.')
            if feed.get('return_kind') not in ('metal','background'):
                raise ValueError('Choose a metal patch or conductive background return.')
            length=float(feed.get('feed_length',0));gap=float(feed.get('gap',0));width=float(feed.get('width',0))
            if not all(math.isfinite(x) for x in (length,gap,width)) or not 0<gap<length or width<0:
                raise ValueError('Box-wall feeds require length > gap > 0 and width >= 0 (0 = pin width).')
            setback=float(feed.get('reference_plane_setback',0))
            if not math.isfinite(setback) or not 0 <= setback < length:
                raise ValueError('Reference plane setback must be finite, nonnegative and shorter than the feed.')
        if any(p.port_Z0!=50 or not p.voltage for p in ports.ports):
            raise ValueError('Box-wall calibration requires excited 50-ohm ports.')
    if aircut:
        if not aircut.get('metal'):raise ValueError('Choose the RDL source metal.')
        for key in ('valley_height','coating_width'):
            value=float(aircut.get(key,-1))
            if not math.isfinite(value) or value<0:raise ValueError('Air-cut dimensions must be finite and nonnegative.')
    port_lines = []
    for port in ports.ports:
        direction = port.direction.lower()
        if direction not in ('x', '-x', 'y', '-y', 'z', '-z'):
            raise ValueError(f'Unsupported openEMS direction for port {port.portnumber}: {port.direction}')
        layers = (dict(from_layername=port.from_layername, to_layername=port.to_layername)
                  if direction.endswith('z') else dict(target_layername=port.target_layername))
        kwargs = dict(portnumber=port.portnumber, voltage=port.voltage, port_Z0=port.port_Z0,
                      source_layernum=port.source_layernum, **layers, direction=direction)
        port_lines.append('simulation_ports.add_port(simulation_setup.simulation_port(' +
                          ', '.join(f'{k}={x!r}' for k, x in kwargs.items()) + '))')
    settings = dict(numeric, fstart=fstart * 1e9, fstop=fstop * 1e9, numfreq=numfreq,
                    energy_limit=energy, Boundaries=list(boundaries),
                    air_around=v.get('air_around', 0),
                    merge_polygon_size=float(v.get('merge_polygon_size', 0)),
                    fill_factor_correction=bool(v.get('fill_factor_correction', False)),
                    preview_only=False, no_gui=True)
    if boxwall:settings['openems_boxwall']=boxwall
    if execution:settings['openems_execution']=execution
    if aircut:settings['openems_aircut']=aircut
    if threads:
        settings['numThreads'] = threads
    if v.get('openems_engine') == 'gpu':
        settings['engine'] = 'gpu'
    text = '''# Generated by setupEM: openEMS FDTD model (user-supplied GDS and stackup).
import argparse
import os
import numpy as np
from openEMS import openEMS
from gds2openEMS import stackup_reader, gds_reader, simulation_setup, utilities

parser = argparse.ArgumentParser(description=__doc__)
actions = parser.add_mutually_exclusive_group()
actions.add_argument('--preview-only', action='store_true', help='Preview geometry/mesh without solving')
actions.add_argument('--prepare-only', action='store_true', help='Write geometry/mesh XML without solving or opening a viewer')
args = parser.parse_args()
script_path = os.path.dirname(os.path.abspath(__file__))
model_basename = utilities.get_basename(__file__)
sim_path = utilities.create_sim_path(script_path, model_basename)
os.chdir(script_path)
'''
    text += f'\ngds_filename = {v.get("GdsFile", "")!r}\nXML_filename = {v.get("SubstrateFile", "")!r}\n'
    text += 'settings = {}\n'
    text += ''.join(f'settings[{key!r}] = {value!r}\n' for key, value in settings.items())
    text += '''settings['preview_only'] = args.preview_only
settings['no_gui'] = not args.preview_only
simulation_ports = simulation_setup.all_simulation_ports()
'''
    text += '\n'.join(port_lines) + '\n'
    generator = dict(name='setupEM', version=package_version(),
                     exporter_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest())
    input_selection = dict(variable_overrides=v.get('variable_overrides', {}), cellname=v.get('cellname', ''),
                           purpose='all' if v.get('purpose', list(range(65536))) == list(range(65536)) else v['purpose'])
    text += f'''\nsettings['simulation_ports'] = simulation_ports
settings['_touchstone_provenance'] = utilities.touchstone_provenance(
    dict(settings, **{input_selection!r}), sources={{'gds': gds_filename, 'stackup': XML_filename,
                       'model_script': os.path.abspath(__file__),
                       'configuration': os.path.splitext(os.path.abspath(__file__))[0] + '.simcfg'}},
    generator={generator!r})
'''
    text += f'''
materials_list, dielectrics_list, metals_list = stackup_reader.read_substrate(
    XML_filename, variable_overrides={v.get('variable_overrides', {})!r})
layernumbers = metals_list.getlayernumbers()
layernumbers.extend(simulation_ports.portlayers)
allpolygons = gds_reader.read_gds(
    gds_filename, layernumbers, purposelist={"range(65536)" if v.get('purpose', list(range(65536))) == list(range(65536)) else repr(v['purpose'])},
    cellname={v.get('cellname', '')!r}, metals_list=metals_list,
    gds_boundary_layers=dielectrics_list.get_boundary_layers(),
    merge_polygon_size=settings['merge_polygon_size'])
settings.update(simulation_ports=simulation_ports, materials_list=materials_list,
                dielectrics_list=dielectrics_list, metals_list=metals_list,
                layernumbers=layernumbers, allpolygons=allpolygons,
                sim_path=sim_path, model_basename=model_basename)
'''
    if boxwall or aircut:
        text += "\nfrom gds2openEMS import util_model_geometry as generated_geometry\n"
    if boxwall:
        text += """
from gds2openEMS import util_boxwall as boxwall
settings = generated_geometry.add_boxwall_feeds(settings, settings['openems_boxwall'], source_gds=gds_filename)
feed_config = settings['openems_boxwall']
if 'ports' not in feed_config:
    setback = float(feed_config.get('reference_plane_setback', 0))
    if not np.isfinite(setback) or not 0 <= setback < float(feed_config['feed_length']):
        raise ValueError('Reference plane setback must be finite, nonnegative and shorter than the feed.')
    settings['reference_plane_shift'] = {feed_config['side']: float(feed_config['feed_length']) - setback}
    if setback:
        print(f'Reference plane moved {setback:g} drawing units toward the wall from the terminal; '
              'the intervening transition remains part of the device.', flush=True)
plan = boxwall.prepare(settings)
if args.preview_only:
    boxwall.preview(plan)
else:
    print(boxwall.run(plan, prepare_only=args.prepare_only))
raise SystemExit(0)
"""
    if aircut:
        text += """
settings = generated_geometry.add_rdl_aircut(settings, settings['openems_aircut'])
print('RDL air-cut geometry:', settings['rdl_aircut_status'], flush=True)
"""
    text += '''
# A full S matrix requires all ports to be excited, once per column.
if not simulation_ports.portcount:
    raise ValueError('Define at least one simulation port.')
if any(port.voltage == 0 for port in simulation_ports.ports):
    raise ValueError('This full-S-matrix model requires nonzero excitation voltage on every port.')
for excitation in simulation_ports.all_active_excitations():
    FDTD = openEMS(EndCriteria=10 ** (settings['energy_limit'] / 10))
    FDTD.SetGaussExcite((settings['fstart'] + settings['fstop']) / 2,
                       (settings['fstop'] - settings['fstart']) / 2)
    FDTD.SetBoundaryCond(settings['Boundaries'])
    settings['excite_portnumbers'] = excitation
    simulation_setup.setupSimulation(FDTD=FDTD, settings=settings)
    if args.prepare_only:
        excitation_path = utilities.get_excitation_path(sim_path, excitation)
        os.makedirs(excitation_path, exist_ok=True)
        FDTD.GetCSX().Write2XML(os.path.join(excitation_path, model_basename + '.xml'))
    else:
        simulation_setup.runSimulation(FDTD=FDTD, settings=settings)
    if args.preview_only:
        break

if not args.preview_only and not args.prepare_only:
    f = np.linspace(settings['fstart'], settings['fstop'], settings['numfreq'])
    n = simulation_ports.portcount
    s = np.empty((n, n, len(f)), dtype=complex)
    for i in range(1, n + 1):
        for j in range(1, n + 1):
            s[i-1, j-1] = utilities.calculate_Sij(i, j, f, sim_path, simulation_ports)
    snp = os.path.join(sim_path, model_basename + '.s' + str(n) + 'p')
    provenance = utilities.touchstone_provenance(settings, result_kind='raw')
    utilities.write_snp(s, f, snp, z0=simulation_ports.get_reference_impedance(), provenance=provenance)
    print('S-parameters:', snp, flush=True)
'''
    return text
