"""Additional boundary, persistence and cache scenarios; no external network."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import csv
import io
import json
from pathlib import Path
import runpy
from subprocess import CompletedProcess
from urllib.error import HTTPError
import numpy as np
import pytest
import fetcher as f

TESTS=Path(__file__).resolve().parent
RECOVERY=runpy.run_path(str(TESTS/'test_input_recovery.py'))
OMNI=runpy.run_path(str(TESTS/'test_input_data.py'))
ATM=runpy.run_path(str(TESTS/'test_atmosphere_inputs.py'))
TA=runpy.run_path(str(TESTS/'test_ta15_inputs.py'))
TRANSPORT=runpy.run_path(str(TESTS/'test_celestrak_transport.py'))


@pytest.mark.parametrize('model',['89','96','15B','nrlmsis'])
def test_unicode_spaces_output_and_roundtrip(tmp_path,monkeypatch,model):
    body,download=RECOVERY['config'](model)
    monkeypatch.setattr(f,'_download',lambda *a,**k:body)
    parent=tmp_path/'Входы физика с пробелами'
    result=download(parent)
    rows=RECOVERY['read_result'](model,result)
    assert len(rows)==(24 if model=='nrlmsis' else 2)
    assert Path(result['input_file']).is_relative_to(parent)
    meta=json.loads(Path(result['manifest']).read_text(encoding='utf-8'))
    assert meta['input_sha256']==f.hashlib.sha256(Path(result['input_file']).read_bytes()).hexdigest()


@pytest.mark.parametrize('model',['89','96','15B','nrlmsis'])
def test_final_rename_failure_preserves_old_bundle(tmp_path,monkeypatch,model):
    body,download=RECOVERY['config'](model)
    monkeypatch.setattr(f,'_download',lambda *a,**k:body)
    first=download(tmp_path)
    before=RECOVERY['snapshot'](tmp_path)
    def denied(*a,**k):raise PermissionError('Injected publication denied')
    monkeypatch.setattr(Path,'rename',denied)
    with pytest.raises(PermissionError,match='publication denied'):download(tmp_path)
    assert RECOVERY['snapshot'](tmp_path)==before
    assert len(list(tmp_path.iterdir()))==1
    RECOVERY['read_result'](model,first)


@pytest.mark.parametrize('start,day',[('2024-02-29',60),('2024-03-01',61)])
def test_omni_leap_day_and_exclusive_end(tmp_path,monkeypatch,start,day):
    body=OMNI['record'](day=day)+OMNI['record'](day=day,hour=1,**{'28':7.0})
    monkeypatch.setattr(f,'_download',lambda *a,**k:body)
    result=f.download_tsyganenko_inputs(start,start+'T01:00',tmp_path)
    rows=f.load_inputs(result['input_file'],'96')
    assert len(rows)==1 and rows['date'][0]==np.datetime64(start)
    assert rows['T96_input'][0,0]==2.3


def test_ta15_year_boundary_with_timezone(tmp_path,monkeypatch):
    line=TA['source']().decode().splitlines()[0].split()
    previous=line.copy();previous[:4]=['2023','365','23','55']
    following=line.copy();following[:4]=['2024','1','0','0']
    def download(url,*a,**k):
        fields=previous if '2023_' in url else following
        return (' '.join(fields)+'\n').encode()
    monkeypatch.setattr(f,'_download',download)
    result=f.download_ta15_inputs('2024-01-01T00:55+01:00','2024-01-01T01:05+01:00',tmp_path)
    rows=f.load_ta15_inputs(result['input_file'])
    np.testing.assert_array_equal(rows['date'],np.array(['2023-12-31T23:55','2024-01-01T00:00'],dtype='datetime64[s]'))
    assert len(json.loads(Path(result['manifest']).read_text())['sources'])==2


@pytest.mark.parametrize('code',[401,403,404,410])
def test_permanent_http_failure_not_retried(monkeypatch,code):
    calls=[]
    def denied(*a,**k):calls.append(1);raise HTTPError('https://example.org/file',code,'denied',{},None)
    monkeypatch.setattr(f,'urlopen',denied)
    with pytest.raises(HTTPError):f._download('https://example.org/file',1,3,range_requests=True)
    assert len(calls)==1


def test_short_retry_after_respected(monkeypatch):
    calls=[];sleeps=[]
    def opening(*a,**k):
        calls.append(1)
        if len(calls)==1:raise HTTPError('https://example.org/file',503,'busy',{'Retry-After':'2'},None)
        return TRANSPORT['Response'](b'good',200,{'Content-Length':'4'})
    monkeypatch.setattr(f,'urlopen',opening)
    monkeypatch.setattr(f.time,'sleep',sleeps.append)
    assert f._download('https://example.org/file',3,2,range_requests=True)==b'good'
    assert sleeps==[2] and len(calls)==2


@pytest.mark.parametrize('body,length,limit',[(b'bad','4',20),(b'too large','9',4)])
def test_full_response_truncation_or_oversize_rejected(monkeypatch,body,length,limit):
    monkeypatch.setattr(f,'urlopen',lambda *a,**k:TRANSPORT['Response'](body,200,{'Content-Length':length}))
    with pytest.raises(ValueError):f._download('https://example.org/file',1,1,max_bytes=limit,range_requests=True)


def test_concurrent_cache_publish_never_mixes_body_and_metadata(tmp_path):
    now=datetime.now(timezone.utc).isoformat()
    bodies=[(str(i)*70000).encode() for i in range(6)]
    with ThreadPoolExecutor(max_workers=3) as pool:
        list(pool.map(lambda body:f._save_weather_cache(tmp_path,f.MSIS_URL,body,now),bodies))
    cached=f._cached_weather(tmp_path,f.MSIS_URL,datetime.now(timezone.utc))
    assert cached[0] in bodies and cached[1]==now
    assert not list(tmp_path.glob('.source-*'))


def test_cache_url_isolation(tmp_path):
    now=datetime.now(timezone.utc)
    f._save_weather_cache(tmp_path,f.MSIS_URL,b'all',now.isoformat())
    assert f._cached_weather(tmp_path,f.MSIS_RECENT_URL,now) is None
    assert f._cached_weather(tmp_path,f.MSIS_URL,now)[0]==b'all'


def test_expired_cache_does_not_hide_network_failure(tmp_path,monkeypatch):
    cache=tmp_path/'cache';out=tmp_path/'out';out.mkdir()
    f._save_weather_cache(cache,f.MSIS_RECENT_URL,ATM['source'](),(datetime.now(timezone.utc)-timedelta(hours=4)).isoformat())
    before=RECOVERY['snapshot'](cache)
    def unavailable(*a,**k):raise TimeoutError('Injected offline')
    monkeypatch.setattr(f,'_download',unavailable)
    with pytest.raises(TimeoutError):f.download_atmosphere_inputs('2024-09-10','2024-09-11',out,cache_dir=cache)
    assert not list(out.iterdir()) and RECOVERY['snapshot'](cache)==before


@pytest.mark.parametrize('problem',['missing_body','invalid_json','path_digest'])
def test_broken_cache_never_accepted(tmp_path,problem):
    now=datetime.now(timezone.utc)
    f._save_weather_cache(tmp_path,f.MSIS_URL,b'good',now.isoformat())
    meta=next(tmp_path.glob('*.json'))
    if problem=='missing_body':next(tmp_path.glob('*.csv')).unlink()
    elif problem=='invalid_json':meta.write_text('{broken',encoding='utf-8')
    else:
        data=json.loads(meta.read_text());data['sha256']='../outside'
        meta.write_text(json.dumps(data))
    with pytest.raises((ValueError,OSError)):f._cached_weather(tmp_path,f.MSIS_URL,now)


def test_atmosphere_bom_reversed_days_and_timezone(tmp_path,monkeypatch):
    lines=ATM['source']().decode().splitlines()
    body=('\ufeff'+lines[0]+'\n'+'\n'.join(reversed(lines[1:]))+'\n').encode('utf-8')
    monkeypatch.setattr(f,'_download',lambda *a,**k:body)
    result=f.download_atmosphere_inputs('2024-09-10T03:00+03:00','2024-09-10T06:00+03:00',tmp_path)
    rows=f.load_atmosphere_inputs(result['input_file'])
    assert len(rows)==3 and rows['date'][0]==np.datetime64('2024-09-10T00:00')
    np.testing.assert_array_equal(rows['ap'][:,1],[25,25,25])


@pytest.mark.parametrize('mutation',['duplicate','missing_first_history','missing_previous_day'])
def test_atmosphere_required_days_not_invented(tmp_path,monkeypatch,mutation):
    lines=ATM['source']().splitlines(keepends=True)
    if mutation=='duplicate':lines.append(lines[2])
    else:lines.pop(1 if mutation=='missing_first_history' else 3)
    monkeypatch.setattr(f,'_download',lambda *a,**k:b''.join(lines))
    with pytest.raises(ValueError):f.download_atmosphere_inputs('2024-09-10','2024-09-11',tmp_path)
    assert not list(tmp_path.iterdir())


@pytest.mark.parametrize('mutation',['shifted','short','long'])
def test_worker_success_with_wrong_interval_is_rejected(tmp_path,monkeypatch,mutation):
    monkeypatch.setattr(f,'_download',lambda *a,**k:ATM['source']())
    def wrong_output(command,**kwargs):
        start=np.datetime64(command[4]);end=np.datetime64(command[5])
        if mutation=='shifted':start+=np.timedelta64(1,'D');end+=np.timedelta64(1,'D')
        if mutation=='short':end-=np.timedelta64(1,'h')
        if mutation=='long':end+=np.timedelta64(1,'h')
        dates=np.arange(start,end,np.timedelta64(1,'h'))
        rows=np.empty(len(dates),dtype=f.MSIS_DTYPE)
        rows['date']=dates;rows['f107']=100;rows['f107a']=110;rows['ap']=4
        np.save(command[6],rows,allow_pickle=False)
        return CompletedProcess(command,0,'test-version','')
    monkeypatch.setattr(f.subprocess,'run',wrong_output)
    with pytest.raises(ValueError,match='requested UTC interval'):
        f.download_atmosphere_inputs('2024-09-10','2024-09-11',tmp_path)
    assert not list(tmp_path.iterdir())
