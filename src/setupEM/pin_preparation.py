"""Vendor-independent GDS pin inventory and dedicated EM marker generation."""
import hashlib
import json
from functools import lru_cache
from pathlib import Path
import xml.etree.ElementTree as ET
import gdspy
import numpy as np

def read_map(path):
    rows = []
    for line in path.read_text().splitlines():
        fields = line.split('#', 1)[0].split()
        if len(fields) >= 4:
            try:
                rows.append((fields[0], fields[1], int(fields[2]), int(fields[3])))
            except ValueError:
                continue
    if not rows:
        raise ValueError('No layer/purpose/stream-layer/datatype rows in mapfile')
    return rows


def inventory(cell, rows):
    polygons = cell.get_polygons(by_spec=True)
    labels = cell.get_labels()
    pins = []
    for metal, purpose, layer, datatype in sorted(set(rows)):
        if purpose != 'pin':
            continue
        drawing = {(l, d) for n, p, l, d in rows if n == metal and p == 'drawing'}
        specs = drawing | {(layer, datatype)} | {(l,d) for n,p,l,d in rows if n == metal and p in ('label','text','net')}
        candidates = [label for label in labels
                      if (int(label.layer), int(label.texttype)) in specs
                      and label.text.strip() and not label.text.startswith('&')]
        shapes = sorted(polygons.get((layer, datatype), []),
                        key=lambda p: (*np.min(p, axis=0), *np.max(p, axis=0)))
        for shape in shapes:
            lo, hi = np.min(shape, axis=0), np.max(shape, axis=0)
            inside = [label for label in candidates
                      if gdspy.inside([tuple(label.position)], [shape])[0]]
            names = sorted({label.text for label in inside})
            match = 'inside' if len(names) == 1 else 'ambiguous' if names else 'unnamed'
            distance = None
            if not names and candidates:
                distances = [float(np.linalg.norm(np.maximum(
                    np.maximum(lo - label.position, label.position - hi), 0)))
                    for label in candidates]
                distance = min(distances)
                names = sorted({label.text for label, dist in zip(candidates, distances)
                                if abs(dist - distance) < 1e-9})
                match = 'nearest' if len(names) == 1 else 'ambiguous'
            pins.append(dict(id=len(pins) + 1, metal=metal, source=[layer, datatype],
                             names=names, match=match, label_distance=distance,
                             bbox=[lo.tolist(), hi.tolist()], _polygon=shape))
    return pins



def inspect(gds_path, rows, cellname=''):
    lib=gdspy.GdsLibrary();lib.read_gds(str(gds_path),units='import')
    tops=lib.top_level()
    if cellname:
        if cellname not in lib.cells:raise ValueError('Cell not found: '+cellname)
        cell=lib.cells[cellname]
    elif len(tops)==1:cell=tops[0]
    else:raise ValueError('Select a cell first; top-level cells: '+', '.join(c.name for c in tops))
    return lib,cell,inventory(cell,rows)


def write(gds_path, output, rows, selection, cellname='', start_layer=240, stackup='', mapfile=''):
    """selection is ordered (inventory ID, reviewed name); originals are retained."""
    source=Path(gds_path);output=Path(output);manifest=output.with_suffix('.ports.json')
    protected=[source]+[Path(x) for x in (stackup,mapfile) if x]
    for target in (output,manifest):
        if any(target.resolve()==p.resolve() or (target.exists() and p.exists() and target.samefile(p)) for p in protected):
            raise ValueError('Refusing to overwrite an input file')
        if target.exists():raise ValueError('Output already exists; choose a new output name: '+str(target))
    if not selection or len({i for i,n in selection})!=len(selection):
        raise ValueError('Select distinct pin shapes')
    if not 0<=start_layer<=65535:raise ValueError('Start layer must be in 0..65535')
    lib,cell,pins=inspect(source,rows,cellname)
    byid={p['id']:p for p in pins}
    reserved={l for _,_,l,_ in rows}
    for c in lib.cells.values():
        reserved.update(int(l) for l in c.get_layers())
        reserved.update(int(l.layer) for l in c.labels)
    if stackup:
        reserved.update(int(e.attrib['Layer']) for e in ET.parse(stackup).iter() if 'Layer' in e.attrib)
    available=iter(i for i in range(start_layer,65536) if i not in reserved)
    ports=[]
    for number,(ident,name) in enumerate(selection,1):
        if ident not in byid:raise ValueError('Unknown pin ID: '+str(ident))
        name=name.strip()
        if not name:raise ValueError('Give every selected pin a name')
        pin=byid[ident]
        try:layer=next(available)
        except StopIteration:raise ValueError('No unused GDS layers remain')
        cell.add(gdspy.Polygon(pin['_polygon'],layer=layer,datatype=0))
        center=np.mean(pin['bbox'],axis=0)
        cell.add(gdspy.Label(name,center,layer=layer,texttype=0))
        drawing=[[l,d] for n,p,l,d in rows if n==pin['metal'] and p=='drawing']
        ports.append(dict({k:v for k,v in pin.items() if not k.startswith('_')},
                          name=name,portnumber=number,source_layernum=layer,datatype=0,drawing=drawing))
    data=dict(schema='setupEM.ports.v1',input=str(source.resolve()),
              input_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),
              cell=cell.name,unit_m=lib.unit,ports=ports,mapping=[list(r) for r in rows])
    # Exclusive creation protects existing files, including races after the checks above.
    with output.open('xb') as stream:lib.write_gds(stream)
    data['output_sha256']=hashlib.sha256(output.read_bytes()).hexdigest()
    with manifest.open('x') as stream:json.dump(data,stream,indent=2);stream.write('\n')
    return data


def names_for_gds(path):
    """Read only this layout's manifest, caching hash verification between UI updates."""
    try:
        p=Path(path).resolve();m=p.with_suffix('.ports.json')
        key=tuple((s.st_ino,s.st_size,s.st_mtime_ns,s.st_ctime_ns) for s in (p.stat(),m.stat()))
        return dict(_cached_names(str(p),key))
    except (OSError,ValueError,TypeError):return {}


@lru_cache(maxsize=16)
def _cached_names(path,stat_key):
    try:
        p=Path(path);data=json.loads(p.with_suffix('.ports.json').read_text())
        if data.get('output_sha256') and hashlib.sha256(p.read_bytes()).hexdigest()!=data['output_sha256']:
            return {}
        return {int(port['source_layernum']):port.get('name') or ', '.join(port.get('names',[]))
                for port in data['ports']}
    except (OSError,ValueError,KeyError,TypeError):return {}
