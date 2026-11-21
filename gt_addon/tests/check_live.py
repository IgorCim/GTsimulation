"""Live downloads and independent source-to-input verification, without GT."""
from pathlib import Path
import argparse
import csv
from datetime import datetime,timedelta,timezone
import hashlib
import json
import sys
import tempfile
from urllib.parse import urlsplit
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import fetcher

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
        path=root/m.get('source_file','SW-All.csv');digest(path,m['source_sha256'])
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


def replay_files(directory, models):
    """Locate only requested sources; preserve the actual CelesTrak dataset URL."""
    names=[]
    if any(m in ('89','96') for m in models):names.append('omni2_2024.dat')
    if '15B' in models:names.append('2023_OMNI_5m_with_TA15_drivers.dat')
    if 'nrlmsis' in models:
        recent=list(directory.rglob('SW-Last5Years.csv'))
        names.append('SW-Last5Years.csv' if any((p.parent/'manifest.json').is_file() for p in recent) else 'SW-All.csv')
    captured={}
    for name in names:
        paths=sorted(p for p in directory.rglob(name) if (p.parent/'manifest.json').is_file())
        if not paths:raise ValueError('No manifested source found: '+name)
        path=paths[0];manifest=json.loads((path.parent/'manifest.json').read_text(encoding='utf-8'))
        if name.startswith('SW-'):
            url=fetcher.MSIS_RECENT_URL if name=='SW-Last5Years.csv' else fetcher.MSIS_URL
            if manifest.get('source')!=url:raise ValueError('Replay source URL mismatch.')
            expected=manifest['source_sha256']
        else:
            source=next(x for x in manifest['sources'] if Path(urlsplit(x['url']).path).name==name)
            url=(fetcher.OMNI_BASE_URL if name.startswith('omni2_') else fetcher.TA15_BASE_URL)+'/'+name
            if source['url']!=url:raise ValueError('Replay source URL mismatch.')
            expected=source['sha256']
        digest(path,expected)
        captured[name]={'path':str(path.resolve()),'sha256':expected,'url':url,'recorded_retrieved_at':manifest.get('source_retrieved_at',manifest.get('retrieved_at'))}
    return captured


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--replay-dir',type=Path,help='Explicit offline replay from saved raw responses with original manifests')
    parser.add_argument('--models',nargs='+',choices=['89','96','15B','nrlmsis'],default=['89','96','15B','nrlmsis'])
    args=parser.parse_args()
    replay_sources={}
    if args.replay_dir:
        try:replay_sources=replay_files(args.replay_dir,args.models)
        except ValueError as exc:parser.error(str(exc))
        import io
        allowed={v['url']:k for k,v in replay_sources.items()}
        def opening(url,**kwargs):
            if getattr(url,'full_url',url) not in allowed:raise RuntimeError('Unexpected replay URL: '+str(url))
            actual_url=getattr(url,'full_url',url)
            body=Path(replay_sources[allowed[actual_url]]['path']).read_bytes()
            class Response(io.BytesIO):
                status=200
                headers={'Content-Length':str(len(body))}
            return Response(body)
        fetcher.urlopen=opening
    root=Path(__file__).resolve().parents[1]
    (root/'results').mkdir(exist_ok=True)
    folder=Path(tempfile.mkdtemp(prefix='replay-' if args.replay_dir else 'live-',dir=root/'results'))
    result={'status':'RUNNING','models':{},'scope':'Download/prepare/integrity/independent arithmetic only; no GT import or simulation.',
            'mode':'offline captured-response replay' if args.replay_dir else 'network (CelesTrak explicit cache allowed)', 'replay_sources':replay_sources}
    print('MODE: '+result['mode'],flush=True)
    for model in dict.fromkeys(args.models):
        print('Download and independent check: '+model,flush=True)
        try:
            if model in ('89','96'):
                b=fetcher.download_tsyganenko_inputs('2024-09-10','2024-09-11',folder,model=model)
            elif model=='15B':
                b=fetcher.download_ta15_inputs('2023-01-01T00:30','2023-01-01T01:30',folder,allow_interpolated=True)
            else:
                b=fetcher.download_atmosphere_inputs('2024-09-10','2024-09-11',folder,dataset=('recent' if 'SW-Last5Years.csv' in replay_sources else 'all') if args.replay_dir else 'auto',cache_dir=None if args.replay_dir else root/'inputs/.celestrak-cache')
            checked=compare(model,b)
            checked['bundle']=b
            if model=='nrlmsis':
                meta=json.loads(Path(b['manifest']).read_text(encoding='utf-8'))
                checked.update(source_mode=meta.get('source_mode','network'),source_retrieved_at=meta.get('source_retrieved_at'),source_url=meta['source'])
                if args.replay_dir:
                    captured=replay_sources[meta['source_file']]
                    checked.update(source_mode='offline_replay',source_retrieved_at=captured['recorded_retrieved_at'])
                print('SOURCE nrlmsis: '+checked['source_mode']+'; retrieved '+str(checked['source_retrieved_at']),flush=True)
            result['models'][model]=checked
        except Exception as exc:
            result['models'][model]={'status':'FAIL','error_type':type(exc).__name__,'error':str(exc)}
            print('FAIL '+model+': '+str(exc),flush=True)
    if not args.replay_dir:
        result['mode']='network with explicit source cache' if any(v.get('source_mode')=='validated_cache' for v in result['models'].values()) else 'live network'
    result['status']='PASS' if all(r['status']=='PASS' for r in result['models'].values()) else 'FAIL'
    if any(k=='gtsimulation' or k.startswith('gtsimulation.') for k in sys.modules):
        result['status']='FAIL';result['unexpected_gt_import']=True
    report=folder/'report.json';report.write_text(json.dumps(result,indent=2),encoding='utf-8')
    print('Evidence: '+str(report),flush=True)
    print(result['status']+': '+result['mode']+'; independent check for '+','.join(result['models'])+'.',flush=True)
    return 0 if result['status']=='PASS' else 1


if __name__=='__main__':raise SystemExit(main())
