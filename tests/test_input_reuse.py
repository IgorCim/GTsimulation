"""Verify that the evidence checker detects tampering and actual network attempts."""
from pathlib import Path
import importlib.util
import hashlib
import json
import subprocess
import sys
import pytest

spec=importlib.util.spec_from_file_location('reuse',Path(__file__).resolve().parents[1]/'verification/check_reuse.py')
r=importlib.util.module_from_spec(spec);spec.loader.exec_module(r)


def make_bundle(tmp_path):
    (tmp_path/'inputs.npy').write_bytes(b'input bytes')
    (tmp_path/'source.dat').write_bytes(b'source bytes')
    manifest={'input_sha256':hashlib.sha256(b'input bytes').hexdigest(),
              'sources':[{'url':'https://example.org/source.dat','sha256':hashlib.sha256(b'source bytes').hexdigest()}]}
    (tmp_path/'manifest.json').write_text(json.dumps(manifest))
    return {'input_file':str(tmp_path/'inputs.npy')}


def test_integrity_checker(tmp_path):
    assert len(r.verify_bundle(make_bundle(tmp_path)))==2


@pytest.mark.parametrize('filename',['inputs.npy','source.dat'])
def test_tampering_rejected(tmp_path,filename):
    bundle=make_bundle(tmp_path)
    (tmp_path/filename).write_bytes(b'changed')
    with pytest.raises(ValueError,match='Integrity mismatch'):r.verify_bundle(bundle)


def test_offline_guard_prevents_connections():
    # Invoke evaluate with an empty table mapping. Its audit hook is installed
    # before imports; then explicitly test a localhost connection in that process.
    code='''
import runpy, socket
r=runpy.run_path(__import__('sys').argv[1])
try: r['evaluate']({},True)
except KeyError: pass
try: socket.create_connection(('127.0.0.1',9),timeout=1)
except RuntimeError as e:
 assert 'Network disabled' in str(e)
 print('blocked')
else: raise AssertionError('Network was not blocked')
'''
    proc=subprocess.run([sys.executable,'-c',code,str(Path(r.__file__))],capture_output=True,text=True,timeout=60)
    assert proc.returncode==0,proc.stderr
    assert proc.stdout.strip()=='blocked'
