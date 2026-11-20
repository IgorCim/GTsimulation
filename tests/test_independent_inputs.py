"""Independent auditor: known arithmetic, time boundaries, and wrong-content detection."""
import importlib.util
from pathlib import Path
from datetime import datetime,timedelta
import hashlib
import json
import shutil
import sys
import numpy as np
import pytest

spec=importlib.util.spec_from_file_location('audit',Path(__file__).resolve().parents[1]/'verification/check_independent_inputs.py')
a=importlib.util.module_from_spec(spec);spec.loader.exec_module(a)


@pytest.mark.parametrize('code,category',[(0,1),(3,1),(7,2),(13,2),(17,3),(23,3),(27,4),(43,5),(53,6),(57,7),(90,7)])
def test_known_kp_groups(code,category):assert a.kp_bin(code)==category


def test_bad_kp():
    with pytest.raises(ValueError):a.kp_bin(99)


def test_known_ap_history_and_boundary():
    rows={}
    for i in range(4):
        row={'F10.7_OBS':str(100+i),'F10.7_OBS_CENTER81':'110','AP_AVG':str(i+1)}
        row.update({f'AP{k}':str(i*8+k) for k in range(1,9)})
        rows[(datetime(2024,9,7)+timedelta(days=i)).date()]=row
    np.testing.assert_array_equal(a.atmosphere_expected(rows,datetime(2024,9,10)),[102,110,4,25,24,23,22,17.5,9.5])
    assert a.atmosphere_expected(rows,datetime(2024,9,10,2,59))[3]==25
    assert a.atmosphere_expected(rows,datetime(2024,9,10,3))[3]==26


@pytest.mark.parametrize('mutation',['value','time'])
def test_valid_hash_does_not_hide_bad_numbers(tmp_path,mutation):
    source=Path(__file__).resolve().parents[1]/'verification/reuse-nadxczs5/omni-2jxcjapm'
    for p in source.iterdir():shutil.copyfile(p,tmp_path/p.name)
    data=np.load(tmp_path/'inputs.npy',allow_pickle=False)
    if mutation=='value':data['T96_input'][0,0]+=1
    else:data['date'][0]+=np.timedelta64(1,'m')
    np.save(tmp_path/'inputs.npy',data,allow_pickle=False)
    m=json.loads((tmp_path/'manifest.json').read_text())
    m['input_sha256']=hashlib.sha256((tmp_path/'inputs.npy').read_bytes()).hexdigest()
    (tmp_path/'manifest.json').write_text(json.dumps(m))
    with pytest.raises(AssertionError):a.compare('96',{'input_file':str(tmp_path/'inputs.npy')})


def test_no_gt_or_pymsis_import():
    # The checker module itself uses only stdlib/numpy; assert in fresh interpreter.
    import subprocess
    code="import runpy,sys;runpy.run_path(sys.argv[1]);assert 'gtsimulation' not in sys.modules;assert 'pymsis' not in sys.modules"
    p=subprocess.run([sys.executable,'-c',code,str(Path(a.__file__))],capture_output=True,text=True,timeout=30)
    assert p.returncode==0,p.stderr
