import json
import subprocess
import os
import numpy as np
import pytest
import skrf as rf
from setupEM.lumped_models import prepare_model_run
from setupEM.network_parameters import ExtractionSpec


def test_adapter_reduces_open_ports_and_records_source_and_command(tmp_path):
    repo=tmp_path/'repository';script=repo/'rlgc_from_s2p/rlgc_from_s2p.py'
    script.parent.mkdir(parents=True);script.write_text('print("example tool")')
    f=np.linspace(1e8,8e9,51)
    z=np.broadcast_to(np.array([[60,5,8],[5,65,10],[8,10,70]],complex),(len(f),3,3))
    net=rf.Network(f=f,z=z,z0=[25,75,100]);source={'path':'/source.s3p','sha256':'original'}
    spec=ExtractionSpec(port_a=3,port_b=1,unused_ports='open',line_length_m=.001)
    command,folder=prepare_model_run(net,source,spec,repo,tmp_path/'result','rlgc_from_s2p')
    selected=rf.Network(str(folder/'selected_ports.s2p'))
    np.testing.assert_allclose(selected.z,z[:,[2,0]][:,:,[2,0]],rtol=1e-12,atol=1e-12)
    np.testing.assert_allclose(selected.z0,50)
    report=json.loads((folder/'run.json').read_text())
    assert report['source']==source and report['selected_ports']==[3,1]
    assert report['unused_ports']=='open' and command[-3:]==['3.0','1000.0','50']
    with pytest.raises(FileExistsError):prepare_model_run(net,source,spec,repo,folder,'rlgc_from_s2p')
    assert (folder/'selected_ports.s2p').exists()


def test_worker_captures_plots_and_failure_exit_status(tmp_path):
    repo=tmp_path/'repository';script=repo/'inductor_fit/inductor_fit.py'
    script.parent.mkdir(parents=True)
    script.write_text('from matplotlib import pyplot as plt\nplt.plot([0,1],[0,1])\nplt.show()\nprint("model output")\nraise ValueError("fit failed")\n')
    net=rf.Network(f=np.linspace(1e8,8e9,11),s=np.zeros((11,2,2)),z0=50)
    command,folder=prepare_model_run(net,{},ExtractionSpec(),repo,tmp_path/'result','inductor_fit',basic=True,spectre=True)
    assert command[-2:]==['--basic','--spectre']
    result=subprocess.run(command,cwd=folder,env=dict(os.environ,MPLCONFIGDIR=str(tmp_path/'mpl')),capture_output=True,text=True,timeout=30)
    assert result.returncode!=0 and 'fit failed' in result.stderr and 'model output' in result.stdout
    assert (folder/'fit_plot_1.png').stat().st_size>1000
