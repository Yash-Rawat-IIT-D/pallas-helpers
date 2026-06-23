# New LinkedVector Handoff

This note is a handoff for the standalone LinkedVector refactor that replaced
the old nested `LinkedTimeVector` / `LinkedDurationVector` path.

The goal of the refactor was to move policy-dependent behavior out of the old
legacy vector implementation and into a cleaner `LV -> SubArray -> Manager`
stack.

## Active Path

The active implementation now lives in:

- `pallas/libraries/pallas/include/pallas/utils/pallas_lv.h`
- `pallas/libraries/pallas/src/pallas_lv.cpp`
- `pallas/libraries/pallas/include/pallas/utils/pallas_subarray.h`
- `pallas/libraries/pallas/src/pallas_subarray.cpp`
- `pallas/libraries/pallas/src/pallas_storage.cpp`
- `pallas/libraries/pallas/src/pallas_write.cpp`

The old files still exist but are no longer the intended development path:

- `pallas/libraries/pallas/include/pallas/utils/pallas_linked_vector.h`
- `pallas/libraries/pallas/src/pallas_linked_vector.cpp`

Those legacy files were intentionally left in the tree for reference only.
They should not be the place for new work.

## Short History

Older refactor work focused on:

- splitting the linked-vector layer from the old nested subarray hierarchy
- introducing standalone `TimeLV` / `DurationLV`
- moving storage/read/write logic into the new LV + SubArray path
- replacing old encoding naming with `StoragePolicy`
- updating Python wrappers and analysis helpers to use the new LV types

That part is mostly done. The newer work has been around online policy-aware
managers, especially Delta and timestamp Lossy.

## Current Design

The current stack is:

- `TimeLV` / `DurationLV`
- one linked list of `SubArrayBase` children
- one `Manager` per subarray, chosen from `(ValueDomain, StoragePolicy)`

The key enums in the active path are:

- `ValueDomain`: `Timestamp`, `Duration`
- `StoragePolicy`: `None`, `Delta`, `Lossy`
- `LossyPolicy`: `Linear`, `NormalSample`
- `SubArrayPhase`: `RuntimeWrite`, `AnalysisRead`

Important semantics:

- `size()` means logical number of represented values
- `mem_size()` means number of physical `uint64_t` payload words
- `allocated_count` is capacity in `uint64_t` words
- `physical_size` is the used payload size in `uint64_t` words
- each subarray stores `starting_index` and `file_offset`
- managers operate on caller-owned subarray storage instead of owning the data

## What Is Implemented

### LV Layer

`LVBase` now provides:

- linked-list ownership of standalone subarrays
- `at()` / `operator[]` access through subarray lookup
- `as_flat_array()`
- `free_data()`
- `load_all_data()`
- `getSubArrayPolicies()`
- `getLoadedSubArrayPolicies()`
- `apply_preferred_policy_now()`

There is also a small L1 recent-value cache:

- `RecentValueRingBuffer`
- capacity is `64`
- stores `(logical_index, value)` pairs
- used by LV lookup before touching subarrays

`operator[]` is the path that handles cache lookup, on-demand load, and memory
pressure eviction. `at()` validates bounds and delegates to `operator[]`.

### SubArray Layer

`SubArrayBase` now stores the shared runtime state:

- logical size
- physical payload size
- allocated payload size
- file offset
- starting logical index
- linked-list prev/next pointers
- `uint64_t* values`
- `StoragePolicy`
- `SubArrayPhase`
- one `std::unique_ptr<Manager>`

Subarray headers are split into:

- common header written by `SubArrayBase::write_common_header()`
- time-specific header in `TimeSubArray::write_header()`
- duration-specific header in `DurationSubArray::write_header()`

The common header currently stores:

- logical size
- stored policy
- physical payload size
- subarray data offset

`TimeSubArray` stores exact:

- first timestamp
- last timestamp

`DurationSubArray` stores exact:

