"""CelesTrak transport, dataset choice and transparent cache; no external requests."""
from datetime import datetime,timedelta,timezone
from pathlib import Path
from urllib.error import HTTPError
import io
import json
import re
import runpy
import pytest
import fetcher as f


class Response(io.BytesIO):
 def __init__(self,body,status=206,headers=None):
  super().__init__(body);self.status=status;self.headers=headers or {}


def responder(body,change=None):
 calls=[]
 def opening(req,**kwargs):
  first,last=map(int,re.fullmatch(r'bytes=(\d+)-(\d+)',req.get_header('Range')).groups())
  last=min(last,len(body)-1)
  headers={'Content-Range':f'bytes {first}-{last}/{len(body)}','ETag':'"one"','Content-Length':str(last-first+1)}
  calls.append(req)
  part=body[first:last+1]
  if change:return change(req,headers,part,len(calls))
  return Response(part,headers=headers)
 return opening,calls


def test_stable_ranges_and_if_range(monkeypatch):
 body=bytes(range(256))*600
 opening,calls=responder(body);monkeypatch.setattr(f,'urlopen',opening)
 assert f._download('https://example.org/file',1,2,max_bytes=200000,range_requests=True)==body
 assert len(calls)==3 and calls[0].get_header('If-range') is None
 assert all(c.get_header('If-range')=='"one"' for c in calls[1:])


@pytest.mark.parametrize('problem',['etag','total','offset','end','weak','missing_tag','length','short','status200','encoding'])
def test_reject_inconsistent_range(monkeypatch,problem):
 body=b'x'*70000
 def change(req,h,part,n):
  if n==2:
   if problem=='etag':h['ETag']='"two"'
   if problem=='total':h['Content-Range']='bytes 65536-69999/71000'
   if problem=='offset':h['Content-Range']='bytes 65535-69999/70000'
   if problem=='end':h['Content-Range']='bytes 65536-69998/70000'
   if problem=='weak':h['ETag']='W/"one"'
   if problem=='missing_tag':h.pop('ETag')
   if problem=='length':h['Content-Length']='1'
   if problem=='short':part=part[:-1]
   if problem=='encoding':h['Content-Encoding']='gzip'
   if problem=='status200':return Response(body,200,{'Content-Length':str(len(body))})
  return Response(part,headers=h)
 opening,calls=responder(body,change);monkeypatch.setattr(f,'urlopen',opening)
 with pytest.raises(ValueError):f._download('https://example.org/file',1,1,range_requests=True)
 assert len(calls)==2


def test_size_limit_before_accepting_chunk(monkeypatch):
 opening,calls=responder(b'x'*100)
 monkeypatch.setattr(f,'urlopen',opening)
 with pytest.raises(ValueError,match='size limit'):f._download('https://example.org/file',1,1,max_bytes=99,range_requests=True)


def test_server_ignores_first_range_but_complete_file_is_valid(monkeypatch):
 monkeypatch.setattr(f,'urlopen',lambda *a,**k:Response(b'complete',200,{'Content-Length':'8'}))
 assert f._download('https://example.org/file',1,1,range_requests=True)==b'complete'


def test_retry_does_not_duplicate_committed_chunk(monkeypatch):
 body=b'x'*70000;attempts=[]
 opening,calls=responder(body)
 def flaky(req,**kwargs):
  attempts.append(req.get_header('Range'))
  if len(attempts)==2:raise TimeoutError('interrupted second part')
  return opening(req,**kwargs)
 monkeypatch.setattr(f,'urlopen',flaky);monkeypatch.setattr(f.time,'sleep',lambda _:None)
 assert f._download('https://example.org/file',1,2,range_requests=True)==body
 assert attempts[1]==attempts[2]


def test_404_and_long_retry_after_not_hammered(monkeypatch):
 for code,headers in [(404,{}),(503,{'Retry-After':'120'})]:
  calls=[]
  def unavailable(*a,**k):calls.append(1);raise HTTPError('url',code,'unavailable',headers,None)
  monkeypatch.setattr(f,'urlopen',unavailable)
  with pytest.raises(HTTPError):f._download('https://example.org/file',1,3,range_requests=True)
  assert len(calls)==1


@pytest.mark.parametrize('start,dataset,expected',[
 ('2024-01-01','auto','recent'),('2022-01-04','auto','recent'),('2022-01-03','auto','all'),
 ('1960-01-01','auto','all'),('2024-01-01','all','all'),('2020-01-01','recent','recent')])
