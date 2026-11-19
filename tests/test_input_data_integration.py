"""Integration with the actual GT field and particle pusher."""
from datetime import datetime, timezone, timedelta
from pathlib import Path
import numpy as np
import pytest
from gtsimulation.magnetic_field.magnetosphere import Tsyganenko
from gtsimulation.input_data.omni import DTYPE


@pytest.fixture
def input_file(tmp_path):
    rows = np.zeros(2, dtype=DTYPE)
    rows["date"] = ["2024-09-10T00", "2024-09-10T01"]
    rows["T89_input"] = [2, 4]
    rows["T96_input"] = [[2, -20, 1, -2], [3, -30, 2, -3]]
    path = tmp_path / "drivers.npy"
    np.save(path, rows)
    return path


@pytest.mark.parametrize("model", ["89", "96"])
def test_external_time_and_field(input_file, model):
    field = Tsyganenko(datetime(2024,9,10,0,30), model, input_file=input_file)
    expected = 2 if model == "89" else [2,-20,1,-2]
    np.testing.assert_array_equal(field.parmod, expected)
    assert np.all(np.isfinite(field.calc_field(2, 1, 1)))
    field.update_state(datetime(2024,9,10,1,59,59))
    np.testing.assert_array_equal(field.parmod, 4 if model == "89" else [3,-30,2,-3])
    before = field.Date
    with pytest.raises(ValueError): field.update_state(datetime(2024,9,10,2))
    assert field.Date == before


def test_timezone(input_file):
    field = Tsyganenko(datetime(2024,9,10,3,30,tzinfo=timezone(timedelta(hours=3))),
                      "89",input_file=input_file)
    assert field.Date == datetime(2024,9,10,0,30)
    assert field.parmod == 2


@pytest.mark.parametrize("model", ["89", "96", "15B"])
def test_existing_bundled_inputs(model):
    field = Tsyganenko(datetime(2008,1,1,1),model)
    index = np.argmax(field.T_input["date"] >= field.Date)
    column = {"89":"T89_input","96":"T96_input","15B":"T15B_input"}[model]
    np.testing.assert_allclose(field.parmod, field.T_input[column][index])
    assert np.all(np.isfinite(field.calc_field(2,1,1)))


def test_short_trajectory(input_file,tmp_path):
    import h5py
    from gtsimulation.common import Units
    from gtsimulation.particle import Flux, generator
    from gtsimulation.pusher import BunemanBorisSimulator
    particle = Flux(
        Spectrum=generator.spectrum.Monolines(energy=Units.GeV),
        Distribution=generator.distribution.UserInput(R0=[2*Units.RE,0,0],V0=[0,1,0]),
        Names="proton",Nevents=1,
    )
    output = tmp_path / "trajectory.h5"
    sim = BunemanBorisSimulator(
        Particles=particle, Num=10, Step=1e-6,
        Bfield=Tsyganenko(datetime(2024,9,10),"96",input_file=input_file),
        Date=datetime(2024,9,10), Output=str(output), Verbose=0,
    )
    sim()
    with h5py.File(output) as f:
        coordinates=f["events/0/Track/Coordinates"][:]
        assert len(coordinates)>0
        assert np.all(np.isfinite(coordinates))


@pytest.mark.parametrize("model",["89","96"])
def test_same_drivers_same_field_as_bundled(tmp_path,model):
    date=datetime(2008,1,1,1)
    original=Tsyganenko(date,model)
    i=np.argmax(original.T_input["date"] >= date)
    path=tmp_path/"same.npy"
    np.save(path,original.T_input[i:i+2])
    external=Tsyganenko(date,model,input_file=path)
    np.testing.assert_allclose(external.calc_field(2,1,1),original.calc_field(2,1,1),rtol=1e-12,atol=1e-12)