- min duration
- max duration
- mean duration

### Storage / Read / Write

The new write/read path is wired through `pallas_storage.cpp`.

Important points:

- `TimeLV::write_header()` and `DurationLV::write_header()` write vector-level metadata
- each subarray calls `write_data()` first, then `write_header()`
- data offset is captured from the data file before header metadata is written
- managers are responsible for writing/loading their payload representation
- `_pallas_compress_write()` and `_pallas_compress_read()` are used by the new path

On read:

- LV constructors rebuild the linked list of subarrays from metadata
- subarrays are constructed in `AnalysisRead` phase
- payload data is loaded lazily through `LVBase::load_data()`

## Managers

### NoneManager

This is the baseline implementation.

Behavior:

- values are stored raw in the subarray `uint64_t[]`
- add succeeds until `physical_size == allocated_count`
- `mem_size()` tracks used raw words
- `write_data()` writes `mem_size()` words
- `load_data()` loads `mem_size()` words

This path preserves exact values and is the simplest correctness baseline.

### TimeDeltaManager

This is the current online delta manager for timestamps.

Encoding:

- first value stored raw as varint
- second value stored as positive delta
- later values stored as delta-of-delta
- delta-of-delta uses zigzag
- packets use LEB128-style varints

Runtime behavior:

- data is packed directly into the subarray `uint64_t[]` payload buffer
- `payload_bytes` tracks byte usage in memory
- `physical_size` is updated from used payload bytes
- `recommended_capacity()` currently returns `DEFAULT_VECTOR_SIZE`

Access behavior:

- runtime write phase keeps packed payload and decodes on demand
- `at()` uses sparse checkpoints plus forward decode
- `copy_to_array()` can materialize logical values by full decode
- analysis-read phase currently decodes eagerly to a flat logical array on load

Checkpoint state:

- stride is `50`
- checkpoint stores logical index
- checkpoint stores byte offset
- checkpoint stores decoded value
- checkpoint stores previous delta

### DurationDeltaManager

This mirrors `TimeDeltaManager`, but handles signed duration deltas.

Encoding:

- first value stored raw
- second value stores signed delta via zigzag
- later values store signed delta-of-delta via zigzag

Runtime and read behavior follow the same broad shape as timestamp delta:

- packed payload during runtime write
- sparse-checkpoint decode for `at()`
- eager decode to flat logical values in analysis-read load path

Duration stats are updated only when a value is actually accepted into the
subarray.

### LinearTimeManager

This is the current timestamp lossy prototype.

It is intentionally narrow:

- only used for timestamp `StoragePolicy::Lossy`
- only supports `LossyPolicy::Linear`
- duration lossy is not implemented yet
- duration lossy currently falls back to Delta

Current representation:

- first `16` timestamps are used as seed values
- once the seed window is full, the manager fits a line
- after model activation, `values[0]` stores slope bytes
- after model activation, `values[1]` stores anchor value
- remaining payload slots store explicit outlier pairs:
  - logical index
  - exact value

Current limits:

- outlier capacity is `8`
- representative payload capacity is `2 + 2 * 8`
- if outlier capacity is exhausted, manager returns `AddStatus::Outlier`
- LV then rolls to a fresh subarray and retries there

Current prediction model:

- OLS slope over the seed values
- anchor is the first value
- prediction is `anchor + slope * logical_index`
- non-model mode still serves reads through prediction-from-fit

Important note:

- this implementation is functional enough for experimentation
- it is not yet a good compression scheme for the observed `MPI_Test` traces

## Hot-Loop Promotion

Hot-loop policy switching was reintroduced in `pallas_write.cpp` using the new
LV/subarray policy model.

Current behavior:

- only checks simple 2-token enter/leave sequences
- decision is made exactly once when loop iterations hit `64`
- window size is `RecentValueRingBuffer::kCapacity`
- promotion condition is currently:
  - more than 75% of the last 64 durations are `<= 350 ns`

