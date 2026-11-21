"""Compare direct urllib and public addon NASA downloads in fresh processes."""
from pathlib import Path
import argparse
from datetime import datetime, timezone
import hashlib
import html
import json
import os
import subprocess
import sys
import tempfile
import time
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[1]
URL = 'https://spdf.gsfc.nasa.gov/pub/data/omni/low_res_omni/omni2_2024.dat'


def worker(method, directory, timeout):
    sys.path.insert(0, str(ROOT))
    import fetcher
    result = {'method': method, 'url': URL, 'started_UTC': datetime.now(timezone.utc).isoformat(),
              'python': sys.executable, 'socket_timeout': timeout, 'attempts': 1,
              'fetcher_sha256': hashlib.sha256(Path(fetcher.__file__).read_bytes()).hexdigest()}
    begun = time.monotonic()
    def opening(url, **kwargs):
        response = urlopen(url, **kwargs)
        result['http_status'] = response.status
        result['final_url'] = response.geturl()
        result['headers'] = {key: response.headers.get(key) for key in
                             ('Content-Length', 'Content-Type', 'ETag', 'Last-Modified')}
        (directory/'response.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
        return response
    try:
        if method == 'direct':
            with opening(URL, timeout=timeout) as response:
                body = response.read(fetcher.OMNI_MAX_BYTES + 1)
            if len(body) > fetcher.OMNI_MAX_BYTES:
                raise ValueError('Response exceeds addon size limit.')
            path = directory/'omni2_2024.dat'
            path.write_bytes(body)
        else:
            # Observe headers only; the addon still performs its original network read.
            fetcher.urlopen = opening
            bundle = fetcher.download_tsyganenko_inputs('2024-09-10', '2024-09-11',
                directory, model='96', timeout=timeout, attempts=1)
            path = Path(bundle['manifest']).parent/'omni2_2024.dat'
            import runpy
            checker = runpy.run_path(str(ROOT/'tests/check_live.py'))
            # check_live imports this same fetcher module; no further network call here.
            result['independent_input_check'] = checker['compare']('96', bundle)
        body = path.read_bytes()
        declared = result['headers'].get('Content-Length')
        if declared is not None and len(body) != int(declared):
            raise ValueError('Content-Length mismatch.')
        result.update(status='PASS', bytes=len(body), sha256=hashlib.sha256(body).hexdigest(), file=str(path))
    except Exception as exc:
        result.update(status='FAIL', error_type=type(exc).__name__, error=str(exc))
    result['seconds'] = round(time.monotonic()-begun, 3)
    (directory/'result.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
    print(json.dumps(result, ensure_ascii=False), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--worker', choices=['direct','addon'])
    parser.add_argument('--directory', type=Path)
    parser.add_argument('--socket-timeout', type=float, default=20)
    parser.add_argument('--deadline', type=float, default=75)
    args = parser.parse_args()
    if args.worker:
        worker(args.worker, args.directory, args.socket_timeout)
        return
    results = ROOT/'results'
    results.mkdir(exist_ok=True)
    folder = Path(tempfile.mkdtemp(prefix='nasa-comparison-', dir=results))
    report = {'url': URL, 'created_UTC': datetime.now(timezone.utc).isoformat(),
              'note': 'Same interpreter, inherited environment, default TLS validation, URL, timeout and one attempt. Fresh process for each run. Sequential AB/BA reduces order bias; it cannot prove server ownership of a network failure.',
              'proxy_environment_present': any(os.environ.get(k) for k in
                  ('HTTPS_PROXY','https_proxy','HTTP_PROXY','http_proxy','ALL_PROXY','all_proxy')),
              'trials': []}
    print('REPORT: '+str(folder/'report.html'), flush=True)
    for index, method in enumerate(('direct','addon','addon','direct'), 1):
        directory = folder/f'{index:02d}-{method}'
        directory.mkdir()
        print(f'[{index}/4] {method}: start; deadline {args.deadline:g}s', flush=True)
        start = time.monotonic()
        with (directory/'worker.log').open('w', encoding='utf-8') as log:
            process = subprocess.Popen([sys.executable, str(Path(__file__).resolve()), '--worker', method,
                '--directory', str(directory), '--socket-timeout', str(args.socket_timeout)],
                stdout=log, stderr=subprocess.STDOUT)
            while process.poll() is None:
                elapsed = time.monotonic()-start
                if elapsed >= args.deadline:
                    process.kill()
                    process.wait()
                    break
                print(f'  {method}: {elapsed:.0f}/{args.deadline:g}s', flush=True)
                try:
                    process.wait(timeout=min(5, args.deadline-elapsed))
                except subprocess.TimeoutExpired:
                    pass
        path = directory/'result.json'
        if path.is_file():
            trial = json.loads(path.read_text(encoding='utf-8'))
        else:
            trial = {'method':method, 'status':'TIMEOUT' if time.monotonic()-start>=args.deadline else 'WORKER_ERROR',
                     'seconds':round(time.monotonic()-start,3)}
            if (directory/'response.json').is_file():
                trial['response_before_failure']=json.loads((directory/'response.json').read_text(encoding='utf-8'))
        trial['log'] = str(directory/'worker.log')
        report['trials'].append(trial)
        print(f"[{index}/4] {method}: {trial['status']}; {trial.get('error','')}", flush=True)
        successful = [x for x in report['trials'] if x['status']=='PASS']
        report['successful_file_hashes_identical'] = len({x['sha256'] for x in successful})==1 if successful else None
        (folder/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
        rows=''.join('<tr>'+''.join('<td>'+html.escape(str(x.get(k,'')))+'</td>' for k in
            ('method','status','seconds','bytes','sha256','error'))+'</tr>' for x in report['trials'])
        (folder/'report.html').write_text('<!doctype html><meta charset="utf-8"><title>NASA comparison</title>'
            '<h1>NASA: прямое скачивание и аддон</h1><p>'+html.escape(URL)+'</p>'
            '<table border="1"><tr><th>Метод</th><th>Итог</th><th>Секунды</th><th>Байты</th><th>SHA256</th><th>Ошибка</th></tr>'+rows+
            '</table><p>Порядок: прямое → аддон → аддон → прямое. TLS-проверка включена. Кэш не используется.</p>',encoding='utf-8')
    print('Evidence: '+str(folder/'report.json'),flush=True)

if __name__=='__main__':
    main()
