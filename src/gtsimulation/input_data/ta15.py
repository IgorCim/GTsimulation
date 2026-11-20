"""Official TA15 B-index inputs; GT's existing coordinate convention is preserved."""
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import shutil
import tempfile
import numpy as np
from .omni import _download

BASE_URL = "https://geo.phys.spbu.ru/~tsyganenko/models/ta15"
DTYPE = np.dtype([("date","datetime64[s]"),("T15B_input","f8",(4,)),
                  ("imf_flag","i1"),("sw_flag","i1")])
COMPATIBILITY = ("Source IMF is GSW (30-minute trailing averages). GT's existing T15B wrapper "
                 "uses GSM positions/tilt and the same source drivers; this addon preserves "
                 "that convention, not a full GSW coordinate implementation.")


def _boundary(value):
    if isinstance(value,str): value=datetime.fromisoformat(value.replace('Z','+00:00'))
    if not isinstance(value,datetime): raise ValueError('Expected ISO time or datetime.')
    if value.tzinfo is not None: value=value.astimezone(timezone.utc).replace(tzinfo=None)
    if value.minute%5 or value.second or value.microsecond:
        raise ValueError('TA15 boundaries must be whole five-minute UTC slots.')
    return value


def _parse(body,year):
    records={}
    for number,line in enumerate(body.decode('ascii').splitlines(),1):
        if not line.strip(): continue
        fields=line.split()
        if len(fields)!=19: raise ValueError(f'Invalid TA15 record at line {number}.')
        y,d,h,m=map(int,fields[:4])
        stamp=datetime(y,1,1)+timedelta(days=d-1,hours=h,minutes=m)
        if y!=year or d<1 or stamp.year!=y or not 0<=h<24 or not 0<=m<60 or m%5:
            raise ValueError('Invalid TA15 timestamp.')
        if stamp in records: raise ValueError('Duplicate TA15 timestamp.')
        values=[float(fields[i]) for i in (16,5,6,18)]
        flags=[int(fields[i]) for i in (13,14)]
        records[stamp]=(values,flags)
    if not records: raise ValueError('Empty TA15 response.')
    return records


def load_ta15_inputs(path):
    rows=np.load(path,allow_pickle=False)
    if not isinstance(rows,np.ndarray):
        rows.close(); raise ValueError('Expected NPY array.')
    if rows.ndim!=1 or not len(rows) or rows.dtype!=DTYPE:
        raise ValueError('Invalid TA15 input schema.')
    dates=rows['date'];v=rows['T15B_input']
    if np.any(np.isnat(dates)) or np.any(dates.astype('int64')%300) or np.any(np.diff(dates)!=np.timedelta64(5,'m')):
        raise ValueError('TA15 slots must be sorted, unique and continuous.')
    if not np.all(np.isfinite(v)) or np.any(v[:,0]<=0) or np.any(v[:,0]>=99.99) or np.any(abs(v[:,1:3])>=999.9) or np.any(v[:,3]<0) or np.any(v[:,3]>2):
        raise ValueError('Missing TA15 drivers or B-index outside GT range 0..2.')
    if any(not np.all(np.isin(rows[k],[1,2])) for k in ('imf_flag','sw_flag')):
        raise ValueError('Invalid TA15 quality flags.')
    return rows


def download_ta15_inputs(start,end,output_dir,*,allow_interpolated=False,timeout=30,attempts=3):
    """Download [start,end), require all five-minute slots and GT B-index <=2."""
    start,end=_boundary(start),_boundary(end)
    if start>=end or start.year<1995 or end-start>timedelta(days=366):
        raise ValueError('Require 1995 or later, start < end, at most 366 days.')
    if type(allow_interpolated) is not bool: raise ValueError('allow_interpolated must be boolean.')
    if type(attempts) is not int or not 1<=attempts<=5: raise ValueError('attempts must be 1..5.')
    if not np.isfinite(timeout) or timeout<=0: raise ValueError('timeout must be positive and finite.')
    records={};raw={};sources=[]
    for year in range(start.year,(end-timedelta(seconds=1)).year+1):
        name=f'{year}_OMNI_5m_with_TA15_drivers.dat';url=f'{BASE_URL}/{name}'
        body=_download(url,timeout,attempts,max_bytes=32*1024*1024)
        records.update(_parse(body,year));raw[name]=body
        sources.append({'url':url,'sha256':hashlib.sha256(body).hexdigest()})
    rows=np.empty(int((end-start).total_seconds()//300),dtype=DTYPE)
    for i in range(len(rows)):
        stamp=start+timedelta(minutes=5*i)
        if stamp not in records: raise ValueError(f'Missing TA15 slot: {stamp.isoformat()}Z.')
        values,flags=records[stamp]
        if not allow_interpolated and flags!=[1,1]:
            raise ValueError(f'Interpolated or invalid TA15 inputs at {stamp.isoformat()}Z.')
        rows[i]=(stamp,values,*flags)
    parent=Path(output_dir).expanduser().resolve();parent.mkdir(parents=True,exist_ok=True)
    staging=Path(tempfile.mkdtemp(prefix='.ta15-',dir=parent))
    try:
        np.save(staging/'inputs.npy',rows,allow_pickle=False)
        load_ta15_inputs(staging/'inputs.npy')
        for name,body in raw.items(): (staging/name).write_bytes(body)
        manifest={'schema':'gt-ta15-inputs-v1','model':'15B','rows':len(rows),
                  'start':start.isoformat()+'Z','end_exclusive':end.isoformat()+'Z',
                  'time_system':'UTC','sampling':'5 minutes; containing slot; no interpolation by addon',
                  'units':['nPa','nT','nT','dimensionless'],'parameter_order':['Pdyn','By_GSW','Bz_GSW','B_index'],
                  'allow_provider_interpolation':allow_interpolated,
                  'provider_interpolated_rows':int(np.sum((rows['imf_flag']==2)|(rows['sw_flag']==2))),
                  'compatibility_note':COMPATIBILITY,'sources':sources,
                  'retrieved_at':datetime.now(timezone.utc).isoformat(),
                  'input_sha256':hashlib.sha256((staging/'inputs.npy').read_bytes()).hexdigest()}
        (staging/'manifest.json').write_text(json.dumps(manifest,indent=2),encoding='utf-8')
        bundle=parent/('ta15-'+staging.name.removeprefix('.ta15-'));staging.rename(bundle)
    except BaseException:
        if staging.resolve().parent!=parent: raise RuntimeError('Unexpected staging directory.')
        shutil.rmtree(staging);raise
    return {'input_file':str(bundle/'inputs.npy'),'manifest':str(bundle/'manifest.json'),
            'rows':len(rows),'model':'15B','compatibility_note':COMPATIBILITY}
