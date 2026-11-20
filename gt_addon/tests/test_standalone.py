"""Check independent delivery, safe inputs, and absence of model imports."""
from pathlib import Path
import subprocess
import sys
import numpy as np
import pytest
import fetcher


def test_gt_import_is_never_requested():
    script='''
import sys,importlib.abc
class BlockGT(importlib.abc.MetaPathFinder):
 def find_spec(self,fullname,path=None,target=None):
  if fullname=='gtsimulation' or fullname.startswith('gtsimulation.'):
   raise AssertionError('GT import forbidden for standalone downloader')
sys.meta_path.insert(0,BlockGT())
sys.path.insert(0,sys.argv[1])
import fetcher
assert not any(n=='gtsimulation' or n.startswith('gtsimulation.') for n in sys.modules)
print('standalone')
'''
    p=subprocess.run([sys.executable,'-I','-c',script,str(Path(__file__).resolve().parents[1])],capture_output=True,text=True,timeout=30)
    assert p.returncode==0,p.stderr
    assert p.stdout.strip()=='standalone'


@pytest.mark.parametrize('loader',[lambda p:fetcher.load_inputs(p,'96'),fetcher.load_ta15_inputs,fetcher.load_atmosphere_inputs])
def test_pickle_not_executed(tmp_path,loader):
    path=tmp_path/'object.npy';np.save(path,np.array([{'untrusted':True}],dtype=object))
    with pytest.raises(ValueError):loader(path)


def test_cli_can_run_without_repo_on_path(tmp_path):
    script=Path(__file__).resolve().parents[1]/'fetcher.py'
    p=subprocess.run([sys.executable,'-I',str(script),'--help'],cwd=tmp_path,capture_output=True,text=True,timeout=30)
    assert p.returncode==0 and 'nrlmsis' in p.stdout
