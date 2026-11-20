"""Download and freeze NRLMSIS drivers without altering pymsis process state."""
import csv
from datetime import datetime, timedelta, timezone
import hashlib
import io
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import numpy as np
from .omni import _download, _utc_hour

URL = "https://celestrak.org/SpaceData/SW-All.csv"
DTYPE = np.dtype([("date", "datetime64[s]"), ("f107", "f8"),
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


_WORKER = '''
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
'''


def download_atmosphere_inputs(start, end, output_dir, *, timeout=30, attempts=3):
    """Prepare observed-only hourly inputs in [start,end); retain original CSV."""
    start, end = _utc_hour(start), _utc_hour(end)
    if start >= end or end-start > timedelta(days=366):
        raise ValueError("Require start < end and at most 366 days.")
    if isinstance(attempts, bool) or not isinstance(attempts,int) or not 1 <= attempts <= 5:
        raise ValueError("attempts must be an integer from 1 to 5.")
    if not np.isfinite(timeout) or timeout <= 0:
        raise ValueError("timeout must be positive and finite.")
    body = _download(URL, timeout, attempts)
    prepared = _validated_csv(body, start, end)
    parent = Path(output_dir).expanduser().resolve()
    parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=".msis-", dir=parent))
    try:
        (staging / "SW-All.csv").write_bytes(body)
        (staging / "selected.csv").write_text(prepared, encoding="utf-8")
        worker = subprocess.run([sys.executable, "-c", _WORKER,
            str(staging / "selected.csv"), start.isoformat(), end.isoformat(),
            str(staging / "inputs.npy")], capture_output=True, text=True, timeout=120)
        if worker.returncode:
            raise ValueError("pymsis input preparation failed: " + worker.stderr[-2000:])
        rows = load_atmosphere_inputs(staging / "inputs.npy")
        manifest = {"schema":"gt-msis-inputs-v1", "rows":len(rows),
            "start":start.isoformat()+"Z", "end_exclusive":end.isoformat()+"Z",
            "source":URL, "source_sha256":hashlib.sha256(body).hexdigest(),
            "retrieved_at":datetime.now(timezone.utc).isoformat(),
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
    return {"input_file":str(bundle/"inputs.npy"), "manifest":str(bundle/"manifest.json"),
            "rows":len(rows), "model":"nrlmsis",
            "space_weather_file":str(bundle/"selected.csv")}


def load_atmosphere_inputs(path):
    rows = np.load(path, allow_pickle=False)
    if not isinstance(rows, np.ndarray):
        rows.close()
        raise ValueError("Expected NPY array.")
    if rows.ndim != 1 or not len(rows) or rows.dtype != DTYPE:
        raise ValueError("Invalid atmospheric input schema.")
    dates=rows["date"]
    if np.any(np.isnat(dates)) or np.any(dates != dates.astype("datetime64[h]")) or np.any(np.diff(dates) != np.timedelta64(1,"h")):
        raise ValueError("Atmospheric hours must be sorted, unique and continuous.")
    for key in ("f107", "f107a", "ap"):
        values=rows[key]
        if not np.all(np.isfinite(values)) or np.any(values>400) or np.any(values<0) or (key != "ap" and np.any(values==0)):
            raise ValueError("Invalid atmospheric drivers.")
    return rows


def atmosphere_at(path, date):
    rows=load_atmosphere_inputs(path)
    if date.tzinfo is not None:
        date=date.astimezone(timezone.utc).replace(tzinfo=None)
    stamp=np.datetime64(date)
    if not rows["date"][0] <= stamp < rows["date"][-1]+np.timedelta64(1,"h"):
        raise ValueError("Date outside the external atmospheric interval.")
    row=rows[np.searchsorted(rows["date"],stamp,side="right")-1]
    return date, np.array([row["f107"]]), np.array([row["f107a"]]), row["ap"][None,:].copy()
