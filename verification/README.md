# Input-data addon verification

Base GT revision: 095dc71b0561cbe19a7ee436f65eda62fc2baff3.
Verified on Windows with Python 3.12.10, numpy 2.5.3, numba 0.67.0.
GT was built with BUILD_GEANT4_COMPONENTS=OFF.

- addon-tests.xml: 51 offline and GT integration cases, JIT disabled, warnings treated as errors.
- addon-tests-jit.xml: the same 51 cases with JIT enabled, warnings treated as errors.
- addon-tests-wheel.xml: 51 cases after installing the built wheel. Integration imports resolve to site-packages. Parser tests load the source module directly.
- live_result.json: real NASA download for 2024-09-10, 24 valid T96 hourly rows, actual field evaluation and a 10-point proton trajectory saved to HDF5. JIT disabled for this live smoke test.
- extended_date_result.json: real T96 drivers and field calculation for 2025-01-02 00:00 UTC, beyond bundled input coverage. Also records the correctly rejected 2025-09-10 00:00 hour with OMNI fill values.

The live/ directory holds source annual files, input arrays, manifests and the
HDF5 smoke result. SHA256 identifies the source bytes and numerical artifacts.
The smoke trajectory checks the data-to-simulation path; it is not a scientific
validation of T96 or a convergence study of the particle pusher.

Offline cases cover Kp bins, T96 order, missing/fill values, UTC conversion,
year boundaries, duplicates, malformed files, bounded retries, timeout exhaustion,
HTTP 404, size limits, write cleanup, concurrent outputs, repeated calls,
unsafe object NPY files, time-range checks, preserved bundled T89/T96/T15B
behavior and matching field results for identical old/new drivers.

## Expanded addon verification

The current addon also prepares T15B and observed NRLMSIS atmospheric inputs.

- addon-expanded-tests.xml: 86 deterministic tests, JIT disabled, warnings as errors.
- addon-expanded-jit.xml: the same 86 tests with JIT enabled.
- addon-expanded-wheel.xml: 86 tests after installation of the built wheel.
  New modules and GT consumers resolve from site-packages. The original OMNI
  parser-only tests still load the source module directly.
- expanded_wheel.json: wheel SHA256 and byte-for-byte equality of the seven
  changed/new runtime modules with source.
- expanded_live_result.json: real CelesTrak download (24 hours), NRLMSIS density
  evaluation, real TA15 download (12 slots), T15B field evaluation, and comparison
  of all 96,104 source records for 2023 with the bundled inputs at float16 precision.
- check_expanded_live.py: rerunnable network smoke check. It saves fresh bundles
  and a report; outages or missing data fail the run rather than being hidden.

The extended deterministic tests include previous-day F107, 57-hour Ap history,
observed/interpolated flags, missing days and slots, corrupted arrays, UTC bounds,
GT's B-index range, pymsis process isolation, default-path preservation,
CLI dispatch/errors, worker timeout cleanup, and matching T15B fields for identical
old/new inputs. Historical v1 reports above are retained as earlier evidence.

## Limits

GT's existing GSM/GSW convention for T15B is preserved and reported, not corrected.
T15B inputs with B-index outside 0..2 are rejected. Atmospheric forecasts are not
accepted. Field coefficient versions are not changed. See the input inventory in
../docs/user_guide/input_inventory.md for the complete scope distinction.

Geant4 execution, all operating systems and all historical periods were not tested.
A short field/medium/trajectory smoke check is not scientific model validation.
Passing this suite does not prove the absence of every possible defect.
