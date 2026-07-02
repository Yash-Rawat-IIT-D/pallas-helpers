# NPB Benchmark Layout

This directory mirrors the existing `test-pallas` runner/matrix setup for the
NAS Parallel Benchmarks MPI suite.

Each benchmark lives in its own subdirectory:

- `bt`
- `cg`
- `dt`
- `ep`
- `ft`
- `is`
- `lu`
- `mg`
- `sp`

Inside each benchmark directory:

- `matrix.json` contains the Pallas storage-policy matrix for that benchmark.
- `runner_<CLASS>.json` targets one NPB class binary such as `S`, `W`, `A`,
  `B`, `C`, `D`, `E`, or `F`.

Notes:

- `dt` only has `S/W/A/B/C/D` runners because NPB does not define `E/F` there.
- `is` only has `S/W/A/B/C/D/E` runners because NPB does not define `F` there.
- The generated runners default to `jobs=4`, which is valid for both the
  square-grid kernels (`bt`, `sp`) and the power-of-two kernels.

Example:

```bash
cd /home/dby/inria/test-pallas
./run_benchmark.py nasp/mg/runner_A.json
```
