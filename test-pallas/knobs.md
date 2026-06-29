# PLA And DurationSpike Knobs

This note explains the main constants used by the current C++ implementations of:

- timestamp lossy compression via `PLAManager`
- duration lossy compression via `DurationSpikeManager`

The goal is practical tuning: what each constant does, what happens if we increase or decrease it, and what range is sensible to experiment with.

## Timestamp PLA Overview

There are currently two timestamp paths:

- `PLA4`: simple alpha-style anchor picker
- `PLA8`, `PLA16`, `PLA32`: gamma-style anchor picker

All of them work on a logical block of `1000` timestamps.

### PLA4 flow

`PLA4` is intentionally simple:

1. Compute local deltas.
2. For each interior point, score how unusual its delta is relative to a small `+-5` neighborhood.
3. Keep the top 4 interior points.
4. Sort them by index.
5. Emit anchor records.

This is a cheap post-mortem approximation path.

### Gamma PLA flow

`PLA8/16/32` use the more structured Gamma pipeline:

1. Precompute per-block stats in one pass:
   - delta
   - absolute delta-of-delta
   - prefix sums for line-fit scoring
   - per-position spike score
2. Initialize per-position candidate state:
   - `Null`
   - `Free`
   - `Suppressed`
   - `Anchor`
3. Build a seed pool from the best spike-score positions.
4. Choose a few spread-aware initial seeds.
5. Suppress nearby smooth regions asymmetrically, especially to the right of strong spikes.
6. Repeatedly refine the worst segment if splitting it gives enough gain.
7. If refinement stalls before reaching the target `K`, fill from remaining `Free`, then `Suppressed`, then anything still available.

Important behavior:

- first and last logical values are not anchors
- they are implicit boundaries
- Gamma always tries to reach exactly the requested `K` unless the block is too small to have that many interior points

## Timestamp PLA Knobs

### Runtime dispatch knob

`k_max`

- Where it comes from:
  - `PLA4`, `PLA8`, `PLA16`, `PLA32`
- Meaning:
  - target number of interior anchors to store
- Current values:
  - `4`, `8`, `16`, `32`
- Effect:
  - higher `k_max` lowers error and lowers compression
  - lower `k_max` increases compression but forces longer segments
- Practical tuning:
  - `4` is the cheap aggressive-compression path
  - `8` is a good first “serious” PLA mode
  - `16` and `32` are for better fit on messy traces

### Block size

`kPLABlockSize = 1000`

- Meaning:
  - logical values per PLA block
- Effect:
  - larger blocks improve amortization but make one model cover more behavior
  - smaller blocks react better to local shape changes but increase metadata/header churn
- Practical tuning:
  - keep at `1000` unless the whole storage scheme changes

### Hard anchor ceiling

`kPLAMaxAnchors = 32`

- Meaning:
  - compile-time storage ceiling for PLA anchor arrays
- Effect:
  - only matters if we want schemes above `PLA32`
- Practical tuning:
  - leave as-is unless new policies above `32` are introduced

## Gamma-Specific Knobs

These affect `PLA8/16/32`.

### Local spike neighborhood

`kGammaLocalRadius = 8`

- Meaning:
  - when scoring a candidate spike, compare it against a local neighborhood of roughly `+-8` delta positions
- Lower values:
  - makes scoring more local and more sensitive
  - can overreact to very small noisy clusters
- Higher values:
  - smooths the score more
  - can miss short sharp structure
- Sensible range:
  - `4` to `16`

### Seed pool size

`kGammaSeedPoolSize = 64`

- Meaning:
  - number of best-scored candidates retained before spread-aware seeding
- Lower values:
  - faster, but more likely to miss a good distant seed
- Higher values:
  - more robust seed choice, slightly more work
- Sensible range:
  - `16` to `128`
- Rule of thumb:
  - if seed placement looks too concentrated, increase this first

### Initial seed count

`kGammaSeedCount = 4`

- Meaning:
  - number of spread-aware anchors chosen before refinement starts
- Lower values:
  - lets refinement do more of the work
  - can miss obvious structure early
- Higher values:
  - stronger initial partitioning
  - can overcommit anchors too early
- Sensible range:
  - `2` to `6`
- Good default:
  - `4` is sensible for `K=8/16/32`

### Candidates evaluated per segment

`kGammaCandidatesPerSegment = 4`

