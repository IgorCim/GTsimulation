from datetime import datetime, timezone
from pathlib import Path
import numpy as np

from gtsimulation.common import Units, Regions
from gtsimulation.magnetic_field import AbsBfield
from gtsimulation.magnetic_field.magnetosphere.Functions import transformations, t89, t96, t15B
from ._gauss import load_earth_reference


class Tsyganenko(AbsBfield):
    """
    Tsyganenko empirical magnetospheric magnetic field model (T89/T96).

    This class provides an interface to compute the magnetic field components
    in the Earth's magnetosphere using the Tsyganenko empirical models (T89 or T96).
    The model type is selected via the `ModCode` parameter.

    :param date: Date for model initialization (default: 2000-01-01)
    :type date: datetime.datetime
    :param ModCode: Model version selector (89, 96, 15B)
    :type ModCode: str
    :param input_file: Optional prepared inputs.npy for T89/T96/T15B. Uses the
        containing UTC hour (T89/T96) or five-minute slot (T15B) and rejects
        dates outside the supplied interval. T15B retains the existing GT
        GSM/GSW convention and emits a compatibility warning.
        Without this option, bundled data selection is preserved.
    :raises ValueError: If date is outside model's valid range
    """
    to_meters = Units.RE2m

    def __init__(self, date: datetime = datetime(2000, 1, 1), ModCode="96", *, input_file=None):
        super().__init__()
        self.ModelName = "Tsyganenko"
        self.Region = Regions.Magnetosphere
        self.mod_code = str(ModCode)
        self._external_inputs = input_file is not None
        self.T_input = None
        if self._external_inputs:
            from gtsimulation.input_data.omni import load_inputs
            if self.mod_code == "15B":
                import warnings
                from gtsimulation.input_data.ta15 import load_ta15_inputs, COMPATIBILITY
                warnings.warn(COMPATIBILITY, UserWarning, stacklevel=2)
                self.T_input = load_ta15_inputs(input_file)
            else:
                self.T_input = load_inputs(input_file, self.mod_code)
        elif self.mod_code == '15B':
            self.T_input = np.load(Path(__file__).resolve().parent.joinpath("Data", "T_input15B_short.npy"))
        elif self.mod_code in ["89", "96"]:
            self.T_input = np.load(Path(__file__).resolve().parent.joinpath("Data", "T_input_short.npy"))
        else:
            raise ValueError("ModCode must take one of the values '89', '96', '15B'.")
        if self._external_inputs:
            date = self._external_date(date)
        if not self._external_inputs and not self.T_input['date'][0] <= date <= self.T_input['date'][-1]:
            raise ValueError(f"Input date must be between {self.T_input['date'][0]} and {self.T_input['date'][-1]}.")
        self.Date = date
        self.__set_psi_ind()

    def __set_psi_ind(self):
        self.year = self.Date.year
        self.doy = self.Date.timetuple().tm_yday
        self.sec = self.Date.second + 60 * self.Date.minute + 3600 * self.Date.hour
        self.DTnum = self.Date.toordinal()  # + 366
        self.ps = self._get_psi()
        self.parmod = self._get_ind()

    def _get_psi(self):
        self.g, self.h = load_earth_reference(self.Date)

        # Direction of the centered geomagnetic dipole in GEO
        dipole_geo = transformations.get_dipole_direction(
            self.g, self.h
        )

        # Transform dipole direction GEO -> GSM
        x, _, _ = transformations.geo2gsm(
            dipole_geo[0],
            dipole_geo[1],
            dipole_geo[2],
            self.year,
            self.doy,
            self.sec,
            self.g,
            self.h
        )

        # In GSM coordinates: D_x = sin(psi)
        psi = np.arcsin(np.clip(x, -1.0, 1.0))

        return psi

    def _get_ind(self):
        if self._external_inputs:
            ia = np.searchsorted(self.T_input['date'], np.datetime64(self.Date), side="right") - 1
        else:
            ia = np.argmax(self.T_input['date'] >= self.Date)
        match self.mod_code:
            case "89":
                return self.T_input['T89_input'][ia]
            case "96":
                return self.T_input['T96_input'][ia].astype(np.float32)
            case "15B":
                return self.T_input["T15B_input"][ia].astype(np.float32)
            case _:
                return None

    def calc_field(self, x, y, z):
        X, Y, Z = transformations.geo2gsm(x, y, z, self.year, self.doy, self.sec, self.g, self.h)
        Bx, By, Bz = 0, 0, 0
        if self.mod_code == "89":
            Bx, By, Bz = t89.t89(self.parmod, self.ps, X, Y, Z)
        elif self.mod_code == "96":
            Bx, By, Bz = t96.t96(self.parmod, self.ps, X, Y, Z)
        elif self.mod_code == "15B":
            Bx, By, Bz = t15B.t15B(self.parmod, self.ps, X, Y, Z)

        Bx, By, Bz = transformations.geo2gsm(Bx, By, Bz, self.year, self.doy, self.sec, self.g, self.h, inverse=True)
        return Bx, By, Bz

    def _external_date(self, date):
        if date.tzinfo is not None:
            date = date.astimezone(timezone.utc).replace(tzinfo=None)
        stamp = np.datetime64(date)
        step = np.timedelta64(5, "m") if self.mod_code == "15B" else np.timedelta64(1, "h")
        end = self.T_input["date"][-1] + step
        if not self.T_input["date"][0] <= stamp < end:
            raise ValueError("Date outside the external input interval.")
        return date

    def update_state(self, new_date):
        if self._external_inputs:
            new_date = self._external_date(new_date)
        self.Date = new_date
        self.__set_psi_ind()

    def __str__(self):
        return (
            "Tsyganenko\n"
            f"\tMode: {self.mod_code}\n"
            f"\tPsi: {self.ps}"
        )
