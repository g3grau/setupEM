"""Stackup-driven preprocessing of a selected Cadence design cell.

Only explicitly selected drawing LPPs are simplified. Pin polygons and labels
are retained separately so geometry cleanup cannot erase the port inventory.
"""
from pathlib import Path
from datetime import datetime, timezone
import hashlib
import importlib.metadata
import json
import tempfile
import numpy as np


def file_identity(path):
    path=Path(path).expanduser().resolve()
    return dict(path=str(path),sha256=hashlib.sha256(path.read_bytes()).hexdigest())


def preprocess(options,work_parent=None,overwrite=False):
    import gdstk
    from gds_simplify_for_em import run_simplify,layers_from_stackup
    from gds_geometry_utils import design_cell,validate_and_repair_polygons
    if options.get('stackup_reader')=='openems':
        from gds2openEMS import stackup_reader
    else:
        from gds2palace import stackup_reader
    try:
        from .pin_preparation import read_map
        from .generated_outputs import check_outputs,publish_outputs
    except ImportError:
        from pin_preparation import read_map
        from generated_outputs import check_outputs,publish_outputs
    opts=dict(options);source=file_identity(opts['source']);stackup=file_identity(opts['stackup'])
    output=Path(opts['output']).expanduser().resolve();report_path=output.with_suffix('.prep.json')
    mapping=file_identity(opts['mapfile']) if opts.get('mapfile') else None
    inputs=[source,stackup]+([mapping] if mapping else [])
    states=check_outputs((output,report_path,output.with_suffix('.prep.log')),
        [item['path'] for item in inputs],overwrite=overwrite)
    for key in ('fill_minsize','fill_maxsize','max_hole_area','via_merge_size'):
        value=opts.get(key)
        if value is not None and (not np.isfinite(value) or value<0):raise ValueError(key+' must be finite and nonnegative.')
    if opts['fill_maxsize'] is not None and opts['fill_maxsize']<opts['fill_minsize']:
        raise ValueError('Maximum fill size must not be less than minimum fill size.')
    if int(opts['fill_mincount'])!=opts['fill_mincount'] or opts['fill_mincount']<2:raise ValueError('Fill repeat count must be at least 2.')
    _,_,metals=stackup_reader.read_substrate(stackup['path'],variable_overrides=opts.get('variable_overrides') or {})
    metal_layers,via_layers=layers_from_stackup(metals,tuple(opts.get('port_layer_range',[201,299])))
    all_physical=set(metal_layers)|{v[0] for v in via_layers}
    excluded=set(opts.get('excluded_layers',[]));metal_layers=[l for l in metal_layers if l not in excluded]
    via_layers=[v for v in via_layers if v[0] not in excluded]
    if not metal_layers:raise ValueError('No physical metal layers selected by the XML stackup.')
    lib=gdstk.read_gds(source['path'])
    name=opts.get('cell','').strip()
    if name:
        matches=[cell for cell in lib.cells if cell.name==name]
        if not matches:raise ValueError('Raw GDS cell not found: '+name)
        cell=matches[0]
    else:cell=design_cell(lib)[0]
    polygons=cell.get_polygons(apply_repetitions=True,include_paths=True)
    labels=cell.get_labels(apply_repetitions=True)
    present={(p.layer,p.datatype) for p in polygons}
    rows=read_map(Path(mapping['path'])) if mapping else []
    pin_specs={(l,d) for _,purpose,l,d in rows if purpose=='pin'}
    drop=set(opts.get('drop_datatypes',[]))
    if any(d in drop and (l,d) in present for l,d in pin_specs):
        raise ValueError('A removed datatype contains mapped pins. Remove that datatype from the removal list.')
    physical=set(metal_layers)|{v[0] for v in via_layers}
    if rows:
        drawing={(l,d) for _,purpose,l,d in rows if purpose=='drawing'}
    else:drawing={(l,d) for l,d in present if d in set(opts.get('drawing_datatypes',[0]))}
    simulation_specs=sorted(spec for spec in present&drawing if spec[0] in all_physical and spec[1] not in drop)
    selected=sorted(present&drawing)
    selected=[spec for spec in selected if spec[0] in physical and spec[1] not in drop]
    if set(selected)&pin_specs:
        raise ValueError('The stream map assigns the same layer/datatype to drawing and pins. Exclude that layer from simplification or use a distinct pin mapping.')
    if not selected or not any(l in metal_layers for l,d in selected):
        raise ValueError('No metal drawing polygons match the stackup and drawing datatype/map selection.')
    if len(selected)>65536:raise ValueError('Too many selected layer/datatype pairs.')
    virtual={spec:number for number,spec in enumerate(selected)};inverse={v:k for k,v in virtual.items()}
    work_metals=[v for (l,d),v in virtual.items() if l in metal_layers]
    work_vias=[]
    for layer,above,below in via_layers:
        for (l,d),v in virtual.items():
            if l==layer:work_vias.append((v,[n for (a,dt),n in virtual.items() if a in above],[n for (b,dt),n in virtual.items() if b in below]))
    scale=lib.unit/1e-6
    work=gdstk.Library(unit=1e-6,precision=lib.precision);work_cell=gdstk.Cell('RAW_DRAWING');work.add(work_cell)
    for polygon in polygons:
        spec=(polygon.layer,polygon.datatype)
        if spec in virtual:work_cell.add(gdstk.Polygon(polygon.points*scale,layer=virtual[spec]))
    print(f'Raw design cell: {cell.name}; input unit {lib.unit:g} m; {len(polygons)} polygons including paths',flush=True)
    print(f'Simplifying drawing LPPs: {selected}; protected pin LPPs: {sorted(pin_specs)}',flush=True)
    with tempfile.TemporaryDirectory(prefix='.setupem_raw_',dir=work_parent or output.parent) as temporary:
        temporary=Path(temporary);work_input=temporary/'drawing.gds';work_output=temporary/'simplified.gds'
        work.write_gds(work_input,max_points=8190)
        run_simplify(str(work_input),work_metals,str(work_output),cellname='RAW_DRAWING',
            do_cutouts=opts.get('do_cutouts',True),max_hole_area=opts.get('max_hole_area',1.),
            do_floating=opts.get('do_floating',True),fill_minsize=opts['fill_minsize'],
            fill_maxsize=opts['fill_maxsize'],fill_mincount=opts['fill_mincount'],
            do_merge=opts.get('do_merge',True),via_layers=work_vias,
            via_merge_size=opts.get('via_merge_size',0),fill_ground_holes=opts.get('fill_ground_holes',False))
        cleaned=gdstk.read_gds(work_output)
        _,unresolved=validate_and_repair_polygons(cleaned,work_metals)
        if unresolved:raise ValueError('Simplification left invalid metal polygons; see log. No cleaned GDS published.')
        # A repeated isolated *terminal* must not disappear as dummy fill.
        # Check the original drawing overlap under mapped pins before publishing.
        cleaned_polygons=[p for c in cleaned.top_level() for p in c.get_polygons()]
        original_by_spec={spec:[] for spec in selected};cleaned_by_spec={spec:[] for spec in selected}
        for polygon in work_cell.polygons:original_by_spec[inverse[polygon.layer]].append(polygon)
        for polygon in cleaned_polygons:cleaned_by_spec[inverse[polygon.layer]].append(polygon)
        from rtree.index import Index
        spatial={}
        def overlaps(spec,footprint,clean=False):
            key=(spec,clean);shapes=cleaned_by_spec[spec] if clean else original_by_spec[spec]
            if key not in spatial:
                spatial[key]=Index((i,(*p.bounding_box()[0],*p.bounding_box()[1]),None) for i,p in enumerate(shapes)) if shapes else Index()
            bounds=footprint.bounding_box()
            return [shapes[i] for i in spatial[key].intersection((*bounds[0],*bounds[1]))]
        checked=0;precision=max(lib.precision/1e-6,1e-9)
        for metal,purpose,layer,datatype in rows:
            if purpose!='pin':continue
            specs=[(l,d) for n,p,l,d in rows if n==metal and p=='drawing' and (l,d) in virtual]
            for pin in (p for p in polygons if (p.layer,p.datatype)==(layer,datatype)):
                footprint=gdstk.Polygon(pin.points*scale)
                for spec in specs:
                    old=gdstk.boolean(overlaps(spec,footprint),footprint,'and',precision=precision)
                    before=sum(p.area() for p in old)
                    if before<=precision**2:continue
                    after=sum(p.area() for p in gdstk.boolean(overlaps(spec,footprint,True),footprint,'and',precision=precision))
                    if after<before-max(precision**2,before*1e-6):
                        raise ValueError(f'Simplification removed drawing metal beneath a mapped {metal} pin. Disable floating-fill removal, adjust its size/repeat limits, or exclude layer {spec[0]}. No cleaned GDS published.')
                    checked+=1
        result=gdstk.Library(unit=lib.unit,precision=lib.precision);top=gdstk.Cell(cell.name);result.add(top)
        removed=0
        for polygon in polygons:
            spec=(polygon.layer,polygon.datatype)
            if polygon.datatype in drop:removed+=1
            elif spec not in virtual:top.add(polygon)
        count=0
        for clean_cell in cleaned.top_level():
            for polygon in clean_cell.get_polygons():
                layer,datatype=inverse[polygon.layer]
                top.add(gdstk.Polygon(polygon.points/scale,layer=layer,datatype=datatype));count+=1
        top.add(*labels)
        staged=temporary/'cleaned.gds';result.write_gds(staged,max_points=8190)
        for item in inputs:
            if file_identity(item['path'])!=item:raise ValueError('An input changed while processing; run again.')
        try:version=importlib.metadata.version('gds_prepare_for_EM')
        except importlib.metadata.PackageNotFoundError:version='unknown'
        report=dict(schema='setupEM.raw-preparation.v1',created_utc=datetime.now(timezone.utc).isoformat(),
            source=source,stackup=stackup,stream_map=mapping,options=opts,cell=cell.name,
            unit_m=lib.unit,precision_m=lib.precision,selected_drawing_lpps=[list(spec) for spec in selected],protected_pin_lpps=[list(spec) for spec in sorted(pin_specs)],
            simulation_drawing_lpps=[list(spec) for spec in simulation_specs],
            pin_drawing_overlaps_checked=checked,
            removed_datatype_polygons=removed,simplified_drawing_polygons=count,labels_retained=len(labels),
            hierarchy='Selected design cell flattened; other top-level cells omitted. Raw source unchanged.',
            tool=dict(name='gds_prepare_for_EM',version=version),
            adapter_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            output=dict(path=str(output),sha256=hashlib.sha256(staged.read_bytes()).hexdigest()))
        staged_report=temporary/'report.json';staged_report.write_text(json.dumps(report,indent=2)+'\n')
        publish_outputs(((staged,output),(staged_report,report_path)),overwrite=overwrite,expected=states)
    print(f'Cleaned GDS: {output}\nPreparation report: {report_path}\nOriginal pins and {len(labels)} labels retained.',flush=True)
    return report


def verified_report(options):
    output=Path(options['output']).expanduser().resolve()
    report=json.loads(output.with_suffix('.prep.json').read_text())
    if report.get('schema')!='setupEM.raw-preparation.v1' or report['options']!=options:
        raise ValueError('Raw preparation settings changed. Simplify again, replacing generated files or choosing a new output name.')
    for key in ('source','stackup','stream_map','output'):
        identity=report.get(key)
        if identity and file_identity(identity['path'])!=identity:
            raise ValueError('Preparation input or output changed: '+identity['path']+'. Simplify again.')
    return report