- Meaning:
  - when splitting the current worst segment, only the top few local candidates are fully evaluated
- Lower values:
  - faster, but may miss a better split inside the segment
- Higher values:
  - slightly better refinement quality, more work
- Sensible range:
  - `2` to `8`

### Right suppression windows

`kGammaRightWindows = {4, 16, 32, 64, 128, 256, 512}`

- Meaning:
  - how far a strong anchor can suppress candidates to its right
- Larger schedule:
  - more aggressive “claim the flat continuation after the spike”
- Smaller schedule:
  - keeps more right-side candidates alive
- Tuning effect:
  - if Gamma keeps wasting anchors immediately after a large spike, increase right suppression
  - if it misses later useful right-side structure, reduce it

### Left suppression windows

`kGammaLeftWindows = {4, 16, 32, 64}`

- Meaning:
  - how far suppression extends to the left
- Intent:
  - left suppression is intentionally weaker than right suppression
- Tuning effect:
  - increase only if you see too many redundant anchors just before spikes
- Sensible upper bound:
  - keeping left suppression much smaller than right suppression is usually the right shape

### Suppressed-overlap threshold

`kGammaSuppressedOverlapThreshold = 0.6`

- Meaning:
  - stop suppression if too much of the candidate window is already suppressed
- Lower values:
  - suppression becomes more conservative
- Higher values:
  - suppression becomes more willing to extend through already-muted regions
- Sensible range:
  - `0.4` to `0.8`

### Minimum segment length for refinement

`kGammaMinSegmentLength = 8`

- Meaning:
  - very short segments are not further split during refinement
- Lower values:
  - can squeeze more anchors into tiny segments
  - may overfit noise
- Higher values:
  - avoids overfitting, but may leave local bad regions untouched
- Sensible range:
  - `6` to `16`

### Minimum relative gain

`kGammaMinGainRatio = 0.05`

- Meaning:
  - the split must improve the parent segment score by at least `5%` of the parent score
- Lower values:
  - more eager splitting
  - may chase tiny improvements
- Higher values:
  - more conservative splitting
  - may stop refinement too early
- Sensible range:
  - `0.01` to `0.10`

### Minimum absolute gain

`kGammaMinGainAbs = 1e-6`

- Meaning:
  - absolute floor for accepting a split, even if the parent score is tiny
- Usually:
  - leave this tiny unless numerical issues show up
- Sensible range:
  - `1e-8` to `1e-4`

## What To Tune First For PLA

If Gamma looks bad, tune in this order:

1. `k_max`
2. `kGammaSeedPoolSize`
3. `kGammaRightWindows`
4. `kGammaLocalRadius`
5. `kGammaMinGainRatio`

Typical symptoms:

- Too many anchors near one noisy cluster:
  - increase `kGammaRightWindows`
  - increase `kGammaSeedPoolSize`
  - possibly increase `kGammaLocalRadius`
- Not enough anchors in later structure:
  - reduce right suppression
  - reduce `kGammaMinGainRatio`
- Overfitting tiny wiggles:
  - increase `kGammaMinSegmentLength`
  - increase `kGammaMinGainRatio`

## DurationSpike Overview

`DurationSpikeManager` is a post-mortem duration model for `1000`-value blocks.

It assumes the duration block usually has:

- a dominant baseline
- small noise around that baseline
- a small number of positive spikes/outliers

### Current flow

1. Compute a robust initial baseline using the median.
2. Compute residuals relative to that baseline.
3. Derive a spike threshold from median absolute residuals.
4. Keep only strong positive residuals as spike candidates.
5. Sort candidates by spike size.
6. Store the strongest ones exactly.
7. Group some of the remaining similar spikes together.
8. Fit a clipped baseline mean/stddev on the values not claimed by spikes.
9. During reconstruction:
   - exact spikes are exact
   - grouped spikes use their shared group value
   - all remaining positions are regenerated from a deterministic Gaussian-like sample around the clipped baseline

This is not PLA. It is more like:

- baseline + exact outliers + grouped outliers

## DurationSpike Knobs

### Runtime dispatch knob

`k_max`

- Where it comes from:
  - `Spike4`, `Spike8`, `Spike16`, `Spike32`
- Meaning:
  - upper budget of spike candidates retained after sorting
- Lower values:
  - more compression, more missed spikes
- Higher values:
  - better spike preservation, larger payload
