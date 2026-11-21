"""Run an external CLI unchanged; capture its plot windows as reviewable PNGs."""
import runpy
import sys
from pathlib import Path
import matplotlib
matplotlib.use('Agg')
from matplotlib import pyplot as plt


def save_plots(*args,**kwargs):
    for number in plt.get_fignums():
        plt.figure(number).savefig(Path.cwd()/f'fit_plot_{number}.png',dpi=150,bbox_inches='tight')
    plt.close('all')


if __name__=='__main__':
    plt.show=save_plots
    script=sys.argv[1];sys.argv=sys.argv[1:]
    try:runpy.run_path(script,run_name='__main__')
    finally:save_plots()
