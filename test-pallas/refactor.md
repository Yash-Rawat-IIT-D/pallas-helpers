# Linked Vector Refactor Notes

This note describes the current structure around:

- `pallas_linked_vector.h`
- `pallas_linked_vector.cpp`
- the way storage/read/write code calls into them from `pallas_storage.cpp`

The goal is to make future refactors easier by clarifying:

- which types own what
- which layers call which functions
- where codec policy is chosen
- where storage metadata lives
- where current coupling points exist

Assumption: this reflects the current `bmark-*` branch state.

## 1. High-Level Dependency Tree

```text
ParameterHandler
├── default timestamp subarray encoding
├── default duration subarray encoding
├── MonotoneLossyVariant
├── DurationLossyVariant
└── memory + benchmark/storage counters context

SubArrayEncoding
├── None
├── Delta2VintTimestamp
├── Delta2VintDuration
├── MonotoneLossy
└── DurationLossy

SubArrayCodec interface
├── NoneCodec
├── Delta2VintCodecBase
│   ├── TimestampDelta2VintCodec
│   └── DurationDelta2VintCodec
├── MonotoneLossyCodec
└── DurationLossyCodec

LinkedVector
├── owns linked list of LinkedVector::SubArray
├── used for event timestamps / sequence timestamps
├── writes metadata to info file
├── writes encoded payload to data file
└── lazy-loads payload through load_data()

LinkedDurationVector
├── owns linked list of LinkedDurationVector::SubArray
├── tracks min/max/mean at vector and subarray level
├── used for sequence durations / exclusive durations
├── writes metadata to info file
├── writes encoded payload to data file
└── lazy-loads payload through load_data()

pallas_storage.cpp
├── calls LinkedVector::write_to_file()
├── calls LinkedDurationVector::write_to_file()
├── constructs vectors back from metadata files
├── calls LinkedVector::load_data()
├── calls LinkedDurationVector::load_data()
└── in BMARK mode verifies encode/decode correctness

pallas_write.cpp
└── influences which SubArrayEncoding gets assigned during trace construction
```

## 2. Main Types in `pallas_linked_vector.h`

### 2.1 `SubArrayEncoding`

This is the central enum for payload encoding policy.

```text
SubArrayEncoding
├── None
├── Delta2VintTimestamp
├── Delta2VintDuration
├── MonotoneLossy
└── DurationLossy
```

It is stored:

- as the preferred encoding on a whole vector
- on each concrete subarray as `sub_arr_encoding`
- in the serialized metadata for each stored subarray

So this enum is both:

- a policy choice during write time
- part of the persisted trace format

### 2.2 `SubArrayCodec`

`SubArrayCodec` is the common interface all subarray encoders implement.

Current shape:

```text
SubArrayCodec
├── encoding()
├── can_encode(array, size)
├── encode(file, array, size, encoded_array, caller_sub_array, caller_kind, parameter_handler)
└── decode(encoded_array, enc_size, decoded_array, size, caller_sub_array, caller_kind, parameter_handler)
```

Important current detail:

- `encode()` and `decode()` both receive:
  - `void* caller_sub_array`
  - `int caller_kind`
- `caller_kind == 0` means `LinkedVector::SubArray`
- `caller_kind == 1` means `LinkedDurationVector::SubArray`

This is a lightweight callback context mechanism so codecs can use caller metadata without a larger structural redesign.

### 2.3 Concrete codec tree

```text
SubArrayCodec
├── NoneCodec
│   ├── encode: passthrough
│   └── decode: passthrough
├── Delta2VintCodecBase
│   ├── varint helpers
│   ├── timestamp delta helpers
│   └── duration delta helpers
├── TimestampDelta2VintCodec
│   └── wraps Delta2VintCodecBase for monotone timestamps
├── DurationDelta2VintCodec
│   └── wraps Delta2VintCodecBase for signed duration deltas
├── MonotoneLossyCodec
│   └── current implemented variant: QLinear
└── DurationLossyCodec
    ├── current implemented variant: QLinear
    └── current stub: QLinearMeanRep
```

### 2.4 `LinkedVector`

`LinkedVector` is the linked-list-backed storage type for timestamp-like vectors.

Key responsibilities:

- append values incrementally
- split into fixed-capacity subarrays
- remember preferred encoding for new subarrays
- serialize subarray metadata and payload
- lazy-load payload on demand

Current data shape:

```text
LinkedVector
├── size
├── ref
├── n_sub_array
├── is_contiguous
├── filePath
├── parameter_handler
├── preferred_sub_arr_encoding
├── loaded_subarrays
├── first
└── last
```

