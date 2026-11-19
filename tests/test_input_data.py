"""Offline contract and failure tests for OMNI input preparation."""
from datetime import datetime
import hashlib
import importlib.util
import io
import json
from pathlib import Path
from urllib.error import HTTPError, URLError
import numpy as np
import pytest

# Exercise the download module without requiring Geant4 or importing the simulator.
MODULE = Path(__file__).parents[1] / "src/gtsimulation/input_data/omni.py"
spec = importlib.util.spec_from_file_location("omni_inputs", MODULE)
omni = importlib.util.module_from_spec(spec)
spec.loader.exec_module(omni)


def record(hour=0, year=2024, day=1, **changes):
    fields = ["0"] * 57
    for i, value in {0:year, 1:day, 2:hour, 38:23, 28:2.3, 40:-25, 15:4, 16:-3}.items():
        fields[i] = str(value)
    for key, value in changes.items():
        fields[int(key)] = str(value)
    return (" ".join(fields) + "\n").encode()


def prepare(monkeypatch, tmp_path, body=None, **kwargs):
    monkeypatch.setattr(omni, "_download", lambda *args: record() if body is None else body)
    return omni.download_tsyganenko_inputs("2024-01-01", "2024-01-01T01:00", tmp_path, **kwargs)


def test_values_provenance_and_repeated_calls(monkeypatch, tmp_path):
    result = prepare(monkeypatch, tmp_path)
    rows = omni.load_inputs(result["input_file"], "96")
    np.testing.assert_array_equal(rows["T96_input"][0], [2.3,-25,4,-3])
    assert rows["T89_input"][0] == 3
    metadata = json.loads(Path(result["manifest"]).read_text())
    assert metadata["input_sha256"] == hashlib.sha256(Path(result["input_file"]).read_bytes()).hexdigest()
    assert metadata["sources"][0]["sha256"] == hashlib.sha256(record()).hexdigest()
    assert metadata["imf_coordinates"] == "GSM"
    again = prepare(monkeypatch, tmp_path)
    assert result["input_file"] != again["input_file"]
    assert Path(result["input_file"]).exists()


@pytest.mark.parametrize("kp,expected", [(0,1),(3,1),(7,2),(13,2),(17,3),(53,6),(57,7),(90,7)])
def test_kp_bins(monkeypatch,tmp_path,kp,expected):
    out = prepare(monkeypatch,tmp_path,record(**{"38":kp}),model="89")
    assert omni.load_inputs(out["input_file"],"89")["T89_input"][0] == expected


@pytest.mark.parametrize("body", [
    b"<html>failure</html>", b"", record()+record(), record(day=367),
    record(**{"28":99.99}), record(**{"40":99999}), record(**{"15":999.9}),
    record(**{"16":"nan"}), record(**{"28":0}), record(hour=1),
])
def test_bad_data_no_output(monkeypatch,tmp_path,body):
    with pytest.raises(ValueError):
        prepare(monkeypatch,tmp_path,body)
    assert list(tmp_path.iterdir()) == []


def test_model_specific_missing(monkeypatch,tmp_path):
    out = prepare(monkeypatch,tmp_path,record(**{"28":99.99}),model="89")
    omni.load_inputs(out["input_file"],"89")
    with pytest.raises(ValueError):
        omni.load_inputs(out["input_file"],"96")
    with pytest.raises(ValueError):
        prepare(monkeypatch,tmp_path,record(**{"38":99}),model="89")


@pytest.mark.parametrize("args", [
    {"attempts":0},{"attempts":True},{"timeout":0},{"timeout":float("nan")},{"model":"15B"}
])
def test_invalid_options_before_network(monkeypatch,tmp_path,args):
    monkeypatch.setattr(omni,"_download",lambda *a: pytest.fail("Unexpected network"))
    with pytest.raises(ValueError):
        omni.download_tsyganenko_inputs("2024-01-01","2024-01-02",tmp_path,**args)


def test_cross_year_and_timezone(monkeypatch,tmp_path):
    def download(url,*args):
        return record(hour=23,day=366) if "2024" in url else record(year=2025)
    monkeypatch.setattr(omni,"_download",download)
    out=omni.download_tsyganenko_inputs("2025-01-01T00:00+01:00","2025-01-01T02:00+01:00",tmp_path)
    assert out["rows"] == 2
    assert len(json.loads(Path(out["manifest"]).read_text())["sources"]) == 2


