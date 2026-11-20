"""Prepare hourly T89/T96 inputs from NASA SPDF OMNI2 annual ASCII files."""
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import shutil
import tempfile
import time
from urllib.error import HTTPError, URLError
from urllib.request import urlopen
import numpy as np

BASE_URL = "https://spdf.gsfc.nasa.gov/pub/data/omni/low_res_omni"
MAX_BYTES = 8 * 1024 * 1024
DTYPE = np.dtype([("date", "datetime64[s]"), ("T89_input", "i1"),
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


def _download(url, timeout, attempts, *, max_bytes=None):
    if max_bytes is None:
        max_bytes = MAX_BYTES
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
    rows = np.zeros(count, dtype=DTYPE)
    rows["T89_input"] = -1
    rows["T96_input"] = np.nan
    records, sources, raw = {}, [], {}
    for year in range(start.year, (end - timedelta(hours=1)).year + 1):
        url = f"{BASE_URL}/omni2_{year}.dat"
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
