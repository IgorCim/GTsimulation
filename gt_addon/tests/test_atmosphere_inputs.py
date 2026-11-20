"""Atmospheric input contract and real NRLMSIS integration, no network."""
from datetime import datetime, timedelta
import csv
import io
import json
import numpy as np
import pytest
import fetcher as a

HEADER = 'DATE,BSRN,ND,KP1,KP2,KP3,KP4,KP5,KP6,KP7,KP8,KP_SUM,AP1,AP2,AP3,AP4,AP5,AP6,AP7,AP8,AP_AVG,CP,C9,ISN,F10.7_OBS,F10.7_ADJ,F10.7_DATA_TYPE,F10.7_OBS_CENTER81,F10.7_OBS_LAST81,F10.7_ADJ_CENTER81,F10.7_ADJ_LAST81'.split(',')


def source(change=None):
    out=io.StringIO()
    w=csv.DictWriter(out,fieldnames=HEADER); w.writeheader()
    for i in range(5):
        r=dict.fromkeys(HEADER,'0')
        r.update(DATE=str((datetime(2024,9,7)+timedelta(days=i)).date()))
        r.update({'F10.7_OBS':str(100+i), 'F10.7_OBS_CENTER81':'110','F10.7_DATA_TYPE':'OBS','AP_AVG':str(i+1)})
        for k in range(1,9): r[f'AP{k}']=str(i*8+k)
        if change: change(r,i)
        if r: w.writerow(r)
    return out.getvalue().encode()


@pytest.fixture
def bundle(tmp_path,monkeypatch):
    monkeypatch.setattr(a,'_download',lambda *args,**kwargs:source())
    return a.download_atmosphere_inputs('2024-09-10','2024-09-11',tmp_path)


def test_history_and_provenance(bundle):
    rows=a.load_atmosphere_inputs(bundle['input_file'])
    assert len(rows)==24
    assert rows['f107'][0]==102 # Previous day, not requested day.
    np.testing.assert_array_equal(rows['ap'][0],[4,25,24,23,22,17.5,9.5])
    assert rows['ap'][2,1]==25 and rows['ap'][3,1]==26
    manifest=json.loads(a.Path(bundle['manifest']).read_text())
    assert manifest['source_sha256']==a.hashlib.sha256(source()).hexdigest()
    assert manifest['pymsis_version']




@pytest.mark.parametrize('change',[
 lambda r,i:r.update({'F10.7_DATA_TYPE':'PRD'}) if i==2 else None,
 lambda r,i:r.update({'AP1':'-1'}) if i==0 else None,
 lambda r,i:r.update({'F10.7_OBS':'999'}) if i==2 else None,
 lambda r,i:r.update({'F10.7_OBS_CENTER81':'nan'}) if i==3 else None,
 lambda r,i:r.clear() if i==1 else None,
])
def test_bad_history_fails_without_bundle(tmp_path,monkeypatch,change):
    monkeypatch.setattr(a,'_download',lambda *args,**kwargs:source(change))
    with pytest.raises(ValueError): a.download_atmosphere_inputs('2024-09-10','2024-09-11',tmp_path)
    assert not list(tmp_path.iterdir())


def test_worker_failure_cleans_staging(tmp_path,monkeypatch):
    monkeypatch.setattr(a,'_download',lambda *args,**kwargs:source())
    def fail(*args,**kwargs): raise a.subprocess.TimeoutExpired('worker',120)
    monkeypatch.setattr(a.subprocess,'run',fail)
    with pytest.raises(a.subprocess.TimeoutExpired): a.download_atmosphere_inputs('2024-09-10','2024-09-11',tmp_path)
    assert not list(tmp_path.iterdir())




@pytest.mark.parametrize('mutation',[
 lambda r:r['date'].__setitem__(1,r['date'][0]),
 lambda r:r['ap'].__setitem__((0,0),np.nan),
 lambda r:r['f107'].__setitem__(0,0),
])
def test_corrupt_array(bundle,tmp_path,mutation):
    rows=a.load_atmosphere_inputs(bundle['input_file']);mutation(rows)
    path=tmp_path/'bad.npy';np.save(path,rows)
    with pytest.raises(ValueError): a.load_atmosphere_inputs(path)




def test_reordered_csv_rejected(tmp_path,monkeypatch):
    lines=source().decode().splitlines()
    fields=lines[0].split(',');fields[24],fields[25]=fields[25],fields[24]
    body=('\n'.join([','.join(fields)]+lines[1:])+'\n').encode()
    monkeypatch.setattr(a,'_download',lambda *args,**kwargs:body)
    with pytest.raises(ValueError,match='column order'):
        a.download_atmosphere_inputs('2024-09-10','2024-09-11',tmp_path)


def test_preparation_does_not_change_parent_source(tmp_path,monkeypatch):
    import pymsis.utils as u
    before_path,before_data=u._SPACE_WEATHER.path,u._SPACE_WEATHER.data
    r=prepare_atmosphere(tmp_path,monkeypatch)
    assert a.Path(r['space_weather_file']).is_file()
    assert u._SPACE_WEATHER.path==before_path and u._SPACE_WEATHER.data is before_data


def prepare_atmosphere(tmp_path,monkeypatch):
    monkeypatch.setattr(a,'_download',lambda *args,**kwargs:source())
    return a.download_atmosphere_inputs('2024-09-10','2024-09-11',tmp_path)
