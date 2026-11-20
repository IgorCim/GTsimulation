External input data
===================

The input-data module downloads hourly NASA SPDF OMNI2 drivers for T89/T96
into a new bundle in a user-selected directory.

.. code-block:: console

   python -m gtsimulation.input_data --start 2024-09-10 --end 2024-09-11 --model 96 --output-dir inputs

The command prints JSON with input_file, manifest, rows and model. Errors
return a nonzero exit code. Python callers use the same operation:

.. code-block:: python

   from datetime import datetime
   from gtsimulation.input_data import download_tsyganenko_inputs
   from gtsimulation.magnetic_field.magnetosphere import Tsyganenko

   prepared = download_tsyganenko_inputs(
       "2024-09-10", "2024-09-11", "inputs", model="96"
   )
   field = Tsyganenko(datetime(2024, 9, 10, 12, 30), ModCode="96",
                      input_file=prepared["input_file"])
   print(field.calc_field(2, 1, 1))

The input file can be reused offline. Each download creates a new bundle;
repeated downloads can reflect provider revisions. No implicit cache is used.

Data contract
-------------

* Naive dates are UTC. Zoned boundaries are converted to UTC. Boundaries must
  be whole hours. The interval is [start, end), at most 366 days, from 1963.
* Each OMNI2 record is a one-hour average labelled by its interval start.
  With input_file, GT uses the containing hour and rejects dates outside
  the interval. No interpolation, extrapolation or extra time shift is applied.
  Existing constructor calls continue to use bundled data with their original
  selection behavior.
* T89 converts OMNI Kp multiplied by ten into the seven model activity bins.
  Kp retains its original three-hour resolution.
* T96 uses published flow pressure (nPa), Dst (nT), By GSM and Bz GSM (nT),
  in that order. Pressure is taken directly from OMNI.
* Missing hours, fill values, nonfinite or invalid drivers fail preparation
  for the selected model. Unavailable drivers for the other model remain
  marked invalid and are rejected if loaded for that model.
* Numeric NPY input is loaded with allow_pickle=False. T96 values are float64.
* The manifest records source URLs, retrieval time, interval, units, GSM and
  SHA256 hashes. Original annual responses are retained. An incomplete bundle
  is removed after a handled write failure.
* Publication status is not inferred. OMNI values can be revised. Saved
  source bytes and hashes identify the data actually used.

Scope
-----

This addon supports T89/T96, T15B and observed NRLMSIS atmospheric inputs.
It does not update coefficient versions or enable inactive GT models.
Detailed source-specific contracts are below.

References and verification
---------------------------

NASA OMNI2 field definitions and fill values:
https://omniweb.gsfc.nasa.gov/html/ow_data.html

NASA annual files:
https://spdf.gsfc.nasa.gov/pub/data/omni/low_res_omni/

T89 bins and T96 parameter order follow GT Functions/t89.py and Functions/t96.py.

.. code-block:: console

   python -m pytest tests/test_input_data.py tests/test_input_data_integration.py tests/test_atmosphere_inputs.py tests/test_ta15_inputs.py

Integration checks use actual field classes and a short proton trajectory
written to HDF5. They require an installed GT build; Geant4 is optional.
A live NASA download is an additional network-dependent check.

TA15 B-index inputs
------------------

.. code-block:: console

   python -m gtsimulation.input_data --model 15B --start 2023-01-01T00:30 --end 2023-01-01T01:30 --allow-provider-interpolation --output-dir inputs

The explicit interpolation option accepts the provider's quality flag 2. Without
it, both IMF and solar-wind flags must be 1 (observed). The addon never fills gaps.
All five-minute slots must exist. B-index must be in GT's supported 0..2 range.
Pass the returned input_file to Tsyganenko(..., ModCode="15B", input_file=...).

The official source's IMF is GSW and is averaged over a trailing 30-minute window.
GT currently uses GSM positions/tilt with these same drivers. The addon preserves
this existing convention and emits a compatibility warning; it does not implement
a new GSW transformation. Source quality flags and the limitation are saved in the
manifest. Source: https://geo.phys.spbu.ru/~tsyganenko/empirical-models/magnetic_field/ta15/

Atmospheric inputs
------------------

.. code-block:: console

   python -m gtsimulation.input_data --model nrlmsis --start 2024-09-10 --end 2024-09-11 --output-dir inputs

.. code-block:: python

   from datetime import datetime
   from gtsimulation.input_data import download_atmosphere_inputs
   from gtsimulation.medium.magnetosphere import GTnrlmsis

   prepared = download_atmosphere_inputs("2024-09-10", "2024-09-11", "inputs")
   medium = GTnrlmsis(datetime(2024, 9, 10), input_file=prepared["input_file"])
   medium.calculate_model(6478137, 0, 0)
   print(medium.get_density())  # kg/m3

The numeric bundle works offline and does not change global pymsis configuration.
Daily F10.7/F10.7a and Ap plus three-hourly ap history are prepared using pymsis,
without interpolation. Hourly storage does not create new hourly measurements.
Only observed provider rows with complete preceding history are accepted.
F10.7 is in sfu; Ap/ap are indices. The API retains GT's existing atmosphere
settings, including the geomagnetic-activity mode; it does not change model physics.

For callers such as GT's Geant4 atmospheric helpers, the returned
space_weather_file can be selected explicitly using
pymsis.utils.use_space_weather_file(prepared["space_weather_file"]). This changes
pymsis configuration for the process; do it before starting concurrent calculations.
The addon never does this in the parent process automatically. Geant4 execution
was not tested in this environment.

Source: https://celestrak.org/SpaceData/

Input coverage inventory
------------------------

See input_inventory.md in this directory for all audited input families, including
bundled coefficients, generated turbulence, and the disabled IRI module.
Downloading new drivers does not extend the validity of bundled field coefficients.
