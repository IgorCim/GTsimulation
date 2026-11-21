"""Windows cache publication collisions and preservation on persistent refusal."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
import errno
import threading
import pytest
import fetcher as f


def windows_error(code):
    error=PermissionError(errno.EACCES,'Injected Windows file lock')
    error.winerror=code
    return error


@pytest.mark.parametrize('filename',['data.csv','meta.json'])
@pytest.mark.parametrize('code',[5,32,33])
def test_transient_windows_conflict_recovers(tmp_path,monkeypatch,filename,code):
    original=Path.replace;calls=[];sleeps=[]
    def replace(path,target):
        if path.name==filename:
            calls.append(1)
            if len(calls)==1:raise windows_error(code)
        return original(path,target)
    monkeypatch.setattr(Path,'replace',replace)
    monkeypatch.setattr(f.time,'sleep',sleeps.append)
    now=datetime.now(timezone.utc)
    f._save_weather_cache(tmp_path,f.MSIS_URL,b'complete',now.isoformat())
    assert f._cached_weather(tmp_path,f.MSIS_URL,now)[0]==b'complete'
    assert len(calls)==2 and sleeps==[0.01]
    assert not list(tmp_path.glob('.source-*'))


@pytest.mark.parametrize('code',[5,32,33])
def test_persistent_conflict_has_budget_and_preserves_published_cache(tmp_path,monkeypatch,code):
    now=datetime.now(timezone.utc)
    f._save_weather_cache(tmp_path,f.MSIS_URL,b'old',now.isoformat())
    original=Path.replace;calls=[];sleeps=[]
    def replace(path,target):
        if path.name=='meta.json':calls.append(1);raise windows_error(code)
        return original(path,target)
    monkeypatch.setattr(Path,'replace',replace)
    monkeypatch.setattr(f.time,'sleep',sleeps.append)
    with pytest.raises(PermissionError):f._save_weather_cache(tmp_path,f.MSIS_URL,b'new',now.isoformat())
    assert len(calls)==8 and len(sleeps)==7
    assert f._cached_weather(tmp_path,f.MSIS_URL,now)[0]==b'old'
    assert not list(tmp_path.glob('.source-*'))


def test_unrelated_permission_failure_not_retried(tmp_path,monkeypatch):
    calls=[]
    def denied(*a):calls.append(1);raise windows_error(123)
    monkeypatch.setattr(Path,'replace',denied)
    with pytest.raises(PermissionError):f._save_weather_cache(tmp_path,f.MSIS_URL,b'new',datetime.now(timezone.utc).isoformat())
    assert len(calls)==1 and not list(tmp_path.iterdir())


def test_readers_and_writers_observe_complete_cache(tmp_path):
    now=datetime.now(timezone.utc).isoformat()
    bodies=[(str(i)*70000).encode() for i in range(6)]
    f._save_weather_cache(tmp_path,f.MSIS_URL,bodies[0],now)
    barrier=threading.Barrier(6)
    def write(index):
        barrier.wait(timeout=10)
        for i in range(12):f._save_weather_cache(tmp_path,f.MSIS_URL,bodies[(index+i)%6],now)
    def read(index):
        barrier.wait(timeout=10)
        for i in range(100):
            body,stamp=f._cached_weather(tmp_path,f.MSIS_URL,datetime.now(timezone.utc))
            assert body in bodies and stamp==now
    with ThreadPoolExecutor(max_workers=6) as pool:
        jobs=[pool.submit(write,i) for i in range(3)]+[pool.submit(read,i) for i in range(3)]
        for job in jobs:job.result(timeout=30)
    assert not list(tmp_path.glob('.source-*'))


@pytest.mark.parametrize('kind',['metadata','body'])
def test_transient_cache_read_conflict_recovers(tmp_path,monkeypatch,kind):
    now=datetime.now(timezone.utc)
    f._save_weather_cache(tmp_path,f.MSIS_URL,b'complete',now.isoformat())
    method='read_text' if kind=='metadata' else 'read_bytes'
    original=getattr(Path,method);calls=[];sleeps=[]
    def reading(path,*a,**k):
        calls.append(1)
        if len(calls)==1:raise windows_error(32)
        return original(path,*a,**k)
    monkeypatch.setattr(Path,method,reading)
    monkeypatch.setattr(f.time,'sleep',sleeps.append)
    assert f._cached_weather(tmp_path,f.MSIS_URL,now)[0]==b'complete'
    assert sleeps==[0.01]


def test_existing_hashed_body_is_not_replaced(tmp_path,monkeypatch):
    now=datetime.now(timezone.utc).isoformat()
    f._save_weather_cache(tmp_path,f.MSIS_URL,b'same',now)
    original=Path.replace
    def replace(path,target):
        assert path.name!='data.csv'
        return original(path,target)
    monkeypatch.setattr(Path,'replace',replace)
    f._save_weather_cache(tmp_path,f.MSIS_URL,b'same',now)
    assert f._cached_weather(tmp_path,f.MSIS_URL,datetime.now(timezone.utc))[0]==b'same'



def test_existing_corrupt_hashed_body_is_not_published(tmp_path):
    now=datetime.now(timezone.utc).isoformat()
    f._save_weather_cache(tmp_path,f.MSIS_URL,b'original',now)
    next(tmp_path.glob('*.csv')).write_bytes(b'corrupt')
    meta=next(tmp_path.glob('*.json')).read_bytes()
    with pytest.raises(ValueError,match='does not match'):
        f._save_weather_cache(tmp_path,f.MSIS_URL,b'original',now)
    assert next(tmp_path.glob('*.json')).read_bytes()==meta
    assert not list(tmp_path.glob('.source-*'))


def test_independent_processes_share_cache_safely(tmp_path):
    import subprocess
    import sys
    now=datetime.now(timezone.utc).isoformat()
    f._save_weather_cache(tmp_path,f.MSIS_URL,b'seed',now)
    code="""
import sys
sys.path.insert(0, sys.argv[1])
from datetime import datetime, timezone
import fetcher as f
from pathlib import Path
root=Path(sys.argv[2])
for step in range(20):
    body=(str(step%3)*70000).encode()
    f._save_weather_cache(root,f.MSIS_URL,body,sys.argv[3])
    observed,stamp=f._cached_weather(root,f.MSIS_URL,datetime.now(timezone.utc))
    assert observed in [b'seed']+[(str(i)*70000).encode() for i in range(3)]
    assert stamp==sys.argv[3]
print('PASS: 20 writes and verified reads')
"""
    def child(index):
        result=subprocess.run([sys.executable,'-c',code,str(Path(f.__file__).parent),str(tmp_path),now],
                              capture_output=True,text=True,timeout=30)
        assert result.returncode==0,result.stdout+result.stderr
        assert 'PASS:' in result.stdout
    with ThreadPoolExecutor(max_workers=4) as pool:list(pool.map(child,range(4)))
    assert not list(tmp_path.glob('.source-*'))