### 2.5 `LinkedVector::SubArray`

This is the actual payload node for `LinkedVector`.

```text
LinkedVector::SubArray
├── size
├── allocated
├── sub_arr_encoding
├── enc_size
├── array
├── next / previous
├── starting_index
├── first_value
├── last_value
└── offset
```

Key meaning:

- `sub_arr_encoding`: encoding selected for this subarray payload
- `enc_size`: encoded payload length in `uint64_t` words
- `offset`: offset into the payload file
- `first_value` / `last_value`: metadata shortcuts used by timestamp logic

### 2.6 `LinkedDurationVector`

`LinkedDurationVector` is parallel to `LinkedVector`, but duration-specific.

Extra responsibilities:

- maintain duration statistics
- expose approximate aggregated operations such as `weightedSum()`

Current data shape:

```text
LinkedDurationVector
├── size
├── ref
├── n_sub_array
├── is_contiguous
├── filePath
├── parameter_handler
├── preferred_sub_arr_encoding
├── loaded_subarrays
├── first
├── last
├── min
├── max
└── mean
```

### 2.7 `LinkedDurationVector::SubArray`

This is the duration payload node.

```text
LinkedDurationVector::SubArray
├── size
├── allocated
├── sub_arr_encoding
├── enc_size
├── array
├── next / previous
├── starting_index
├── offset
├── min
├── max
└── mean
```

Difference vs timestamp subarray:

- there is no `first_value` / `last_value`
- instead we persist `min` / `max` / `mean`

These statistics are especially important now because `DurationLossyCodec::decode_qlinear()` reconstructs values using:

- `encoded interior quantiles`
- `subarray min`
- `subarray max`

### 2.8 Current codec-access helper methods

Because nested `SubArray` types remain private, the code currently exposes small helper accessors:

```text
LinkedVector
└── codec_subarray_starting_index(void*)

LinkedDurationVector
├── codec_subarray_starting_index(void*)
├── codec_subarray_min(void*)
└── codec_subarray_max(void*)
```

This is the current compromise between:

- wanting codec access to subarray metadata
- not yet doing a bigger shared-base-class refactor

## 3. Construction and Append-Time Flow

### 3.1 Vector construction

```text
LinkedVector(ParameterHandler&)
└── preferred_sub_arr_encoding = parameter_handler.getTimestampSubArrayEncoding()

LinkedDurationVector(ParameterHandler&)
└── preferred_sub_arr_encoding = parameter_handler.getDurationSubArrayEncoding()
```

Both constructors create an initial `SubArray(DEFAULT_VECTOR_SIZE)`.

### 3.2 Append path

For timestamps:

```text
LinkedVector::add(val)
├── if last subarray full:
│   ├── allocate new SubArray
│   ├── copy preferred_sub_arr_encoding into new subarray
│   └── increment n_sub_array
└── delegate to LinkedVector::SubArray::add(val)
```

For durations:

```text
LinkedDurationVector::add(val)
├── if last subarray full:
│   ├── finalize old subarray mean
│   ├── allocate new SubArray
│   ├── copy preferred_sub_arr_encoding into new subarray
│   └── increment n_sub_array
├── delegate to LinkedDurationVector::SubArray::add(val)
└── update vector-level min/max/mean accumulator
```

## 4. Write-Time Flow

### 4.1 Big-picture write chain

```text
storeEvent() / storeSequence() in pallas_storage.cpp
└── vector->write_to_file(infoFile, dataFile, parameter_handler, storage_counters)
    └── each loaded subarray:
        └── subarray->write_to_file(dataFile, parameter_handler, storage_counters)
            ├── choose codec from sub_arr_encoding
            ├── fallback to None if can_encode() == false
            ├── codec->encode(...)
            ├── _pallas_compress_write(...)
            ├── in BMARK: verify by decode + compare
            └── free in-memory array
```

### 4.2 `LinkedVector::write_to_file()`

Writes:

- vector-level metadata to the info file
- then each subarray metadata

For each subarray metadata entry:

```text
[size, sub_arr_encoding, enc_size, first_value, last_value, offset]
```

### 4.3 `LinkedDurationVector::write_to_file()`

Writes:

- vector-level metadata
- vector-level `min/max/mean`
- then each subarray metadata

For each duration subarray metadata entry:

```text
[size, sub_arr_encoding, enc_size, min, max, mean, offset]
```

### 4.4 Codec selection at subarray write time

