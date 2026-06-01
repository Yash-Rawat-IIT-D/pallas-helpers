# Next-Days TODO Plan

## Summary
Create a planning workspace at `/home/dby/inria/to-do/todo.md` and use it as the single running checklist for the next few days.

Work in this order:

1. Lock a safe, correctness-first semantic policy.
2. Add measurement harnesses for compression ratio, write time, and read time.
3. Extend synthetic benchmarks so they exercise the same grammar shape as the hot `MPI_Test` trace.
4. Only then broaden to event-level policy and new monotone/sampling variants.
5. Move stable benchmarking workflows to the SSH machine last.

The key decision for now is: keep global defaults `None`, make sequence-level `MPI_Test` detection the first semantic override, and defer event-level lossy policy until the sequence-side path is correct and measurable.

## Implementation Plan
### Day 1: Semantic detection and safe policy boundary
- Add a sequence-classification helper in the write path that detects the exact grammar:
  - `SEQUENCE` of two leaf `EVENT`s
  - first record `ENTER`
  - second record `LEAVE`
  - same `RegionRef`
  - resolved region name contains `MPI_Test`
- Use that helper when a sequence is created or first recognized, and set only `sequence.timestamps` to `MonotoneLossy`.
- Keep `sequence.durations` and `sequence.exclusive_durations` on the configured lossless path, with the expected default still `None`.
- Do not change event-level codec selection on Day 1.
- Add temporary debug logging for:
  - detected `MPI_Test` sequence token id
  - chosen encodings for `timestamps`, `durations`, `exclusive_durations`

### Day 2: Benchmark harnesses and observability
- Keep the byte counters already added in storage and standardize the reported metrics:
  - `pre_raw`
  - `raw`
  - `compressed`
  - `effective_ratio`
  - `true_ratio`
- Add a dedicated read benchmark app by copying the read/open flow from `apps/pallas_print.cpp`, but make it:
  - open the trace
  - force traversal/loading of all event and sequence vectors
  - produce no per-record stdout
  - print only final timing totals
- Reuse `test/write_benchmark.c/.cpp` for write-side timing, but add one benchmark mode that generates block-style `ENTER/LEAVE` sequences so it is closer to the `MPI_Test` hot path.
- Record one baseline matrix with defaults `None` before making more codec changes.

### Day 3: Correctness checks and synthetic hot-path generation
- Extend the benchmark generator so it can emit a pseudo `MPI_Test`-failure pattern:
  - repeated `ENTER/LEAVE` of the same region
  - enough iterations to trigger loop/sequence recognition
  - controllable timestamps or logical clock mode
- Use this synthetic case for correctness:
  - verify grammar detection picks the intended sequence only
  - verify decoded sequence timestamps remain monotone
  - verify decoded sequence durations remain unchanged when using lossless modes
- Keep the Python grammar-analysis script as the ground-truth inspection tool for confirming token ids and recursive grammar.

### Day 4: Event-level policy experiment
- Add an experimental event-side rule, but only after the sequence-side policy is stable.
- Scope the first experiment narrowly:
  - if an event definition is `ENTER` or `LEAVE`
  - and its region resolves to `MPI_Test`
  - then allow event timestamp vectors to use an override encoding
- Treat this as region-based, not “failed-poll-only,” and document that limitation clearly.
- Do not attempt retroactive promotion of already-written event subarrays in the first implementation.
- Do not attempt mixed per-occurrence event policies in the current design.

### Day 5+: New monotone/sampling schemes
- Once measurement is stable, add new `MonotoneLossyVariant` schemes in increasing risk order:
  - improved monotone timestamp schemes first
  - duration sampling schemes second
- For each new scheme, require:
  - a deterministic encode/decode rule
  - `can_encode()` boundary behavior
  - error metrics against a `None` baseline trace
  - read/write timing and compression-ratio comparison

### SSH machine phase
- Move to the SSH machine only after:
  - sequence-level policy is correct
  - read/write benchmarks exist
  - one synthetic and one real-trace workflow are repeatable locally
- On SSH, run only larger sweeps:
  - more iterations
  - more threads
  - more codec variants
  - more input parameter combinations

## Public Interfaces and Tooling Changes
- Add one sequence-classification helper in `pallas_write.cpp`; keep it internal, not public API.
- Add one read-benchmark executable alongside existing apps/tests; base it on the `pallas_print` read path but make it silent except for totals.
- Extend `write_benchmark` with one more pattern that mimics repeated block-style `MPI_Test` behavior.
- Keep the Python analysis script as the recursive grammar inspector and result-validation tool.

## Test and Benchmark Plan
- Real-trace checks:
  - confirm the dominant `MPI_Test` sequence grammar still resolves to `ENTER/LEAVE` with the same region
  - confirm only the intended sequence timestamps switch to `MonotoneLossy`
- Synthetic checks:
  - one benchmark with logical clock for deterministic behavior
  - one benchmark with realistic timing noise
- Correctness checks:
  - lossless modes round-trip exactly
  - lossy sequence timestamps remain monotone
  - lossy sequence timestamps do not invert `ENTER`/`LEAVE` timing at the sequence level
- Performance checks:
  - write throughput from `write_benchmark`
  - read throughput from the new silent reader
  - compression ratio from stored byte counters and final file sizes

## Assumptions and Defaults
- Planning file location: `/home/dby/inria/to-do/todo.md`
- Default codec policy remains `None` for both timestamp and duration families.
- First semantic override target is `sequence.timestamps` for detected `MPI_Test` failure sequences.
- Event-level lossy policy is explicitly deferred until after sequence-level correctness and benchmarking are in place.
- No retroactive re-encoding of already-populated event subarrays is planned in the first pass.
