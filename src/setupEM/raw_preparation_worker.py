"""Background entry point; importing the GUI or an IHP-specific CLI is avoided."""
import json
import sys
from pathlib import Path
try:
    from .raw_preparation import preprocess
except ImportError:
    from raw_preparation import preprocess

if __name__=='__main__':
    job=Path(sys.argv[1])
    preprocess(json.loads(job.read_text(encoding='utf-8')),work_parent=job.parent,overwrite='--overwrite' in sys.argv[2:])
