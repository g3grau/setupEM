"""Portable, data-only machine defaults. Project selections take precedence."""
from functools import lru_cache
from pathlib import Path
from datetime import datetime
import argparse
import json
import os
import tempfile
import warnings

DIRECTORIES={'gds','stackup','touchstone','project','stream_map','output','models','fdtd','fem'}
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


def configured_path(section,key,project=None):
    value=expand_path(path_defaults().get(section,{}).get(key,''))
    if not value or Path(value).is_absolute():return value
    # Machine/tool defaults have a stable base even before a project is opened.
    base=(project or configured_path('directories','project')) if section=='directories' and key!='project' else None
    return str((Path(base) if base else config_path().resolve().parent).joinpath(value).resolve())


def project_directory(window=None,source=''):
    """Resolve project context locally to a window, never from the process cwd."""
    if window is not None:
        root=getattr(window,'_project_root',None)
        if root:return str(Path(root).resolve())
        config=getattr(window,'user_inputs_file',None)
        if config and Path(config).is_file():
            folder=Path(config).resolve().parent
            try:relative=json.loads(Path(config).read_text()).get('project_root','.')
            except (ValueError,OSError,AttributeError):relative='.'
            if isinstance(relative,str):return str((folder/expand_path(relative)).resolve())
        raw=getattr(getattr(window,'file_tab',None),'raw_input',None)
        candidates=[raw.source.text() if raw else '',getattr(window,'saved_values',{}).get('GdsFile',''),
                    getattr(getattr(window,'script_model',None),'path','')]
        for path in candidates:
            if path and not str(path).startswith('Please choose') and Path(expand_path(str(path))).is_file():
                return str(Path(expand_path(str(path))).resolve().parent)
    return configured_path('directories','project') or (str(Path(source).expanduser().resolve().parent) if source else '')


def output_directory(kind,window=None,source='',fallback='',create=False):
    project=project_directory(window,source)
    value=configured_path('directories',kind,project=project)
    if not value and kind=='models':value=configured_path('directories','output',project=project)
    value=value or str(fallback)
    if value and create:Path(value).mkdir(parents=True,exist_ok=True)
    return value


def output_filename(kind,name,window=None,source='',fallback=''):
    folder=output_directory(kind,window,source,fallback)
    return str(Path(folder)/name) if folder else name


def collect_touchstone(files,directory):
    """Publish result copies; preserve a differing previous network by hash name."""
    import hashlib
    import shutil
    folder=Path(directory);folder.mkdir(parents=True,exist_ok=True)
    outputs=[]
    for filename in files:
        source=Path(filename)
        if folder.resolve() in source.resolve().parents:continue
        digest=hashlib.sha256(source.read_bytes()).hexdigest()
        target=folder/source.name
        if target.exists() and hashlib.sha256(target.read_bytes()).hexdigest()!=digest:
            target=folder/(source.stem+'_'+digest[:12]+source.suffix)
        if target.exists():
            if hashlib.sha256(target.read_bytes()).hexdigest()!=digest:raise ValueError('Result name collision: '+str(target))
        else:
            # Exclusive creation protects a prior result even if another process publishes too.
            with target.open('xb') as output,source.open('rb') as original:shutil.copyfileobj(original,output)
        outputs.append(str(target))
    return outputs


def browse_start(kind,current='',fallback='',project=None):
    """Keep an explicit current file/directory ahead of machine defaults."""
    if kind not in DIRECTORIES:raise ValueError('Unknown browse kind: '+kind)
    if current and not str(current).startswith('Please choose'):
        path=Path(expand_path(str(current)))
        if not path.is_absolute() and project:path=Path(project)/path
        if path.is_dir() or path.is_file():return str(path)
        if path.is_absolute() and path.parent.is_dir():return str(path.parent)
    default=configured_path('directories',kind,project=project)
    if default and (Path(default).is_dir() or Path(default).is_file()):return default
    # An as-yet-uncreated relative project folder must not send the dialog to cwd.
    raw=expand_path(path_defaults().get('directories',{}).get(kind,''))
    if raw and not Path(raw).is_absolute() and project:
        for parent in Path(default).parents:
            if parent.is_dir():return str(parent)
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
