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

This version supports T89/T96. T15B inputs require a separate source and
interpretation. Gauss coefficient updates, IRI and atmospheric F10.7/Ap
preparation require separate implementations. GTnrlmsis already uses pymsis
for F10.7/Ap. OMNI availability does not extend the validity of IGRF or other
coefficients used by GT. Model validity must also be respected.

References and verification
---------------------------

NASA OMNI2 field definitions and fill values:
https://omniweb.gsfc.nasa.gov/html/ow_data.html

NASA annual files:
https://spdf.gsfc.nasa.gov/pub/data/omni/low_res_omni/

T89 bins and T96 parameter order follow GT Functions/t89.py and Functions/t96.py.

.. code-block:: console

   python -m pytest tests/test_input_data.py tests/test_input_data_integration.py

Integration checks use actual field classes and a short proton trajectory
written to HDF5. They require an installed GT build; Geant4 is optional.
A live NASA download is an additional network-dependent check.
