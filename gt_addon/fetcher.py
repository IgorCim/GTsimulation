"""Standalone input downloader; does not import, modify, or run GT models."""
import argparse
import csv
from datetime import datetime, timedelta, timezone
import hashlib
import io
import re
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
from urllib.error import HTTPError, URLError
from urllib.request import urlopen, Request
import numpy as np

# OMNI INPUTS
OMNI_BASE_URL = "https://spdf.gsfc.nasa.gov/pub/data/omni/low_res_omni"
OMNI_MAX_BYTES = 8 * 1024 * 1024
OMNI_DTYPE = np.dtype([("date", "datetime64[s]"), ("T89_input", "i1"),
                  ("T96_input", "<f8", (4,))])
KP_CODES = set(range(0, 91, 10)) | set(range(3, 84, 10)) | set(range(7, 88, 10))


def _utc_hour(value):
    if isinstance(value, str):
        value = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if not isinstance(value, datetime):
        raise ValueError("Expected an ISO date/time or datetime.")
    if value.tzinfo is not None:
        value = value.astimezone(timezone.utc).replace(tzinfo=None)
    if value.minute or value.second or value.microsecond:
        raise ValueError("Interval boundaries must be whole UTC hours.")
    return value


def _download(url, timeout, attempts, *, max_bytes=None, range_requests=False):
    if max_bytes is None:
        max_bytes = OMNI_MAX_BYTES
    if range_requests:
        return _download_ranges(url, timeout, attempts, max_bytes)
    for attempt in range(attempts):
        try:
            with urlopen(url, timeout=timeout) as response:
                body = response.read(max_bytes + 1)
            if len(body) > max_bytes:
                raise ValueError("Input response exceeds the size limit.")
            return body
        except (URLError, TimeoutError) as exc:
            if isinstance(exc, HTTPError) and exc.code not in (408, 429, 500, 502, 503, 504):
                raise
            if attempt + 1 == attempts:
                raise
            time.sleep(0.5 * (attempt + 1))



def _download_ranges(url, timeout, attempts, max_bytes):
    """One stable file, retrieved in bounded HTTP ranges. Never mix versions."""
    body=bytearray();total=None;etag=None
    while total is None or len(body)<total:
        offset=len(body)
        last=min(offset+65535,max_bytes-1)
        if total is not None:last=min(last,total-1)
        headers={"Range":f"bytes={offset}-{last}",
                 "User-Agent":"gt-input-addon/1.0 (+https://github.com/IgorCim/GTsimulation)",
                 "Accept-Encoding":"identity"}
        if etag:headers["If-Range"]=etag
        for attempt in range(attempts):
            try:
                with urlopen(Request(url,headers=headers),timeout=timeout) as response:
                    if response.headers.get("Content-Encoding","identity").lower()!="identity":
                        raise ValueError("Encoded range response is not supported.")
                    if response.status==200:
                        if offset:raise ValueError("CelesTrak changed file or stopped honoring ranges; refusing mixed data.")
                        complete=response.read(max_bytes+1)
                        if len(complete)>max_bytes:raise ValueError("Input response exceeds the size limit.")
                        declared=response.headers.get("Content-Length")
                        if declared is not None and int(declared)!=len(complete):raise ValueError("Incomplete CelesTrak file.")
                        return complete
                    if response.status!=206:raise ValueError("Unexpected HTTP range status.")
                    match=re.fullmatch(r"bytes (\d+)-(\d+)/(\d+)",response.headers.get("Content-Range",""))
                    if not match:raise ValueError("Invalid CelesTrak Content-Range.")
                    first,end,size=map(int,match.groups())
                    tag=response.headers.get("ETag")
                    if first!=offset or end!=min(last,size-1) or not 0<size<=max_bytes or first>end:
                        raise ValueError("Invalid CelesTrak range offsets or size limit.")
                    if not tag or tag.startswith('W/'):
                        raise ValueError("Strong ETag required for stable CelesTrak ranged download.")
                    if total is not None and (size!=total or tag!=etag):raise ValueError("CelesTrak changed during download.")
                    declared=response.headers.get("Content-Length")
                    if declared is not None and int(declared)!=end-first+1:raise ValueError("Range Content-Length mismatch.")
                    part=response.read(end-first+2)
                    if len(part)!=end-first+1:raise ValueError("Incomplete CelesTrak range.")
                # Commit a chunk only after all checks and successful read.
                body.extend(part);total=size;etag=tag
                break
            except (URLError,TimeoutError) as exc:
                if isinstance(exc,HTTPError) and exc.code not in (408,429,500,502,503,504):raise
                if attempt+1==attempts:raise
                retry_after=exc.headers.get("Retry-After") if isinstance(exc,HTTPError) else None
                if retry_after:
                    if not retry_after.isdigit() or int(retry_after)>timeout:raise
                    time.sleep(int(retry_after))
                else:time.sleep(0.5*(attempt+1))
    return bytes(body)