- Good practical range:
  - `4`, `8`, `16`, `32`

### Maximum exact spikes

`kMaxExactSpikes = 8`

- Meaning:
  - hard cap on how many spikes we keep as exact `(index, value)` pairs
- Lower values:
  - forces more grouping/baseline usage
- Higher values:
  - preserves the biggest spikes better, but uses more bytes
- Practical note:
  - current logic uses roughly `min(8, max(2, k_max / 2))`
- Sensible range:
  - `4` to `12`

### Maximum grouped spike buckets

`kMaxSpikeGroups = 4`

- Meaning:
  - number of distinct grouped spike values allowed
- Lower values:
  - simpler payload, but more spikes fall back to baseline
- Higher values:
  - better fit for several “families” of spikes
  - slightly larger payload and more grouping complexity
- Sensible range:
  - `2` to `8`

### Minimum group size

`kMinGroupSize = 2`

- Meaning:
  - a group must contain at least this many spike indices to be worth storing as a shared bucket
- Lower values:
  - easier to create groups
  - can create wasteful one-off buckets
- Higher values:
  - only stronger recurring spike patterns survive
- Sensible range:
  - `2` to `4`

### Relative group tolerance

`kRelativeGroupTolerance = 0.20`

- Meaning:
  - two residual spikes are considered similar if they differ by at most roughly `20%` of the seed spike size, unless the absolute tolerance is larger
- Lower values:
  - stricter grouping
  - more exact-like behavior, fewer merged spikes
- Higher values:
  - more aggressive grouping
  - can flatten distinct spike heights into one bucket
- Sensible range:
  - `0.10` to `0.35`

### Absolute group tolerance

`kAbsoluteGroupTolerance = 96.0`

- Meaning:
  - minimum allowed grouping tolerance, even for smaller spikes
- Lower values:
  - small spikes need to match more closely to share a bucket
- Higher values:
  - easier grouping among moderate spikes
- Sensible range:
  - `32` to `256`

### Minimum spike residual

`kMinSpikeResidual = 64.0`

- Meaning:
  - absolute floor for calling something a spike
- Real threshold used:
  - `max(kMinSpikeResidual, 3 * median_abs_residual)`
- Lower values:
  - more candidates, more sensitivity, more false spikes
- Higher values:
  - fewer candidates, more compression, more missed medium spikes
- Sensible range:
  - `32` to `256`

### Baseline clipping sigma

`kBaselineClipSigma = 2.5`

- Meaning:
  - after removing spikes, baseline fitting clips values outside about `2.5 sigma`
- Lower values:
  - more aggressive clipping
  - cleaner baseline, but may throw away real baseline variation
- Higher values:
  - baseline fit absorbs more variation
  - risk of spike leakage into the baseline model
- Sensible range:
  - `2.0` to `3.5`

### Minimum baseline clip radius

`kBaselineMinClipRadius = 32.0`

- Meaning:
  - even if estimated sigma is tiny, allow at least this much spread before clipping
- Lower values:
  - baseline becomes very tight
- Higher values:
  - more tolerant baseline
- Sensible range:
  - `16` to `128`

## What To Tune First For DurationSpike

If duration reconstruction looks bad, tune in this order:

1. `k_max`
2. `kMinSpikeResidual`
3. `kMaxExactSpikes`
4. `kRelativeGroupTolerance`
5. `kBaselineClipSigma`

Typical symptoms:

- Big spikes are missed:
  - increase `k_max`
  - decrease `kMinSpikeResidual`
  - increase `kMaxExactSpikes`
- Similar spikes are being merged too aggressively:
  - decrease `kRelativeGroupTolerance`
  - decrease `kAbsoluteGroupTolerance`
- Baseline looks too flat:
  - increase `kBaselineClipSigma`
  - increase `kBaselineMinClipRadius`
- Baseline looks too noisy:
  - decrease `kBaselineClipSigma`
  - decrease `kBaselineMinClipRadius`

## Quick Mental Model

For timestamps:

- `PLA4` is cheap spike picking
- `PLA8/16/32` is seeded segmentation with suppression and refinement

For durations:

- keep a few strongest spikes exactly
- cluster some similar spikes
- model the rest as a clipped noisy baseline

That means:

- PLA knobs mostly decide where anchors go
- DurationSpike knobs mostly decide what counts as a spike, what gets grouped, and how tight the baseline model is
