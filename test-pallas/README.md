# `mpi_test_spinloop`

This directory contains a small two-rank MPI microbenchmark that generates many repeated `MPI_Test` calls.

## What it tests

Rank 1 posts an `MPI_Irecv`, then repeatedly calls `MPI_Test` until the receive completes. Rank 0 waits for a configurable delay, then sends the message. Repeating this pattern many times creates a trace with a large number of `MPI_Test` events.

## Why this is relevant

This benchmark is meant for manual trace inspection when checking the hypothesis that repeated `MPI_Test` structure may remain simple or compressible, while timestamp or time-series metadata in the generated Pallas trace may still grow substantially with the number of polls.

That hypothesis is still uncertain here: this benchmark only produces the event pattern and leaves trace-size interpretation to manual inspection.

## Files

- `mpi_test_spinloop.c`: benchmark source
- `Makefile`: optional convenience build target

## Compile

Directly:

```sh
mpicc -O2 -g mpi_test_spinloop.c -o mpi_test_spinloop
```

With `make`:

```sh
make
```

## Run

```sh
mpirun -np 2 ./mpi_test_spinloop
mpirun -np 2 ./mpi_test_spinloop 1000 100 4
mpirun -np 2 ./mpi_test_spinloop 10000 100 4
mpirun -np 2 ./mpi_test_spinloop 10000 1000 4
```

Arguments:

1. `iterations` (default `1000`)
2. `delay_us` (default `100`)
3. `payload_bytes` (default `4`)

## Output

The program prints minimal parseable stats:

- `rank`
- `iterations`
- `delay_us`
- `payload_bytes`
- `total_polls` on rank 1
- `avg_polls_per_iter` on rank 1

## Suggested workflow

Build the benchmark, run it under the tracing/profiling flow already documented elsewhere in this repository, and compare generated trace sizes across different parameter settings.

This README intentionally does not invent exact EZTrace or Pallas commands. Use the existing repository documentation for the tracing workflow.

## Switching subarray encoding between runs

Pallas reads its runtime config when a new trace is written, so you can change the subarray encoding between runs without rebuilding.

Temporary override for one shell:

```sh
source ~/inria/env-pallas-eztrace.sh
export PALLAS_SUBARRAY_ENCODING=None
mpirun -np 2 ./mpi_test_spinloop 10000 100 4

export PALLAS_SUBARRAY_ENCODING=Delta2Enc
mpirun -np 2 ./mpi_test_spinloop 10000 100 4

export PALLAS_SUBARRAY_ENCODING=Delta2EncVint
mpirun -np 2 ./mpi_test_spinloop 10000 100 4
```

Persistent change through the config file:

1. Edit `pallas/libraries/pallas/pallas.config` and change `subArrayEncoding=...`
2. Reinstall Pallas if needed so the installed config is updated
3. Run again from a fresh shell, or unset `PALLAS_SUBARRAY_ENCODING` if you previously exported it

Accepted values:

- `None`
- `Delta2Enc`
- `Delta2EncVint`
- `TestLossyGenerator`

## Suggested manual experiment matrix

- `iterations`: `100`, `1000`, `10000`, `100000`
- `delay_us`: `0`, `10`, `100`, `1000`
- `payload_bytes`: `4`, `1024`

## Expected observation if the hypothesis is correct

- repeated `MPI_Test` event structure may remain simple or compressible
- trace timing metadata may still grow significantly
- final trace size may grow strongly with the number of polls

## Limitations

- this is a synthetic microbenchmark
- `MPI_Test` poll count depends on machine speed, MPI implementation, and delay behavior
- this does not isolate timestamp buffer size internally
- this is for manual trace-size inspection only