On promotion:

- sequence timestamp LV preferred policy becomes `Lossy`
- sequence duration LV preferred policy becomes `Delta`
- sequence exclusive-duration LV preferred policy becomes `Delta`
- underlying event timestamp LVs are also switched to `Lossy`
- `apply_preferred_policy_now()` is used so the new policy takes effect
  immediately rather than waiting for natural rollover

Testing override:

- `overrideLoopDetection=true` disables this promotion logic
- it is meant for testing policy behavior, not for disabling the whole writer

## Config / ParameterHandler State

The config file and parameter handler were simplified around policy-based
naming.

Important fields now are:

- `storagePolicy`
- `timeLossyPolicy`
- `durationLossyPolicy`
- `timeLinearEpsilon`
- `overrideLoopDetection`

Current default example from `pallas.config`:

- `storagePolicy=None`
- `timeLossyPolicy=Linear`
- `durationLossyPolicy=NormalSample`
- `timeLinearEpsilon=64`

Current behavior caveat:

- `StoragePolicy::Lossy` on durations is intentionally treated as Delta for now

## Python / Tooling Status

Python wrappers were already moved to the new LV path earlier.

Useful scripts in `test-pallas`:

- `analyse_spinloop_trace.py`
- `view_spinloop_blocks.py`

These were used to inspect the new online timestamp/duration behavior,
especially for the `MPI_Test` spinloop traces.

The newer trace-analysis tooling can:

- print large-vector summaries
- show subarray counts and average subarray sizes
- inspect policy distributions
- inspect sequence `3` in spinloop traces
- show timestamp blocks interactively with Bokeh
- plot delta and delta-of-delta behavior

## What We Observed Recently

The main recent observation is that the current Linear timestamp scheme is too
fragile for the failed `MPI_Test` traces.

Observed shape:

- timestamps are mostly monotone
- local windows often look like a few line segments
- timestamp deltas have a stable baseline plus spikes
- the current linear seed + small outlier buffer overflows too quickly

Observed consequence:

- promoted timestamp subarrays often stay very small
- compression gains are eaten by frequent rollover
- Delta on durations performs much better than current Linear on timestamps

The analysis work strongly suggests that future lossy work should be more
segment-oriented or delta-oriented rather than relying on one tiny affine model
with a very small outlier budget.

## Known Caveats

- `LinearTimeManager` is prototype quality, not final
- duration lossy is not implemented; the active fallback is Delta
- analysis-read for Delta currently eagerly decodes into flat arrays
- runtime write for Delta keeps packed payload and decodes on demand
- the legacy linked-vector files still exist and can confuse code searches
- malformed old traces may still emit the historical mean-duration warning

## Good Files To Read First

If someone is resuming the work, the best starting order is:

1. `pallas/libraries/pallas/include/pallas/utils/pallas_lv.h`
2. `pallas/libraries/pallas/src/pallas_lv.cpp`
3. `pallas/libraries/pallas/include/pallas/utils/pallas_subarray.h`
4. `pallas/libraries/pallas/src/pallas_subarray.cpp`
5. `pallas/libraries/pallas/src/pallas_storage.cpp`
6. `pallas/libraries/pallas/src/pallas_write.cpp`
7. `test-pallas/analyse_spinloop_trace.py`
8. `test-pallas/view_spinloop_blocks.py`

## Safe Next Steps

The safest next steps are:

- keep `NoneManager`, `TimeDeltaManager`, and `DurationDeltaManager` as the
  correctness baseline
- treat `LinearTimeManager` as an experimental timestamp path
- continue using the spinloop analysis scripts to study full-window timestamp
  delta behavior
- design the next lossy timestamp manager around better segment/delta models
  rather than just tuning `timeLinearEpsilon`

If new lossy work starts, it should be built on the current standalone
`TimeLV` / `DurationLV` + `SubArrayBase` + `Manager` stack, not on the old
legacy linked-vector code.
