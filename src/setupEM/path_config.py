"""Portable, data-only machine defaults. Project selections take precedence."""
from functools import lru_cache
from pathlib import Path
from datetime import datetime
import argparse
import json
import os
import tempfile
import warnings

DIRECTORIES={'gds','stackup','touchstone','project','stream_map','output'}
TOOLS={'lumpedmodel','broadband_python'}


def config_path():
    override=os.environ.get('SETUPEM_PATH_CONFIG')
    if override:return Path(os.path.expandvars(override)).expanduser()
    root=Path(os.environ.get('XDG_CONFIG_HOME',str(Path.home()/'.config')))
    return root/'setupEM/paths.json'


def validate_config(data):
    if not isinstance(data,dict):raise ValueError('Path snippet must be a JSON object.')
    unknown=set(data)-{'schema','directories','tools'}
    if unknown:raise ValueError('Unknown path snippet key(s): '+', '.join(sorted(unknown)))
    if data.get('schema','setupEM.paths.v1')!='setupEM.paths.v1':raise ValueError('Unsupported path snippet schema.')
    for section,allowed in [('directories',DIRECTORIES),('tools',TOOLS)]:
        values=data.get(section,{})
        if not isinstance(values,dict):raise ValueError(section+' must be an object.')
        if set(values)-allowed:raise ValueError('Unknown '+section+' key(s): '+', '.join(sorted(set(values)-allowed)))
        for key,value in values.items():
            if not isinstance(value,str):raise ValueError(section+'.'+key+' must be a path string.')
    return data


@lru_cache(maxsize=16)
def _read(path,mtime,size):
    try:return validate_config(json.loads(Path(path).read_text(encoding='utf-8')))
    except (ValueError,OSError) as error:
        warnings.warn(f'Cannot use setupEM path defaults {path}: {error}',RuntimeWarning)
        return {}


def path_defaults():
    path=config_path()
    try:
        stat=path.stat();return _read(str(path),stat.st_mtime_ns,stat.st_size)
    except FileNotFoundError:return {}
    except OSError as error:
        warnings.warn(f'Cannot read setupEM path defaults {path}: {error}',RuntimeWarning);return {}


def expand_path(value):
    return os.path.expanduser(os.path.expandvars(value))


def configured_path(section,key):
    return expand_path(path_defaults().get(section,{}).get(key,''))


def browse_start(kind,current='',fallback=''):
    """Keep an explicit current file/directory ahead of machine defaults."""
    if kind not in DIRECTORIES:raise ValueError('Unknown browse kind: '+kind)
    if current and not str(current).startswith('Please choose'):
        path=Path(expand_path(str(current)))
        if path.is_dir() or path.is_file():return str(path)
        if path.is_absolute() and path.parent.is_dir():return str(path.parent)
    default=configured_path('directories',kind)
    if default and Path(default).is_dir():return default
    return expand_path(str(fallback)) if fallback else ''


def install_config(filename):
    """Validate before replacing defaults; keep an existing snippet as a backup."""
    data=validate_config(json.loads(Path(filename).expanduser().read_text(encoding='utf-8')))
    destination=config_path();destination.parent.mkdir(parents=True,exist_ok=True)
    backup=None
    if destination.exists():
        backup=destination.with_name(destination.name+'.backup-'+datetime.now().strftime('%Y%m%d_%H%M%S_%f'))
        with backup.open('xb') as stream:stream.write(destination.read_bytes())
    temporary=None
    try:
        with tempfile.NamedTemporaryFile(mode='w',encoding='utf-8',dir=destination.parent,delete=False) as stream:
            temporary=Path(stream.name);stream.write(json.dumps(data,indent=2)+'\n')
        os.replace(temporary,destination)
    finally:
        if temporary:temporary.unlink(missing_ok=True)
    _read.cache_clear()
    return destination,backup


if __name__=='__main__':
    parser=argparse.ArgumentParser(description='Install or locate portable setupEM path defaults.')
    parser.add_argument('--install',metavar='JSON',help='Install a snippet, preserving existing defaults as a backup')
    args=parser.parse_args()
    if args.install:
        try:destination,backup=install_config(args.install)
        except (OSError,ValueError) as error:parser.error(str(error))
        print(destination)
        if backup:print('Previous defaults: '+str(backup))
    else:print(config_path())