def test_retry_and_404(monkeypatch):
    calls=[]
    def opening(*a,**kw):
        calls.append(1)
        if len(calls)==1: raise URLError("timeout")
        return io.BytesIO(record())
    monkeypatch.setattr(omni,"urlopen",opening)
    monkeypatch.setattr(omni.time,"sleep",lambda _:None)
    assert omni._download("https://example.org",1,2)==record()
    assert len(calls)==2
    calls.clear()
    def absent(*a,**kw):
        calls.append(1)
        raise HTTPError("url",404,"missing",{},None)
    monkeypatch.setattr(omni,"urlopen",absent)
    with pytest.raises(HTTPError): omni._download("url",1,3)
    assert len(calls)==1


def test_partial_write_cleanup(monkeypatch,tmp_path):
    monkeypatch.setattr(omni.np,"save",lambda *a,**kw: (_ for _ in ()).throw(OSError("disk full")))
    with pytest.raises(OSError): prepare(monkeypatch,tmp_path)
    assert list(tmp_path.iterdir())==[]


@pytest.mark.parametrize("mutation",["gap","nan","shape","fill"])
def test_loading_corrupt_inputs(tmp_path,mutation):
    a=np.zeros(2,dtype=omni.DTYPE)
    a["date"]=["2024-01-01T00","2024-01-01T01"]
    a["T96_input"]=[2,-10,1,-1]
    if mutation=="gap": a["date"][1]=np.datetime64("2024-01-01T03")
    if mutation=="nan": a["T96_input"][0,0]=np.nan
    if mutation=="fill": a["T96_input"][0,2]=999.9
    if mutation=="shape": a=a.reshape(1,2)
    path=tmp_path/"bad.npy"
    np.save(path,a)
    with pytest.raises(ValueError): omni.load_inputs(path,"96")


@pytest.mark.parametrize("start,end", [
    ("2024-01-01T00:01","2024-01-02"), ("2024-01-02","2024-01-01"),
    ("1962-01-01","1962-01-02"), ("2024-01-01","2026-01-01"),
    ("nonsense","2024-01-02"), ("2024-01-01","2024-01-01"),
])
def test_bad_interval_never_downloads(monkeypatch,tmp_path,start,end):
    monkeypatch.setattr(omni,"_download",lambda *a: pytest.fail("Unexpected network"))
    with pytest.raises(ValueError): omni.download_tsyganenko_inputs(start,end,tmp_path)
    assert not list(tmp_path.iterdir())


def test_timeout_exhaustion(monkeypatch,tmp_path):
    calls=[]
    def timeout(*a,**kw):
        calls.append(1)
        raise TimeoutError("offline")
    monkeypatch.setattr(omni,"urlopen",timeout)
    monkeypatch.setattr(omni.time,"sleep",lambda _:None)
    with pytest.raises(TimeoutError):
        omni.download_tsyganenko_inputs("2024-01-01","2024-01-02",tmp_path,attempts=2)
    assert len(calls)==2
    assert not list(tmp_path.iterdir())


def test_size_limit(monkeypatch):
    monkeypatch.setattr(omni,"MAX_BYTES",10)
    monkeypatch.setattr(omni,"urlopen",lambda *a,**kw: io.BytesIO(b"x"*11))
    with pytest.raises(ValueError,match="size limit"): omni._download("url",1,1)


def test_concurrent_bundles(monkeypatch,tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    monkeypatch.setattr(omni,"_download",lambda *args:record())
    def run(_):
        return omni.download_tsyganenko_inputs("2024-01-01","2024-01-01T01:00",tmp_path)
    with ThreadPoolExecutor(max_workers=3) as pool: results=list(pool.map(run,range(3)))
    assert len({r["input_file"] for r in results})==3
    for result in results: omni.load_inputs(result["input_file"],"96")
    assert all(p.name.startswith("omni-") for p in tmp_path.iterdir())


def test_pickle_and_npz_rejected(tmp_path):
    path=tmp_path/"object.npy"
    np.save(path,np.array([{"value":1}],dtype=object))
    with pytest.raises(ValueError): omni.load_inputs(path,"96")
    path=tmp_path/"wrong.npz"
    np.savez(path,values=np.zeros(1))
    with pytest.raises(ValueError,match="NPY"): omni.load_inputs(path,"96")
