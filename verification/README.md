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

## Current scope

T89/T96 hourly OMNI inputs are implemented. T15B, Gauss coefficient updates,
IRI and atmospheric input preparation are not part of this first version.
The repository's existing Geant4 interaction benchmarks, all operating systems
and all historical OMNI periods have not been exercised in this verification.
