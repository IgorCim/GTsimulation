"""Injected source failures followed by recovery; no external network required."""
from pathlib import Path
import hashlib
import io
import runpy
from urllib.error import HTTPError
import numpy as np
import pytest
from gtsimulation.input_data import omni,ta15,atmosphere

TESTS=Path(__file__).resolve().parent
atmos_source=runpy.run_path(str(TESTS/'test_atmosphere_inputs.py'))['source']
ta15_source=runpy.run_path(str(TESTS/'test_ta15_inputs.py'))['source']


def omni_source():
    lines=[]
    for hour in (0,1):
        row=['0']*57
        for i,value in {0:2024,1:1,2:hour,38:23,28:2.3,40:-25,15:4,16:-3}.items():row[i]=str(value)
        lines.append(' '.join(row))
    return ('\n'.join(lines)+'\n').encode()


def config(model):
    if model in ('89','96'):
        return omni_source(),lambda parent:omni.download_tsyganenko_inputs('2024-01-01','2024-01-01T02:00',parent,model=model,attempts=2)
    if model=='15B':
        return ta15_source(),lambda parent:ta15.download_ta15_inputs('2023-01-01T00:30','2023-01-01T00:40',parent,attempts=2)
    return atmos_source(),lambda parent:atmosphere.download_atmosphere_inputs('2024-09-10','2024-09-11',parent,attempts=2)


def snapshot(parent):
    return {str(p.relative_to(parent)):hashlib.sha256(p.read_bytes()).hexdigest() for p in parent.rglob('*') if p.is_file()}


def read_result(model,result):
    if model in ('89','96'):return omni.load_inputs(result['input_file'],model)
    if model=='15B':return ta15.load_ta15_inputs(result['input_file'])
    return atmosphere.load_atmosphere_inputs(result['input_file'])


@pytest.mark.parametrize('model',['89','96','15B','nrlmsis'])
@pytest.mark.parametrize('failure',['timeout','404','503','malformed','missing','disk'])
def test_failure_then_recovery_preserves_previous_bundle(tmp_path,monkeypatch,model,failure):
    good,download=config(model)
    phase={'failure':False};calls=[]
    def opening(url,**kwargs):
        calls.append((phase['failure'],url))
        if phase['failure']:
            if failure=='timeout':raise TimeoutError('injected source timeout')
            if failure in ('404','503'):raise HTTPError(url,int(failure),'injected HTTP failure',{},None)
            if failure=='malformed':return io.BytesIO(b'<html>temporary error</html>')
            if failure=='missing':
                lines=good.splitlines(keepends=True)
                # Remove one required time slot/day; no invented replacement.
                return io.BytesIO(b''.join(lines[:-1] if model!='nrlmsis' else lines[:2]+lines[3:]))
        return io.BytesIO(good)
    monkeypatch.setattr(omni,'urlopen',opening)
    monkeypatch.setattr(omni.time,'sleep',lambda _:None)
    first=download(tmp_path)
    expected=read_result(model,first).copy();before=snapshot(tmp_path)
    dirs_before=set(tmp_path.iterdir());phase['failure']=True
    original_save=np.save
    def broken_save(*args,**kwargs):raise OSError('injected full disk')
    if failure=='disk':
        # For atmosphere, failure is at the worker boundary after staging exists.
        if model=='nrlmsis':
            original_run=atmosphere.subprocess.run
            def failed_worker(*args,**kwargs):
                from subprocess import CompletedProcess
                return CompletedProcess(args[0],1,'','injected worker write failure')
            monkeypatch.setattr(atmosphere.subprocess,'run',failed_worker)
        else:monkeypatch.setattr(np,'save',broken_save)
    error=TimeoutError if failure=='timeout' else HTTPError if failure in ('404','503') else (OSError if failure=='disk' and model!='nrlmsis' else ValueError)
    with pytest.raises(error):download(tmp_path)
    assert snapshot(tmp_path)==before
    assert set(tmp_path.iterdir())==dirs_before # Includes empty staging directories.
    failed_calls=[call for call in calls if call[0]]
    assert len(failed_calls)==(2 if failure in ('timeout','503') else 1)
    phase['failure']=False
    monkeypatch.setattr(np,'save',original_save)
    if failure=='disk' and model=='nrlmsis':monkeypatch.setattr(atmosphere.subprocess,'run',original_run)
    recovered=download(tmp_path)
    assert recovered['input_file']!=first['input_file']
    np.testing.assert_array_equal(read_result(model,recovered),expected)
    for relative,digest in before.items():
        assert hashlib.sha256((tmp_path/relative).read_bytes()).hexdigest()==digest
    assert len(list(tmp_path.iterdir()))==2


@pytest.mark.parametrize('model',['89','96','15B','nrlmsis'])
def test_transient_503_recovers_within_attempt_budget(tmp_path,monkeypatch,model):
    body,download=config(model);calls=[]
    def opening(url,**kwargs):
        calls.append(url)
        if len(calls)==1:raise HTTPError(url,503,'injected transient error',{},None)
        return io.BytesIO(body)
    monkeypatch.setattr(omni,'urlopen',opening)
    monkeypatch.setattr(omni.time,'sleep',lambda _:None)
    result=download(tmp_path)
    assert len(calls)==2 and len(read_result(model,result))>0
    assert len(list(tmp_path.iterdir()))==1