The critical dispatch point is:

```text
sub_arr_encoding
  -> get_subarray_codec(sub_arr_encoding)
  -> codec->can_encode(array, size)
      -> if false:
         sub_arr_encoding = None
         codec = get_subarray_codec(None)
```

This means the persisted `sub_arr_encoding` may be downgraded at write time.

Example:

- `DurationLossy` currently only accepts `size >= 11`
- smaller subarrays automatically fall back to `None`

### 4.5 Current write-time caller context

Write-time encode calls pass:

```text
LinkedVector::SubArray::write_to_file()
└── codec->encode(..., this, 0, parameter_handler)

LinkedDurationVector::SubArray::write_to_file()
└── codec->encode(..., this, 1, parameter_handler)
```

So codecs can tell:

- which vector family called them
- which specific subarray is involved

## 5. Read-Time Flow

### 5.1 Big-picture lazy-load chain

```text
readEvent() / readSequence() in pallas_storage.cpp
└── construct LinkedVector / LinkedDurationVector from metadata only
    └── no payload loaded yet

later...
operator[](pos) / at(pos) / load_all_data()
└── load_data(sub)
    ├── seek to payload offset
    ├── _pallas_compress_read(...)
    ├── get_subarray_codec(sub->sub_arr_encoding)
    ├── codec->decode(..., sub, caller_kind, &parameter_handler)
    └── register loaded subarray in LRU queue
```

### 5.2 Metadata-only reconstruction

`LinkedVector(FILE*, ...)` reconstructs only:

- vector size
- number of subarrays
- preferred encoding
- subarray metadata

`LinkedDurationVector(FILE*, ...)` additionally reconstructs:

- vector min/max/mean
- subarray min/max/mean

At this stage `array == nullptr` for lazy subarrays.

### 5.3 Read-side codec dispatch

Timestamp-like:

```text
codec->decode(encoded_array, enc_size, sub->array, sub->size, sub, 0, &parameter_handler)
```

Duration-like:

```text
codec->decode(encoded_array, enc_size, sub->array, sub->size, sub, 1, &parameter_handler)
```

This is especially important for `DurationLossy`, whose decode now depends on duration subarray metadata.

## 6. Codec-Specific Notes

### 6.1 `NoneCodec`

Behavior:

- no transform
- encoded array is the original array
- decoded array is the encoded array

Coupling consequence:

- caller must be careful not to double free

### 6.2 `TimestampDelta2VintCodec`

Assumption:

- values are monotone timestamps

Shape:

- base timestamp
- first delta
- delta-of-delta varints after that

### 6.3 `DurationDelta2VintCodec`

Assumption:

- durations are not monotone
- adjacent deltas can be signed

Shape:

- base duration
- first signed delta
- delta-of-delta varints

### 6.4 `MonotoneLossyCodec`

Current implemented variant:

- `QLinear`

High-level idea:

- store 11 percentile anchors
- reconstruct a monotone approximation by linear interpolation

Current coupling:

- works directly on the array values
- does not need caller subarray metadata

### 6.5 `DurationLossyCodec`

Current implemented variant:

- `QLinear`

Current algorithm:

```text
encode
├── require size >= 11
├── sort the subarray values
├── extract q10..q90
└── store only those 9 values

decode
├── require duration caller kind
├── recover min/max from LinkedDurationVector::SubArray metadata
├── rebuild 11-anchor quantile model:
│   [min, q10, q20, ..., q90, max]
├── reconstruct sorted values by inverse-CDF-style interpolation
└── deterministically shuffle output using fixed seed + starting_index
```

Current important coupling:

- depends on duration subarray metadata
- depends on caller kind being `1`
- depends on helper accessors on `LinkedDurationVector`

## 7. How `pallas_storage.cpp` Exposes the Linked Vectors

### 7.1 Event path

```text
Event
└── event.timestamps : LinkedVector
    ├── storeEvent() writes it
    └── readEvent() reconstructs it lazily
```

### 7.2 Sequence path

```text
Sequence
├── sequence.durations : LinkedDurationVector
├── sequence.exclusive_durations : LinkedDurationVector
└── sequence.timestamps : LinkedVector
```

Write-time sequence order is currently:

1. durations
2. exclusive durations
3. timestamps

Each of those can use a different `StorageErrorCounters` bucket in `BMARK` mode.

### 7.3 Benchmark-only coupling

On the benchmark branch, `StorageCounters` is threaded through `write_to_file()` so the storage layer can record:

