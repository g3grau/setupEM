"""Execution controls and portable Palace run-script settings; no solver bindings."""
from pathlib import Path
import re

PALACE_ENV = {'palace_mpi_processes': 'PALACE_NP', 'palace_omp_threads': 'OMP_NUM_THREADS',
              'palace_blas_threads': 'OPENBLAS_NUM_THREADS'}
BEGIN = '# BEGIN setupEM parallel settings'
END = '# END setupEM parallel settings'


def palace_execution_block(values):
    lines = []
    for key, name in PALACE_ENV.items():
        value = values.get(key)
        if value is None or value == 0:
            continue
        if isinstance(value, bool) or int(value) != value or not 1 <= int(value) <= 4096:
            raise ValueError(f'{key} must be unset or an integer between 1 and 4096')
        lines.append(f'export {name}={int(value)}')
    return '\n'.join([BEGIN, *lines, END]) if lines else ''


def configure_palace_run_script(path, values):
    """Update only our marked block, retaining calibration/custom launcher commands."""
    path = Path(path)
    text = path.read_text()
    text = re.sub(r'^' + re.escape(BEGIN) + r'\n.*?^' + re.escape(END) + r'\n?',
                  '', text, flags=re.MULTILINE | re.DOTALL)
    block = palace_execution_block(values)
    if block:
        head, sep, tail = text.partition('\n')
        text = head + sep + block + '\n' + tail if head.startswith('#!') else block + '\n' + text
    with path.open('w', newline='\n') as stream:
        stream.write(text)


def palace_script_lines(values):
    """Self-contained exporter lines; generated scripts need no setupEM at runtime."""
    block = palace_execution_block(values)
    if not block:
        return []
    keys = {name: key for key, name in PALACE_ENV.items() if values.get(key)}
    expressions = ', '.join(f'{name!r}: settings[{key!r}]' for name, key in keys.items())
    return ['# Parallel options selected in setupEM Settings.',
            "run_script = os.path.join(settings['sim_path'], 'run_sim')",
            "with open(run_script, encoding='utf-8') as stream:",
            '    run_text = stream.read()',
            "head, sep, tail = run_text.partition('\\n')",
            'parallel_env = {' + expressions + '}',
            "parallel_block = '# BEGIN setupEM parallel settings\\n' + '\\n'.join(",
            "    f'export {key}={int(value)}' for key, value in parallel_env.items()) + '\\n# END setupEM parallel settings'",
            "with open(run_script, 'w', encoding='utf-8', newline='\\n') as stream:",
            "    stream.write(head + sep + parallel_block + '\\n' + tail)"]
