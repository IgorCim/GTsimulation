from datetime import datetime
import json
import numpy as np
import pytest
from gtsimulation.input_data import ta15 as t


def source(flag=1,bindex=0.3):
    return ('2023 1 0 30 -1 4 -2 -600 -20 -10 2 100000 -20 1 %d -0.4 1.8 0.6 %s\n' % (flag,bindex) +
            '2023 1 0 35 -1 5 -3 -600 -20 -10 2 100000 -20 1 1 -0.4 2.0 0.6 0.4\n').encode()


def prepare(tmp_path,monkeypatch,body=None,**kwargs):
    monkeypatch.setattr(t,'_download',lambda *args,**kw:source() if body is None else body)
    return t.download_ta15_inputs('2023-01-01T00:30','2023-01-01T00:40',tmp_path,**kwargs)


def test_order_precision_flags(tmp_path,monkeypatch):
    r=prepare(tmp_path,monkeypatch,source(bindex=0.3126))
    rows=t.load_ta15_inputs(r['input_file'])
    np.testing.assert_array_equal(rows['T15B_input'][0],[1.8,4,-2,0.3126])
    manifest=json.loads(t.Path(r['manifest']).read_text())
    assert manifest['provider_interpolated_rows']==0
    assert 'GSW' in manifest['compatibility_note']


def test_provider_interpolation_opt_in(tmp_path,monkeypatch):
    with pytest.raises(ValueError,match='Interpolated'): prepare(tmp_path,monkeypatch,source(flag=2))
    assert not list(tmp_path.iterdir())
    r=prepare(tmp_path,monkeypatch,source(flag=2),allow_interpolated=True)
    assert json.loads(t.Path(r['manifest']).read_text())['provider_interpolated_rows']==1


@pytest.mark.parametrize('body',[source(bindex=2.1),source(bindex=-1),source(bindex='nan'),source(flag=9),b'<html>error</html>',source()+source(),source().splitlines()[0]+b'\n'])
def test_reject_bad_inputs(tmp_path,monkeypatch,body):
    with pytest.raises(ValueError): prepare(tmp_path,monkeypatch,body,allow_interpolated=True)
    assert not list(tmp_path.iterdir())


def test_field_slots_and_original_equivalence(tmp_path,monkeypatch):
    from gtsimulation.magnetic_field.magnetosphere import Tsyganenko
    date=datetime(2023,1,1,0,30)
    old=Tsyganenko(date,'15B')
    rows=np.zeros(2,dtype=t.DTYPE)
    rows['date']=['2023-01-01T00:30','2023-01-01T00:35']
    rows['T15B_input']=old.parmod
    rows['imf_flag']=rows['sw_flag']=1
    path=tmp_path/'same.npy'; np.save(path,rows)
    with pytest.warns(UserWarning,match='GSW'):
        new=Tsyganenko(date,'15B',input_file=path)
    np.testing.assert_array_equal(new.parmod,old.parmod)
    np.testing.assert_allclose(new.calc_field(2,1,1),old.calc_field(2,1,1),rtol=0,atol=0)
    new.update_state(datetime(2023,1,1,0,39,59))
    before=new.Date
    with pytest.raises(ValueError): new.update_state(datetime(2023,1,1,0,40))
    assert new.Date==before


@pytest.mark.parametrize('start,end', [('2023-01-01T00:31','2023-01-01T00:40'),('2023-01-01','2023-01-01'),('1994-01-01','1994-01-02')])
def test_invalid_boundaries(tmp_path,monkeypatch,start,end):
    monkeypatch.setattr(t,'_download',lambda *args,**kw:pytest.fail('Unexpected download'))
    with pytest.raises(ValueError): t.download_ta15_inputs(start,end,tmp_path)


def test_timezone():
    assert t._boundary('2023-01-01T03:30+03:00')==datetime(2023,1,1,0,30)
