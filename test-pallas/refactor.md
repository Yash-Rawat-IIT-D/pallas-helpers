# LinkedVector V1 Refactor Plan

## Context

This document captures the planned V1 refactor of:

- `pallas/libraries/pallas/include/pallas/utils/pallas_linked_vector.h`
- `pallas/libraries/pallas/src/pallas_linked_vector.cpp`

The goal is not a cosmetic cleanup. The main objective is to change the storage model so that encoded / predicted representations can influence the in-memory representation earlier, instead of only being applied during the final storage step.

## Current Problem

Today, `SubArrayCodec` is mostly applied at storage time:

1. the vector accumulates raw values in memory
2. the subarray keeps the full `NoneCodec`-style payload in RAM
3. only when writing to file do we call the codec and reduce the representation

This means:

- runtime memory usage still resembles the `NoneCodec` case
- trend-aware encodings only help at the very end
- predictors and codecs are too tightly coupled to storage-time behavior

For timestamps this is partially acceptable because monotone order gives structure “for free”.
For durations this is much weaker, because the values are not naturally ordered in the same way.

## High-Level Refactor Direction

The V1 direction is:

- introduce a common base class for linked-vector behavior
- split timestamp and duration implementations more explicitly
- separate **prediction/trend detection** from **codec serialization**
- allow a vector/subarray to move between:
  - a raw / `None` accumulation state
  - a codec / predicted state

The long-term idea is that once a pattern is detected, the in-memory representation itself can become smaller and more structured, rather than waiting until file output.

## Main Refactor Themes

### 1. Common base classes

Introduce:

- a common base class for the vector
- a common base class for the subarray

And derive concrete specializations:

- `LinkedVectorTimeStamp`
- `LinkedVectorDuration`
- `SubArrayTimeStamp`
- `SubArrayDuration`

Expected benefit:

- shared behavior can move to a base layer
- timestamp-specific and duration-specific logic can stop leaking into each other
- future codecs/predictors can target the correct domain more cleanly

### 2. Explicit domain tagging

Introduce an explicit enum or tag to represent the semantic domain:

- `Timestamp`
- `Duration`

The current expectation is:

- the tag does not necessarily need to be stored as owned mutable state inside every vector or subarray
- but it should be easy to pass through the relevant layers

Expected benefit:

- codec and predictor code can switch on a clean semantic notion instead of relying on ad hoc type assumptions
- duration-vs-timestamp behavior becomes explicit and easier to extend

### 3. Predictor and codec separation

The codec should not be responsible for deciding whether a trend exists.

Instead:

- a **Predictor** decides whether incoming values follow a useful pattern
- the **Codec** is responsible only for representing / serializing the chosen state

Expected benefit:

- cleaner responsibilities
- easier experimentation with multiple predictors on top of the same codec
- easier implementation of duration-specific logic, where ordering assumptions are weaker

### 4. Stateful subarray representation

Each vector/subarray should conceptually support at least two states:

- `NoneState`
  - raw values are accumulated directly
- `CodecState`
  - only the reduced predictor/codec representation is maintained

Transition idea:

1. subarray starts in `NoneState`
2. enough values are observed
3. predictor detects a stable trend
4. subarray transitions to `CodecState`
5. if the trend breaks badly enough, either:
   - fall back to `NoneState`, or
   - terminate the current subarray and start a new one

This part is still design-heavy and should be resolved incrementally.

## Proposed Implementation Plan

### Phase 0. Stabilize terminology and invariants

Before code movement:

- define the exact meaning of:
  - vector
  - subarray
  - codec
  - predictor
  - `NoneState`
  - `CodecState`
- define what must remain true for:
  - append
  - load
  - storage
  - decode
  - statistics (`min`, `max`, `mean`, etc.)

Deliverable:

- a small design note or comments documenting the state model and naming

### Phase 1. Introduce domain tags

Add the semantic domain tag first, before large hierarchy changes.

Tasks:

- define the timestamp/duration tag enum
- thread that tag through the places where codec or predictor behavior will need it
- avoid large ownership refactors at this stage

Why first:

- this is the smallest change that unlocks clearer branching later

### Phase 2. Split common and specialized responsibilities

Refactor the class structure into:

- common base vector
- timestamp vector specialization
- duration vector specialization
- common base subarray
- timestamp subarray specialization
- duration subarray specialization

Tasks:

- identify methods that are truly common
- move only stable/common behavior into the base
- keep domain-specific storage and prediction behavior in derived classes

Important caution:

- do not force everything into the base too early
- if a method already diverges meaningfully for durations vs timestamps, keep it specialized

### Phase 3. Separate predictor from codec

Introduce a predictor abstraction.

Tasks:

- define predictor interface
- decide the predictor lifecycle
- define the handoff between predictor and codec state

Questions to resolve:

- does each subarray own one predictor?
- does predictor state persist after switching to codec mode?
- when a predictor fails, do we downgrade the same subarray or terminate it?

Expected early result:

- current heuristic logic can migrate out of codec/storage code

### Phase 4. Implement `NoneState` / `CodecState`

This is the core behavioral refactor.

Tasks:

- represent subarray state explicitly
- decide which statistics remain available in both states
- ensure append paths work in both states
- ensure transitions are well-defined and testable

Key design choice:

- whether `CodecState` stores:
  - only predictor parameters
  - predictor parameters plus sparse checkpoints
  - predictor parameters plus bounded reconstruction cache

### Phase 5. Rework storage flow

After the state model is working, revisit storage.

Target:

- storage should consume the state already maintained in memory
- it should not need to reconstruct the whole idea of the trend only at write time

Tasks:

- minimize “late” storage-only encoding logic
- keep file format concerns in codec/storage boundary code
- avoid reintroducing duplication between runtime state and serialized state

### Phase 6. Revisit duration-specific predictors/codecs

Once the new structure exists, revisit duration handling specifically.

Rationale:

- timestamps benefit from natural monotone ordering
- durations do not
- therefore duration predictors probably need a different philosophy

Likely future directions:

- distribution-aware predictors
- local-window models
- bounded-error stochastic reconstruction
- hybrid representations that preserve coarse statistics plus limited structure

## Open Design Questions

These should be answered during implementation rather than left implicit:

1. When switching to `CodecState`, do we compress the already accumulated raw values immediately?
2. If a trend breaks, do we:
   - revert the same subarray to raw mode, or
   - close the subarray and open a new one?
3. Which statistics must always be stored, regardless of state?
4. Does the predictor operate:
   - per value
   - per window
   - per subarray
5. How much reconstruction fidelity is needed while the program is still running, before final file write?
6. Which parts of the current `SubArrayCodec` API remain valid once prediction is moved earlier?

## Practical Order of Work

Recommended order:

1. add domain tag
2. split common vs specialized classes
3. extract predictor concept
4. implement explicit state model
5. rewire storage path around the new model
6. revisit duration-specific modeling

This ordering keeps the risky “behavioral” changes after the structural groundwork is laid.

## Risks

Main risks of the refactor:

- over-generalizing the base class too early
- making duration and timestamp paths look more similar than they really are
- breaking lazy loading / storage compatibility while moving state earlier
- accidentally increasing complexity without reducing memory usage

Mitigation:

- keep each phase small and testable
- preserve compatibility as long as possible
- measure memory/state impact after each major phase

## Success Criteria

The refactor should be considered successful if:

- timestamp and duration paths are structurally clearer
- predictors and codecs are decoupled
- subarray state transitions are explicit
- runtime memory usage can become meaningfully smaller than the current raw-only accumulation model
- duration handling no longer depends on assumptions that only really fit monotone timestamp data
