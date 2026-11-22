"""Protected, staged replacement of generated artifacts and their sidecars."""
from pathlib import Path
import os
import shutil
import tempfile


def file_state(path):
    try:
        s=Path(path).stat()
        return (s.st_dev,s.st_ino,s.st_size,s.st_mtime_ns,s.st_ctime_ns)
    except FileNotFoundError:return None


def check_outputs(paths,inputs=(),overwrite=False):
    paths=[Path(p).expanduser().absolute() for p in paths]
    protected=[Path(p).expanduser().absolute() for p in inputs if p]
    if len({p.resolve() for p in paths})!=len(paths):raise ValueError('Generated output paths must be distinct.')
    for target in paths:
        for source in protected:
            if target.resolve()==source.resolve() or (target.exists() and source.exists() and target.samefile(source)):
                raise ValueError('Refusing to overwrite an input file: '+str(target))
        if target.is_symlink() or (target.exists() and not target.is_file()):
            raise ValueError('Choose a regular generated output file: '+str(target))
        if target.exists() and not overwrite:raise ValueError('Output already exists; choose a new name: '+str(target))
    return {str(p):file_state(p) for p in paths}


def publish_outputs(pairs,overwrite=False,expected=None):
    """Publish complete staged files, restoring previous outputs on a write failure.

    The expected states are captured before computation, so a separately changed
    output cannot silently replace the version whose overwrite was approved.
    """
    pairs=[(Path(source),Path(target).expanduser().absolute()) for source,target in pairs]
    states=expected if expected is not None else check_outputs([p for _,p in pairs],overwrite=overwrite)
    for staged,target in pairs:
        if file_state(target)!=states.get(str(target)):
            raise ValueError('Generated output changed during preparation; retry: '+str(target))
        if target.exists() and not overwrite:raise ValueError('Output already exists: '+str(target))
    backup_dir=Path(tempfile.mkdtemp(prefix='.setupem_replace_',dir=pairs[0][1].parent))
    backups={};installed=[];keep_backup=False
    try:
        for index,(staged,target) in enumerate(pairs):
            if target.exists():
                backup=backup_dir/str(index);shutil.copy2(target,backup);backups[target]=backup
        for staged,target in pairs:
            if file_state(target)!=states.get(str(target)):
                raise ValueError('Generated output changed during preparation; retry: '+str(target))
            if target in backups:os.replace(staged,target)
            else:os.link(staged,target)  # Exclusive creation, including late filesystem races.
            installed.append(target)
    except BaseException:
        try:
            for target in reversed(installed):
                if target in backups:os.replace(backups[target],target)
                else:target.unlink(missing_ok=True)
        except OSError as error:
            keep_backup=True
            raise RuntimeError('Could not restore previous generated files; recovery copies are in '+str(backup_dir)) from error
        raise
    finally:
        if not keep_backup:shutil.rmtree(backup_dir)
