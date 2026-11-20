"""Independent numeric audit of saved inputs; imports neither GT nor pymsis."""
import argparse
import csv
from datetime import datetime,timedelta,timezone
import hashlib
import json
from pathlib import Path
import tempfile
from urllib.parse import urlsplit
import numpy as np


def utc(text):
    return datetime.fromisoformat(text.replace('Z','+00:00')).astimezone(timezone.utc).replace(tzinfo=None)


def digest(path,expected):
    if hashlib.sha256(path.read_bytes()).hexdigest()!=expected:
        raise ValueError('SHA256 mismatch: '+str(path))


def kp_bin(code):
    # Explicit activity groups from the seven T89 input categories.
    groups=[(0,3),(7,10,13),(17,20,23),(27,30,33),(37,40,43),(47,50,53),
            (57,60,63,67,70,73,77,80,83,87,90)]
    for category,codes in enumerate(groups,1):
        if code in codes:return category
    raise ValueError('Invalid Kp*10: '+str(code))


def read_annual(root,sources,ta15=False):
    records={}
    for source in sources:
        path=root/Path(urlsplit(source['url']).path).name
        digest(path,source['sha256'])
        for line in path.read_text(encoding='ascii').splitlines():
            if not line.strip():continue
            fields=line.split()
            y,d,h=map(int,fields[:3]);minute=int(fields[3]) if ta15 else 0
            stamp=datetime(y,1,1)+timedelta(days=d-1,hours=h,minutes=minute)
            if stamp in records:raise ValueError('Duplicate source time.')
            records[stamp]=fields
    return records


def ap_slot(records,time):
    row=records[time.date()]
    return float(row['AP'+str(time.hour//3+1)])


def atmosphere_expected(records,time):
    row=records[time.date()]
    previous=records[(time-timedelta(days=1)).date()]
    slot=time.replace(hour=3*(time.hour//3),minute=0,second=0)
    history=[ap_slot(records,slot-timedelta(hours=3*k)) for k in range(20)]
    # Arithmetic means of eight explicitly selected historical slots, no convolution.
    return [float(previous['F10.7_OBS']),float(row['F10.7_OBS_CENTER81']),
            float(row['AP_AVG']),*history[:4],sum(history[4:12])/8,sum(history[12:20])/8]


def compare(model,bundle):
    root=Path(bundle['input_file']).resolve().parent
    m=json.loads((root/'manifest.json').read_text(encoding='utf-8'))
    digest(root/'inputs.npy',m['input_sha256'])
    data=np.load(root/'inputs.npy',allow_pickle=False)
    start,end=utc(m['start']),utc(m['end_exclusive'])
    minutes=5 if model=='15B' else 60
    times=[];cursor=start
    while cursor<end:
        times.append(cursor);cursor+=timedelta(minutes=minutes)
    np.testing.assert_array_equal(data['date'],np.array(times,dtype='datetime64[s]'))
    if len(data)!=m['rows']:raise ValueError('Manifest row count mismatch.')
    if model=='nrlmsis':
        path=root/'SW-All.csv';digest(path,m['source_sha256'])
        with path.open(encoding='utf-8-sig',newline='') as f:
            records={datetime.fromisoformat(row['DATE']).date():row for row in csv.DictReader(f)}
        first=(start-timedelta(days=3)).date();last=(end-timedelta(seconds=1)).date()
        day=first
        while day<=last:
            if records[day]['F10.7_DATA_TYPE']!='OBS':raise ValueError('Non-observed source row.')
            day+=timedelta(days=1)
        expected=np.array([atmosphere_expected(records,t) for t in times])
        actual=np.column_stack([data['f107'],data['f107a'],data['ap']])
        labels=['previous_day_F107_sfu','center81_F107_sfu','daily_Ap','ap_now','ap_minus3h','ap_minus6h','ap_minus9h','ap_mean12_33h','ap_mean36_57h']
    else:
        records=read_annual(root,m['sources'],model=='15B')
        if model=='89':
            expected=np.array([[kp_bin(int(records[t][38]))] for t in times])
            actual=data['T89_input'][:,None];labels=['T89_activity_bin']
        elif model=='96':
            expected=np.array([[float(records[t][i]) for i in (28,40,15,16)] for t in times])
            actual=data['T96_input'];labels=['Pdyn_nPa','Dst_nT','By_GSM_nT','Bz_GSM_nT']
        else:
            expected=np.array([[float(records[t][i]) for i in (16,5,6,18)] for t in times])
            actual=data['T15B_input'];labels=['Pdyn_nPa','By_GSW_nT','Bz_GSW_nT','B_index']
            for field,index in [('imf_flag',13),('sw_flag',14)]:
                np.testing.assert_array_equal(data[field],[int(records[t][index]) for t in times])
    if not np.all(np.isfinite(expected)):raise ValueError('Nonfinite expected values.')
    np.testing.assert_allclose(actual,expected,rtol=0,atol=1e-12,err_msg=model)
    return {'status':'PASS','rows':len(data),'values_compared':int(expected.size),
            'start':m['start'],'end_exclusive':m['end_exclusive'],
            'max_absolute_error_by_component':dict(zip(labels,np.max(abs(actual-expected),axis=0).tolist())),
            'first_expected':dict(zip(labels,expected[0].tolist())),
            'source_and_input_sha256_verified':True}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--bundles',type=Path,help='Path to a successful reuse run bundles.json; defaults to latest successful run')
    args=parser.parse_args()
    root=Path(__file__).resolve().parent
    if args.bundles is None:
        candidates=[]
        for report in root.glob('reuse-*/report.json'):
            m=json.loads(report.read_text(encoding='utf-8'))
            if m.get('status')=='PASS':candidates.append(report)
        if not candidates:parser.error('Run check_reuse.py successfully first.')
        args.bundles=max(candidates,key=lambda p:p.stat().st_mtime).parent/'bundles.json'
    bundles=json.loads(args.bundles.read_text(encoding='utf-8'))
    folder=Path(tempfile.mkdtemp(prefix='independent-',dir=root))
    result={'status':'RUNNING','bundles_file':str(args.bundles.resolve()),'models':{},
            'method':'Independent stdlib/numpy source reader; no GT or pymsis import; all saved interval rows.',
            'limitations':'Validates input preparation, not GT field physics, GSW/GSM approximation, Kp generation, or provider 81-day-average computation.'}
    try:
        for model in ('89','96','15B','nrlmsis'):
            print('Independent audit: '+model,flush=True)
            result['models'][model]=compare(model,bundles[model])
        result['status']='PASS'
    except BaseException as exc:
        result.update(status='FAIL',error_type=type(exc).__name__,error=str(exc));raise
    finally:
        report=folder/'report.json';report.write_text(json.dumps(result,indent=2),encoding='utf-8')
        print('Evidence: '+str(report),flush=True)
    print('PASS: independent input audit for 89/96/15B/NRLMSIS.',flush=True)


if __name__=='__main__':main()
