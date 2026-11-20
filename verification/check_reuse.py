"""Live T89/T96, bundle integrity, and fresh-process offline reuse of four models."""
from pathlib import Path
from datetime import datetime, timezone
from urllib.parse import urlsplit
import argparse
import hashlib
import json
import subprocess
import sys
import tempfile
from unittest.mock import patch


def verify_bundle(bundle):
    root=Path(bundle['input_file']).resolve().parent
    manifest=json.loads((root/'manifest.json').read_text(encoding='utf-8'))
    checks={'inputs.npy':manifest['input_sha256']}
    sources=manifest.get('sources', [{'url':manifest.get('source'), 'sha256':manifest.get('source_sha256')}])
    for source in sources:
        name=Path(urlsplit(source['url']).path).name
        if name != Path(name).name or not name:
            raise ValueError('Invalid source filename.')
        checks[name]=source['sha256']
    for name,expected in checks.items():
        actual=hashlib.sha256((root/name).read_bytes()).hexdigest()
        if actual!=expected:
            raise ValueError(f'Integrity mismatch: {root/name}')
    return checks


def evaluate(bundles, block_network):
    attempts=[]
    if block_network:
        import socket
        def deny(event,args):
            if event in ('socket.connect','socket.getaddrinfo','socket.gethostbyname','socket.sendto'):
                attempts.append(event)
                raise RuntimeError('Network disabled for offline verification: '+event)
        sys.addaudithook(deny)
    import warnings
    import numpy as np
    from gtsimulation.magnetic_field.magnetosphere import Tsyganenko
    from gtsimulation.medium.magnetosphere import GTnrlmsis
    from gtsimulation.input_data.ta15 import COMPATIBILITY
    values={}
    for model in ('89','96','15B'):
        bundle=bundles[model]
        manifest=json.loads(Path(bundle['manifest']).read_text(encoding='utf-8'))
        date=datetime.fromisoformat(manifest['start'].replace('Z','+00:00')).replace(tzinfo=None)
        with warnings.catch_warnings(record=True) as notices:
            warnings.simplefilter('always')
            field=Tsyganenko(date,model,input_file=bundle['input_file'])
        if model=='15B' and not any(str(w.message)==COMPATIBILITY for w in notices):
            raise ValueError('Missing TA15 compatibility warning.')
        result=np.asarray(field.calc_field(2,1,1),dtype=float)
        if not np.all(np.isfinite(result)): raise ValueError('Nonfinite magnetic field.')
        values[model]=result.tolist()
    bundle=bundles['nrlmsis']
    manifest=json.loads(Path(bundle['manifest']).read_text(encoding='utf-8'))
    date=datetime.fromisoformat(manifest['start'].replace('Z','+00:00')).replace(tzinfo=None)
    medium=GTnrlmsis(date,input_file=bundle['input_file'])
    medium.calculate_model(6478137,0,0)
    density=float(medium.get_density())
    if not np.isfinite(density) or density<=0: raise ValueError('Invalid density.')
    values['nrlmsis']=[density]
    if attempts: raise ValueError('Offline evaluation attempted network access: '+str(attempts))
    return {'values':values,'network_blocked':block_network,'network_attempts':attempts}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--worker',type=Path)
    parser.add_argument('--offline',action='store_true')
    args=parser.parse_args()
    if args.worker:
        bundles=json.loads(args.worker.read_text(encoding='utf-8'))
        print(json.dumps(evaluate(bundles,args.offline)))
        return
    root=Path(__file__).resolve().parent
    folder=Path(tempfile.mkdtemp(prefix='reuse-',dir=root))
    report={'status':'RUNNING','started_at':datetime.now(timezone.utc).isoformat(),
            'scope':'Live T89/T96; source/input SHA256; fresh-process reuse with Python socket network blocked. Not scientific model validation.'}
    try:
        from gtsimulation.input_data import download_tsyganenko_inputs
        previous=json.loads((root/'expanded_live_result.json').read_text(encoding='utf-8'))
        bundles={'15B':previous['ta15'],'nrlmsis':previous['atmosphere']}
        import gtsimulation.input_data.omni as omni
        original_download=omni._download
        def record_response(url, *args, **kwargs):
            body=original_download(url,*args,**kwargs)
            name=Path(urlsplit(url).path).name
            path=folder/('response-'+str(len(list(folder.glob('response-*'))))+'-'+name)
            path.write_bytes(body)
            return body
        for model in ('89','96'):
            print(f'Downloading NASA OMNI for T{model}...',flush=True)
            with patch.object(omni,'_download',record_response):
                bundles[model]=download_tsyganenko_inputs('2024-09-10','2024-09-11',folder,model=model)
            if bundles[model]['rows']!=24: raise ValueError('Expected 24 OMNI hours.')
        report['bundles']=bundles
        report['sha256_checks']={model:verify_bundle(bundle) for model,bundle in bundles.items()}
        payload=folder/'bundles.json';payload.write_text(json.dumps(bundles,indent=2),encoding='utf-8')
        results=[]
        for offline in (False,True):
            print('Fresh process: '+('network blocked' if offline else 'baseline evaluation'),flush=True)
            cmd=[sys.executable,str(Path(__file__).resolve()),'--worker',str(payload)]
            if offline: cmd.append('--offline')
            proc=subprocess.run(cmd,capture_output=True,text=True,timeout=600)
            if proc.returncode: raise RuntimeError(proc.stderr[-4000:] or proc.stdout[-4000:])
            results.append(json.loads(proc.stdout))
        import numpy as np
        for model in bundles:
            np.testing.assert_allclose(results[0]['values'][model],results[1]['values'][model],rtol=1e-10,atol=1e-12)
        report.update(status='PASS',baseline=results[0],offline=results[1],comparison={'rtol':1e-10,'atol':1e-12})
    except BaseException as exc:
        report.update(status='FAIL',error_type=type(exc).__name__,error=str(exc))
        raise
    finally:
        report['finished_at']=datetime.now(timezone.utc).isoformat()
        path=folder/'report.json';path.write_text(json.dumps(report,indent=2),encoding='utf-8')
        print('Evidence: '+str(path),flush=True)
    print('PASS: live T89/T96, bundle SHA256, offline reuse of 89/96/15B/NRLMSIS.',flush=True)


if __name__=='__main__':
    main()
