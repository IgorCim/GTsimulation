"""The offline replay harness must preserve source identity, not require unrelated models."""
import hashlib
import json
from pathlib import Path
import runpy
import pytest
import fetcher as f

check=runpy.run_path(str(Path(__file__).with_name('check_live.py')))

@pytest.mark.parametrize('filename,url',[('SW-All.csv',f.MSIS_URL),('SW-Last5Years.csv',f.MSIS_RECENT_URL)])
def test_replay_atmosphere_only_preserves_dataset(tmp_path,filename,url):
    (tmp_path/filename).write_bytes(b'captured')
    (tmp_path/'manifest.json').write_text(json.dumps({'source':url,'source_sha256':hashlib.sha256(b'captured').hexdigest()}))
    files=check['replay_files'](tmp_path,['nrlmsis'])
    assert list(files)==[filename] and files[filename]['url']==url

@pytest.mark.parametrize('damage',['hash','url','missing'])
def test_replay_rejects_invalid_evidence(tmp_path,damage):
    (tmp_path/'SW-Last5Years.csv').write_bytes(b'captured')
    meta={'source':f.MSIS_RECENT_URL,'source_sha256':hashlib.sha256(b'captured').hexdigest()}
    if damage=='hash':meta['source_sha256']='0'*64
    if damage=='url':meta['source']='https://example.org/other'
    if damage!='missing':(tmp_path/'manifest.json').write_text(json.dumps(meta))
    with pytest.raises(ValueError):check['replay_files'](tmp_path,['nrlmsis'])
