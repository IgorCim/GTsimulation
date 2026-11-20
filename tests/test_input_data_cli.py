"""CLI routes and failure reporting, with no network calls."""
import json
import subprocess
import pytest
from gtsimulation.input_data import __main__ as cli


@pytest.mark.parametrize('model,function',[('89','download_tsyganenko_inputs'),('96','download_tsyganenko_inputs'),('15B','download_ta15_inputs'),('nrlmsis','download_atmosphere_inputs')])
def test_cli_dispatch(monkeypatch,capsys,model,function):
    seen=[]
    def fake(*args,**kwargs): seen.append((args,kwargs));return {'model':model,'rows':24}
    monkeypatch.setattr(cli,function,fake)
    monkeypatch.setattr('sys.argv',['input_data','--model',model,'--start','2024-09-10','--end','2024-09-11','--output-dir','inputs'])
    cli.main()
    assert json.loads(capsys.readouterr().out)=={'model':model,'rows':24}
    assert len(seen)==1 and seen[0][0]==('2024-09-10','2024-09-11','inputs')


def test_cli_bad_option(monkeypatch,capsys):
    monkeypatch.setattr('sys.argv',['input_data','--model','96','--start','2024-09-10','--end','2024-09-11','--output-dir','inputs','--allow-provider-interpolation'])
    with pytest.raises(SystemExit) as e: cli.main()
    assert e.value.code==2


def test_cli_worker_timeout(monkeypatch,capsys):
    def fail(*args): raise subprocess.TimeoutExpired('worker',120)
    monkeypatch.setattr(cli,'download_atmosphere_inputs',fail)
    monkeypatch.setattr('sys.argv',['input_data','--model','nrlmsis','--start','2024-09-10','--end','2024-09-11','--output-dir','inputs'])
    with pytest.raises(SystemExit) as e: cli.main()
    assert e.value.code==1 and 'Input preparation failed' in capsys.readouterr().err