def _parse_year(body, year):
    records = {}
    for number, line in enumerate(body.decode("ascii").splitlines(), 1):
        if not line.strip():
            continue
        fields = line.split()
        if len(fields) not in (55, 56, 57):
            raise ValueError(f"Invalid OMNI record at line {number}: {len(fields)} fields.")
        try:
            record_year, day, hour = map(int, fields[:3])
            timestamp = datetime(record_year, 1, 1) + timedelta(days=day - 1, hours=hour)
            values = [float(fields[i]) for i in (38, 28, 40, 15, 16)]
        except (ValueError, OverflowError) as exc:
            raise ValueError(f"Invalid OMNI values at line {number}.") from exc
        if record_year != year or day < 1 or not 0 <= hour <= 23 or timestamp.year != year:
            raise ValueError(f"Invalid OMNI date at line {number}.")
        if timestamp in records:
            raise ValueError(f"Duplicate OMNI timestamp: {timestamp}.")
        records[timestamp] = values
    if not records:
        raise ValueError("Empty OMNI response.")
    return records


def download_tsyganenko_inputs(start, end, output_dir, *, model="96", timeout=30, attempts=3):
    """Download UTC hours in [start, end) into a new, uniquely named bundle.

    Require every hour and valid drivers for the chosen model (89 or 96).
    Keep original source bytes and SHA256 hashes. Do not interpolate gaps.
    """
    start, end = _utc_hour(start), _utc_hour(end)
    model = str(model)
    if model not in ("89", "96"):
        raise ValueError("Supported models are 89 and 96.")
    if start >= end or start.year < 1963 or end - start > timedelta(days=366):
        raise ValueError("Require 1963 or later, start < end, and at most 366 days.")
    if not isinstance(attempts, int) or isinstance(attempts, bool) or not 1 <= attempts <= 5:
        raise ValueError("attempts must be an integer from 1 to 5.")
    if not np.isfinite(timeout) or timeout <= 0:
        raise ValueError("timeout must be positive and finite.")
    count = int((end - start).total_seconds() // 3600)
    rows = np.zeros(count, dtype=OMNI_DTYPE)
    rows["T89_input"] = -1
    rows["T96_input"] = np.nan
    records, sources, raw = {}, [], {}
    for year in range(start.year, (end - timedelta(hours=1)).year + 1):
        url = f"{OMNI_BASE_URL}/omni2_{year}.dat"
        body = _download(url, timeout, attempts)
        records.update(_parse_year(body, year))
        filename = f"omni2_{year}.dat"
        raw[filename] = body
        sources.append({"url": url, "file": filename,
                        "sha256": hashlib.sha256(body).hexdigest()})
    for i in range(count):
        timestamp = start + timedelta(hours=i)
        if timestamp not in records:
            raise ValueError(f"Missing OMNI hour: {timestamp.isoformat()}Z.")
        kp, pressure, dst, by, bz = records[timestamp]
        valid_kp = np.isfinite(kp) and kp in KP_CODES
        valid_t96 = (np.all(np.isfinite([pressure, dst, by, bz]))
                     and 0 < pressure < 99.99 and abs(dst) < 99999
                     and abs(by) < 999.9 and abs(bz) < 999.9)
        if (model == "89" and not valid_kp) or (model == "96" and not valid_t96):
            raise ValueError(f"Missing or invalid T{model} drivers at {timestamp.isoformat()}Z.")
        rows["date"][i] = np.datetime64(timestamp, "s")
        if valid_kp:
            rows["T89_input"][i] = min(7, int((kp + 3) // 10) + 1)
        if valid_t96:
            rows["T96_input"][i] = [pressure, dst, by, bz]
    parent = Path(output_dir).expanduser().resolve()
    parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=".omni-", dir=parent))
    try:
        np.save(staging / "inputs.npy", rows, allow_pickle=False)
        for filename, body in raw.items():
            (staging / filename).write_bytes(body)
        manifest = {
            "schema": "gt-omni-inputs-v1", "model": model, "rows": count,
            "start": start.isoformat() + "Z", "end_exclusive": end.isoformat() + "Z",
            "time_system": "UTC", "sampling": "hourly interval start",
            "selection": "containing hour; no interpolation",
            "units": {"pressure": "nPa", "Dst": "nT", "By": "nT", "Bz": "nT"},
            "imf_coordinates": "GSM", "sources": sources,
            "retrieved_at": datetime.now(timezone.utc).isoformat(),
            "input_sha256": hashlib.sha256((staging / "inputs.npy").read_bytes()).hexdigest(),
        }
        (staging / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        bundle = parent / ("omni-" + staging.name.removeprefix(".omni-"))
        staging.rename(bundle)
    except BaseException:
        if staging.resolve().parent != parent:
            raise RuntimeError("Unexpected staging directory.")
        shutil.rmtree(staging)
        raise
    return {"input_file": str(bundle / "inputs.npy"),
            "manifest": str(bundle / "manifest.json"), "rows": count, "model": model}


def load_inputs(path, model):
    """Read numeric NPY drivers, rejecting unsafe or incomplete model inputs."""
    model = str(model)
    if model not in ("89", "96"):
        raise ValueError("External OMNI inputs support T89/T96 only.")
    data = np.load(path, allow_pickle=False)
    if not isinstance(data, np.ndarray):
        data.close()
        raise ValueError("Expected an NPY array.")
    column = "T89_input" if model == "89" else "T96_input"
    if data.ndim != 1 or len(data) == 0 or not data.dtype.names:
        raise ValueError("Expected a nonempty structured input array.")
    if not {"date", column}.issubset(data.dtype.names):
        raise ValueError("Missing date or model input column.")
    dates = data["date"]
    if dates.dtype.kind != "M" or np.any(np.isnat(dates)):
        raise ValueError("Invalid input timestamps.")
    if np.any(dates != dates.astype("datetime64[h]")):
        raise ValueError("Expected whole UTC hours.")
    if np.any(np.diff(dates) != np.timedelta64(1, "h")):
        raise ValueError("Input hours must be sorted, unique and continuous.")
    values = data[column]
    expected = (len(data),) if model == "89" else (len(data), 4)
    if values.shape != expected or values.dtype.kind not in "iuf":
        raise ValueError("Invalid model input dimensions or type.")
    values = values.astype(np.float64)
    if not np.all(np.isfinite(values)):
        raise ValueError("Nonfinite model drivers.")
    if model == "89":
        if np.any((values < 1) | (values > 7) | (values != np.floor(values))):
            raise ValueError("T89 activity bins must be integers 1..7.")
    elif (np.any(values[:, 0] <= 0) or np.any(values[:, 0] >= 99.99)
          or np.any(np.abs(values[:, 1]) >= 99999)
          or np.any(np.abs(values[:, 2:]) >= 999.9)):
        raise ValueError("Invalid T96 drivers or OMNI fill values.")
    return data


# TA15 INPUTS
TA15_BASE_URL = "https://geo.phys.spbu.ru/~tsyganenko/models/ta15"
TA15_DTYPE = np.dtype([("date","datetime64[s]"),("T15B_input","f8",(4,)),
                  ("imf_flag","i1"),("sw_flag","i1")])
COMPATIBILITY = ("TA15 source IMF is GSW (30-minute trailing averages). This addon prepares "
                 "inputs only; coordinate handling and model execution belong to GT.")


def _five_minute_boundary(value):
    if isinstance(value,str): value=datetime.fromisoformat(value.replace('Z','+00:00'))
    if not isinstance(value,datetime): raise ValueError('Expected ISO time or datetime.')
    if value.tzinfo is not None: value=value.astimezone(timezone.utc).replace(tzinfo=None)
    if value.minute%5 or value.second or value.microsecond:
        raise ValueError('TA15 boundaries must be whole five-minute UTC slots.')
    return value


def _parse_ta15(body,year):
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
    if rows.ndim!=1 or not len(rows) or rows.dtype!=TA15_DTYPE:
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
    start,end=_five_minute_boundary(start),_five_minute_boundary(end)
    if start>=end or start.year<1995 or end-start>timedelta(days=366):
        raise ValueError('Require 1995 or later, start < end, at most 366 days.')
    if type(allow_interpolated) is not bool: raise ValueError('allow_interpolated must be boolean.')
    if type(attempts) is not int or not 1<=attempts<=5: raise ValueError('attempts must be 1..5.')
    if not np.isfinite(timeout) or timeout<=0: raise ValueError('timeout must be positive and finite.')
    records={};raw={};sources=[]
    for year in range(start.year,(end-timedelta(seconds=1)).year+1):
        name=f'{year}_OMNI_5m_with_TA15_drivers.dat';url=f'{TA15_BASE_URL}/{name}'
        body=_download(url,timeout,attempts,max_bytes=32*1024*1024)
        records.update(_parse_ta15(body,year));raw[name]=body
        sources.append({'url':url,'sha256':hashlib.sha256(body).hexdigest()})
    rows=np.empty(int((end-start).total_seconds()//300),dtype=TA15_DTYPE)
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


# ATMOSPHERE INPUTS
MSIS_URL = "https://celestrak.org/SpaceData/SW-All.csv"
MSIS_RECENT_URL = "https://celestrak.org/SpaceData/SW-Last5Years.csv"
MSIS_DTYPE = np.dtype([("date", "datetime64[s]"), ("f107", "f8"),
                  ("f107a", "f8"), ("ap", "f8", (7,))])


def _validated_csv(body, start, end):
    """Keep continuous required history; reject forecasts, gaps and bad values."""
    text = body.decode("utf-8-sig")
    reader = csv.DictReader(io.StringIO(text))
    required = ["DATE", "F10.7_OBS", "F10.7_OBS_CENTER81", "F10.7_DATA_TYPE",
                "AP_AVG"] + [f"AP{i}" for i in range(1, 9)]
    if not reader.fieldnames or not set(required) <= set(reader.fieldnames):
        raise ValueError("Invalid CelesTrak CSV header.")
    positions = {0:"DATE", 20:"AP_AVG", 24:"F10.7_OBS", 26:"F10.7_DATA_TYPE", 27:"F10.7_OBS_CENTER81"}
    positions.update({11+i:f"AP{i}" for i in range(1,9)})
    if any(len(reader.fieldnames)<=i or reader.fieldnames[i]!=name for i,name in positions.items()):
        raise ValueError("CelesTrak column order is incompatible with pymsis.")
    first = start.replace(hour=0) - timedelta(days=3)
    last = (end - timedelta(seconds=1)).replace(hour=0)
    selected = {}
    for row in reader:
        day = datetime.fromisoformat(row["DATE"])
        if not first <= day <= last:
            continue
        if day in selected:
            raise ValueError("Duplicate space-weather date.")
        if row["F10.7_DATA_TYPE"] != "OBS":
            raise ValueError(f"Non-observed space weather at {day.date()}.")
        solar = [float(row[k]) for k in ("F10.7_OBS", "F10.7_OBS_CENTER81")]
        ap = [float(row[k]) for k in ["AP_AVG"] + [f"AP{i}" for i in range(1,9)]]
        if not np.all(np.isfinite(solar + ap)) or not all(0 < x <= 400 for x in solar) or not all(0 <= x <= 400 for x in ap):
            raise ValueError(f"Invalid space-weather drivers at {day.date()}.")
        selected[day] = row
    days = [first + timedelta(days=i) for i in range((last-first).days+1)]
    if any(day not in selected for day in days):
        raise ValueError("Missing space-weather day or required 57-hour history.")
    out = io.StringIO(newline="")
    writer = csv.DictWriter(out, fieldnames=reader.fieldnames)
    writer.writeheader()
    writer.writerows(selected[day] for day in days)
    return out.getvalue()


_WORKER = """
import sys, warnings, numpy as np, pymsis
from pymsis.utils import use_space_weather_file, get_f107_ap
from importlib.metadata import version
use_space_weather_file(sys.argv[1])
dates = np.arange(np.datetime64(sys.argv[2]), np.datetime64(sys.argv[3]), np.timedelta64(1, "h"))
with warnings.catch_warnings():
    warnings.simplefilter("error")
    f107, f107a, ap = get_f107_ap(dates, interpolate=False)
rows = np.empty(len(dates), dtype=[("date","datetime64[s]"),("f107","f8"),("f107a","f8"),("ap","f8",(7,))])
rows["date"], rows["f107"], rows["f107a"], rows["ap"] = dates, f107, f107a, ap
np.save(sys.argv[4], rows, allow_pickle=False)
print(version("pymsis"))
"""



def _atmosphere_source(start, dataset, now=None):
    if dataset not in ("auto","all","recent"):raise ValueError("dataset must be auto, all or recent.")
    now=now or datetime.now(timezone.utc)
    # Conservative subset of the rolling file: four complete calendar years
    # plus current year. Earlier dates use the full historical file.
    recent=start-timedelta(days=3)>=datetime(now.year-4,1,1)
    return MSIS_RECENT_URL if dataset=="recent" or (dataset=="auto" and recent) else MSIS_URL


def _cached_weather(cache_dir,url,now):
    if cache_dir is None:return None
    root=Path(cache_dir).expanduser().resolve()
    key=hashlib.sha256(url.encode()).hexdigest()[:16]
    entry=root/(key+".json")
    if not entry.is_file():return None
    meta=json.loads(entry.read_text(encoding="utf-8"))
    age=(now-datetime.fromisoformat(meta["retrieved_at"])).total_seconds()
    if meta["url"]!=url or not 0<=age<3*3600:return None
    if not re.fullmatch(r"[0-9a-f]{64}",meta["sha256"]):raise ValueError("Invalid CelesTrak cache digest.")
    raw=root/(key+"-"+meta["sha256"]+".csv")
    body=raw.read_bytes()
    if hashlib.sha256(body).hexdigest()!=meta["sha256"]:raise ValueError("CelesTrak cache SHA256 mismatch; refusing cached data.")
    return body,meta["retrieved_at"]


def _save_weather_cache(cache_dir,url,body,retrieved_at):
    if cache_dir is None:return
    root=Path(cache_dir).expanduser().resolve();root.mkdir(parents=True,exist_ok=True)
    key=hashlib.sha256(url.encode()).hexdigest()[:16]
    digest=hashlib.sha256(body).hexdigest()
    # Immutable hash-addressed data, then atomic metadata: concurrent readers
    # always reference a complete source, never a mixed CSV/metadata pair.
    temporary=Path(tempfile.mkdtemp(prefix=".source-",dir=root))
    try:
        (temporary/"data.csv").write_bytes(body)
        (temporary/"meta.json").write_text(json.dumps({"url":url,"retrieved_at":retrieved_at,"sha256":hashlib.sha256(body).hexdigest()},indent=2),encoding="utf-8")
        (temporary/"data.csv").replace(root/(key+"-"+digest+".csv"))
        (temporary/"meta.json").replace(root/(key+".json"))
    finally:
        if temporary.resolve().parent!=root:raise RuntimeError("Unexpected cache staging directory.")
        shutil.rmtree(temporary)

def download_atmosphere_inputs(start, end, output_dir, *, timeout=30, attempts=3, dataset="auto", cache_dir=None):
    """Prepare observed-only hourly inputs in [start,end); retain original CSV."""
    start, end = _utc_hour(start), _utc_hour(end)
    if start >= end or end-start > timedelta(days=366):
        raise ValueError("Require start < end and at most 366 days.")
    if isinstance(attempts, bool) or not isinstance(attempts,int) or not 1 <= attempts <= 5:
        raise ValueError("attempts must be an integer from 1 to 5.")
    if not np.isfinite(timeout) or timeout <= 0:
        raise ValueError("timeout must be positive and finite.")
    url=_atmosphere_source(start,dataset)
    now=datetime.now(timezone.utc)
    cached=_cached_weather(cache_dir,url,now)
    if cached is None:
        body=_download(url, timeout, attempts, range_requests=True)
        source_retrieved_at=datetime.now(timezone.utc).isoformat()
        source_mode="network"
    else:
        body,source_retrieved_at=cached
        source_mode="validated_cache"
    prepared = _validated_csv(body, start, end)
    parent = Path(output_dir).expanduser().resolve()
    parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=".msis-", dir=parent))
    try:
        (staging / url.rsplit("/",1)[-1]).write_bytes(body)
        (staging / "selected.csv").write_text(prepared, encoding="utf-8")
        worker = subprocess.run([sys.executable, "-c", _WORKER,
            str(staging / "selected.csv"), start.isoformat(), end.isoformat(),
            str(staging / "inputs.npy")], capture_output=True, text=True, timeout=120)
        if worker.returncode:
            raise ValueError("pymsis input preparation failed: " + worker.stderr[-2000:])
        rows = load_atmosphere_inputs(staging / "inputs.npy")
        expected_dates = np.arange(np.datetime64(start), np.datetime64(end), np.timedelta64(1, "h"))
        if not np.array_equal(rows["date"], expected_dates):
            raise ValueError("Prepared atmospheric timestamps do not match the requested UTC interval.")
        manifest = {"schema":"gt-msis-inputs-v1", "rows":len(rows),
            "start":start.isoformat()+"Z", "end_exclusive":end.isoformat()+"Z",
            "source":url, "source_file":url.rsplit("/",1)[-1], "source_sha256":hashlib.sha256(body).hexdigest(),
            "source_mode":source_mode, "source_retrieved_at":source_retrieved_at,
            "cache_max_age_seconds":10800 if cache_dir is not None else None,
            "retrieved_at":source_retrieved_at, "created_at":datetime.now(timezone.utc).isoformat(),
            "input_sha256":hashlib.sha256((staging/"inputs.npy").read_bytes()).hexdigest(),
            "pymsis_version":worker.stdout.strip(), "time_system":"UTC",
            "policy":"observed only; no interpolation; previous-day F107 and 57-hour Ap history via pymsis",
            "units":{"f107":"sfu", "f107a":"sfu", "ap":"index"},
            "sampling":"hourly stored; daily F107/F107a/Ap; 3-hourly ap"}
        (staging/"manifest.json").write_text(json.dumps(manifest,indent=2),encoding="utf-8")
        bundle=parent/("msis-"+staging.name.removeprefix(".msis-"))
        staging.rename(bundle)
    except BaseException:
        if staging.resolve().parent != parent:
            raise RuntimeError("Unexpected staging directory.")
        shutil.rmtree(staging)
        raise
    if source_mode=="network":
        try:_save_weather_cache(cache_dir,url,body,source_retrieved_at)
        except BaseException:
            if bundle.resolve().parent!=parent:raise RuntimeError("Unexpected bundle directory.")
            shutil.rmtree(bundle)
            raise
    return {"input_file":str(bundle/"inputs.npy"), "manifest":str(bundle/"manifest.json"),
            "rows":len(rows), "model":"nrlmsis", "source_mode":source_mode,
            "source_retrieved_at":source_retrieved_at,
            "space_weather_file":str(bundle/"selected.csv")}


def load_atmosphere_inputs(path):
    rows = np.load(path, allow_pickle=False)
    if not isinstance(rows, np.ndarray):
        rows.close()
        raise ValueError("Expected NPY array.")
    if rows.ndim != 1 or not len(rows) or rows.dtype != MSIS_DTYPE:
        raise ValueError("Invalid atmospheric input schema.")
    dates=rows["date"]
    if np.any(np.isnat(dates)) or np.any(dates != dates.astype("datetime64[h]")) or np.any(np.diff(dates) != np.timedelta64(1,"h")):
        raise ValueError("Atmospheric hours must be sorted, unique and continuous.")
    for key in ("f107", "f107a", "ap"):
        values=rows[key]
        if not np.all(np.isfinite(values)) or np.any(values>400) or np.any(values<0) or (key != "ap" and np.any(values==0)):
            raise ValueError("Invalid atmospheric drivers.")
    return rows



def main():
    parser = argparse.ArgumentParser(description="Download external GT drivers: T89/T96, T15B, NRLMSIS.")
    parser.add_argument("--start", required=True, help="UTC start, inclusive (ISO 8601)")
    parser.add_argument("--end", required=True, help="UTC end, exclusive (ISO 8601)")
    parser.add_argument("--model", choices=["89", "96", "15B", "nrlmsis"], default="96")
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--allow-provider-interpolation", action="store_true", help="TA15 only: accept provider quality flag 2")
    args = parser.parse_args()
    if args.allow_provider_interpolation and args.model != "15B":
        parser.error("--allow-provider-interpolation requires --model 15B")
    try:
        if args.model == "15B":
            result = download_ta15_inputs(args.start, args.end, args.output_dir, allow_interpolated=args.allow_provider_interpolation)
        elif args.model == "nrlmsis":
            result = download_atmosphere_inputs(args.start, args.end, args.output_dir, cache_dir=Path(args.output_dir)/".celestrak-cache")
        else:
            result = download_tsyganenko_inputs(args.start, args.end, args.output_dir, model=args.model)
    except (ValueError, OSError, subprocess.SubprocessError) as exc:
        parser.exit(1, f"Input preparation failed: {exc}\n")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
