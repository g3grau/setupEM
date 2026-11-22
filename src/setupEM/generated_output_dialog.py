"""One overwrite policy for generated GDS files and sidecars."""
from pathlib import Path
from PySide6.QtWidgets import QMessageBox,QFileDialog
try:
    from .generated_outputs import check_outputs
except ImportError:
    from generated_outputs import check_outputs


def choose_output(parent,app_name,filename,suffixes=(),inputs=()):
    try:
        from .setup_common import get_preference_bool
    except ImportError:
        from setup_common import get_preference_bool
    output=Path(filename).expanduser().absolute()
    while True:
        targets=[output]+[output.with_suffix(suffix) for suffix in suffixes]
        check_outputs(targets,inputs,overwrite=True)
        existing=[p for p in targets if p.exists()]
        if not existing:return str(output),False
        if get_preference_bool(app_name,'overwrite_generated_gds',False):return str(output),True
        box=QMessageBox(parent);box.setWindowTitle('Generated files already exist')
        box.setIcon(QMessageBox.Question)
        box.setText('Replace the previous generated files, or choose a different output filename?')
        box.setInformativeText('\n'.join(map(str,existing)))
        replace=box.addButton('Replace generated files',QMessageBox.DestructiveRole)
        another=box.addButton('Choose another filename…',QMessageBox.ActionRole)
        cancel=box.addButton(QMessageBox.Cancel);box.setDefaultButton(cancel)
        box.exec()
        if box.clickedButton()==replace:return str(output),True
        if box.clickedButton()!=another:return None,False
        filename,_=QFileDialog.getSaveFileName(parent,'Choose another generated GDS filename',str(output),
            'GDSII (*.gds *.GDS);;All files (*)',options=QFileDialog.DontConfirmOverwrite)
        if not filename:return None,False
        output=Path(filename).expanduser().absolute()