def test_conservative_source_choice(start,dataset,expected):
 url=f._atmosphere_source(datetime.fromisoformat(start),dataset,datetime(2026,11,20))
 assert url==(f.MSIS_RECENT_URL if expected=='recent' else f.MSIS_URL)


def test_invalid_dataset_before_download(tmp_path,monkeypatch):
 monkeypatch.setattr(f,'_download',lambda *a,**k:pytest.fail('Unexpected download'))
 with pytest.raises(ValueError):f.download_atmosphere_inputs('2024-09-10','2024-09-11',tmp_path,dataset='invented')


def test_cache_expiry_and_future_timestamp(tmp_path):
 now=datetime(2026,11,20,tzinfo=timezone.utc)
 f._save_weather_cache(tmp_path,f.MSIS_URL,b'captured',now.isoformat())
 assert f._cached_weather(tmp_path,f.MSIS_URL,now+timedelta(hours=2))==(b'captured',now.isoformat())
 assert f._cached_weather(tmp_path,f.MSIS_URL,now+timedelta(hours=3)) is None
 assert f._cached_weather(tmp_path,f.MSIS_URL,now-timedelta(seconds=1)) is None


def test_cache_corruption_is_not_silently_used(tmp_path):
 now=datetime.now(timezone.utc)
 f._save_weather_cache(tmp_path,f.MSIS_URL,b'captured',now.isoformat())
 next(tmp_path.glob('*.csv')).write_bytes(b'corrupt')
 with pytest.raises(ValueError,match='SHA256'):f._cached_weather(tmp_path,f.MSIS_URL,now)


def test_cache_hit_has_original_timestamp_and_no_network(tmp_path,monkeypatch):
 body=runpy.run_path(str(Path(__file__).with_name('test_atmosphere_inputs.py')))['source']()
 calls=[]
 def download(*a,**k):calls.append(1);return body
 monkeypatch.setattr(f,'_download',download)
 first=f.download_atmosphere_inputs('2024-09-10','2024-09-11',tmp_path/'out',cache_dir=tmp_path/'cache')
 second=f.download_atmosphere_inputs('2024-09-10','2024-09-11',tmp_path/'out',cache_dir=tmp_path/'cache')
 assert len(calls)==1 and second['source_mode']=='validated_cache' and first['source_mode']=='network'
 assert first['source_retrieved_at']==second['source_retrieved_at']
 m=json.loads(Path(second['manifest']).read_text())
 assert m['retrieved_at']==first['source_retrieved_at']
 assert m['source_file']=='SW-Last5Years.csv' and (Path(second['manifest']).parent/m['source_file']).is_file()


def test_cache_write_failure_not_reported_as_success(tmp_path,monkeypatch):
 body=runpy.run_path(str(Path(__file__).with_name('test_atmosphere_inputs.py')))['source']()
 monkeypatch.setattr(f,'_download',lambda *a,**k:body)
 def fail(*a):raise OSError('cache full')
 monkeypatch.setattr(f,'_save_weather_cache',fail)
 with pytest.raises(OSError,match='cache full'):
  f.download_atmosphere_inputs('2024-09-10','2024-09-11',tmp_path/'out',cache_dir=tmp_path/'cache')
 assert not list((tmp_path/'out').iterdir())

def test_real_http_range_round_trip(monkeypatch):
    from http.server import BaseHTTPRequestHandler,HTTPServer
    import threading
    body=bytes(range(256))*600
    seen=[]
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*args):pass
        def do_GET(self):
            first,last=map(int,re.fullmatch(r'bytes=(\d+)-(\d+)',self.headers['Range']).groups())
            last=min(last,len(body)-1);seen.append((first,last,self.headers.get('If-Range')))
            self.send_response(206)
            self.send_header('Content-Range',f'bytes {first}-{last}/{len(body)}')
            self.send_header('Content-Length',str(last-first+1))
            self.send_header('ETag','"real-http"');self.end_headers()
            self.wfile.write(body[first:last+1])
    server=HTTPServer(('127.0.0.1',0),Handler)
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    try:
        actual=f._download(f'http://127.0.0.1:{server.server_port}/file.csv',2,1,range_requests=True)
        assert actual==body and len(seen)==3
        assert seen[0][2] is None and seen[1][2]=='"real-http"'
    finally:server.shutdown();server.server_close();thread.join(timeout=5)