- write time
- compression sizes
- verification timing
- MSE/RMSE/NRMSE-like error metrics

That means this branch currently couples:

- vector write path
- codec decode path
- verification reporting

more tightly than the clean functional branch does.

## 8. Current Memory/Lifetime Model

### 8.1 In-memory append mode

- a vector owns one or more live subarrays
- each subarray owns `array`
- once serialized, the subarray frees `array`

### 8.2 Lazy-read mode

- metadata exists even when `array == nullptr`
- `load_data()` reconstructs `array` on demand
- loaded subarrays are tracked in `loaded_subarrays`
- an LRU-like queue in `ParameterHandler::subvector_queue` is used for eviction when memory is high

### 8.3 Destruction model

Two cases:

- non-contiguous allocation: linked subarrays individually deleted
- contiguous metadata allocation on read path: placement-new over a `calloc` block and later `free(first)`

This is an important refactor hazard area.

## 9. Current Refactor Pressure Points

These are the places that look most coupled today.

### 9.1 Private nested `SubArray` types plus codec metadata needs

Current workaround:

- `void* caller_sub_array`
- `caller_kind`
- helper accessors like `codec_subarray_min()`

Possible future refactor direction:

- shared codec-visible metadata struct
- common base for subarray metadata
- or codec traits per vector family

### 9.2 `LinkedVector` and `LinkedDurationVector` duplicate a lot of logic

Shared behavior today:

- linked-subarray ownership
- append/split logic
- lazy loading
- serialization traversal
- preferred encoding handling

Differences:

- timestamp vs duration metadata
- statistics maintenance
- certain query helpers
- different codec assumptions

This suggests a future base/shared internal layer may eventually make sense, but it is currently not there.

### 9.3 Storage concerns are mixed with encoding concerns

Current write path does all of these in one route:

- choose codec
- encode
- compress
- benchmark verify
- persist metadata
- free memory

This makes isolated codec testing harder than it could be.

### 9.4 Persisted metadata format is codec-sensitive

Examples:

- `LinkedVector::SubArray` persists `first_value` / `last_value`
- `LinkedDurationVector::SubArray` persists `min` / `max` / `mean`
- `DurationLossy` decode now depends on duration metadata being present and valid

So changing codec design may require revisiting serialized metadata, not just codec code.

## 10. Practical “Who Calls What?” Cheat Sheet

```text
ThreadWriter / write logic
└── builds Event / Sequence contents

pallas_storage.cpp
├── storeEvent()
│   └── event.timestamps->write_to_file(...)
├── storeSequence()
│   ├── sequence.durations->write_to_file(...)
│   ├── sequence.exclusive_durations->write_to_file(...)
│   └── sequence.timestamps->write_to_file(...)
├── readEvent()
│   └── new LinkedVector(FILE*, ...)
└── readSequence()
    ├── new LinkedDurationVector(FILE*, ...)
    ├── new LinkedDurationVector(FILE*, ...)
    └── new LinkedVector(FILE*, ...)

LinkedVector / LinkedDurationVector
├── write_to_file(...)
│   └── SubArray::write_to_file(...)
│       ├── get_subarray_codec(...)
│       ├── codec->can_encode(...)
│       ├── codec->encode(...)
│       ├── _pallas_compress_write(...)
│       └── in BMARK: pallasVerifyEncodedSubArray(...)
└── load_data(sub)
    ├── _pallas_compress_read(...)
    ├── get_subarray_codec(...)
    └── codec->decode(...)
```

## 11. Suggested Future Refactor Questions

When revisiting this area later, these are probably the most useful questions to ask first:

1. Do we want a shared internal base for `LinkedVector` and `LinkedDurationVector`, or do we prefer two explicit parallel types?
2. Should codec-visible metadata become a real typed object instead of `void* + caller_kind`?
3. Should encode/decode logic be separated more clearly from file I/O and compression?
4. Which subarray metadata is truly part of the on-disk format contract, and which is just a convenience cache?
5. Should lossy codecs be allowed to depend on subarray metadata outside the encoded payload, or should decode be self-contained?

## 12. Short Summary

Today the system is organized around:

- two linked-vector containers
- one per-subarray encoding enum
- one codec interface with lightweight caller context
- storage code that owns persistence and lazy reload

The most important current coupling is:

- `pallas_storage.cpp` owns persistence policy
- `pallas_linked_vector.*` owns container and codec mechanics
- lossy codecs, especially `DurationLossy`, now depend on subarray metadata and caller context

That is the main architectural pressure point to keep in mind for future work.
