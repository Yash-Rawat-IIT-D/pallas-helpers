import os
import statistics
from collections import Counter

from .common import (
    DEBUG_ATTR_PARTS,
    DEFAULT_SUBARRAY_BATCH_SIZE,
    MPI_NAME_FILTERS,
    print_unavailable,
    safe_getattr,
    summarize_numeric_series,
    vector_to_list,
)


def format_token_like(obj):
    obj_type = type(obj).__name__
    token_id = safe_getattr(safe_getattr(obj, "id"), "id")
    token_type = safe_getattr(safe_getattr(safe_getattr(obj, "id"), "type"), "name")
    record = safe_getattr(safe_getattr(obj, "record"), "name")
    name = None
    guess = safe_getattr(obj, "guessName")
    if callable(guess):
        try:
            name = guess()
        except Exception:
            name = None
    if obj_type == "Loop":
        loop_sequence = safe_getattr(obj, "sequence")
        repeated_token = safe_getattr(loop_sequence, "id")
        repeated_token_type = safe_getattr(safe_getattr(repeated_token, "type"), "name")
        repeated_token_id = safe_getattr(repeated_token, "id")
        name = (
            f"Loop(nb_iterations={safe_getattr(obj, 'nb_iterations')}, "
            f"repeated_token_type={repeated_token_type}, "
            f"repeated_token_id={repeated_token_id})"
        )
    return {
        "object_type": obj_type,
        "token_type": token_type,
        "token_id": token_id,
        "record": record,
        "name": name,
    }


def get_thread_root_sequence(thread):
    sequences = list(safe_getattr(thread, "sequences", []) or [])
    for sequence in sequences:
        guess = safe_getattr(sequence, "guessName")
        if callable(guess):
            try:
                if guess() == "thread":
                    return sequence
            except Exception:
                pass
    return sequences[0] if sequences else None


def print_basic_summary(trace, archive, thread):
    print("=== Basic Summary ===")
    archives = list(safe_getattr(trace, "archives", []) or [])
    print(f"archives={len(archives)}")

    archive_threads = list(safe_getattr(archive, "threads", []) or []) if archive else []
    print(f"selected_archive_id={safe_getattr(archive, 'id')}")
    print(f"threads_in_selected_archive={len(archive_threads)}")
    print(f"selected_thread_id={safe_getattr(thread, 'id')}")

    if thread is None:
        print_unavailable("thread summary")
        return

    events = list(safe_getattr(thread, "events", []) or [])
    sequences = list(safe_getattr(thread, "sequences", []) or [])
    loops = list(safe_getattr(thread, "loops", []) or [])

    print(f"event_definitions={len(events)}")
    print(f"sequence_definitions={len(sequences)}")
    print(f"loop_definitions={len(loops)}")
    print(f"event_occurrences={sum(safe_getattr(event, 'nb_occurrences', 0) for event in events)}")
    print(f"sequence_occurrences={sum(safe_getattr(sequence, 'n_iterations', 0) for sequence in sequences)}")

    root_sequence = get_thread_root_sequence(thread)
    if root_sequence is not None:
        root_content = list(safe_getattr(root_sequence, "content", []) or [])
        print(f"high_level_root_token_count={len(root_content)}")
    else:
        print_unavailable("high_level_root_token_count")

    metadata = safe_getattr(trace, "metadata")
    if metadata is not None:
        print(f"trace_metadata_keys={sorted(metadata.keys())}")
    else:
        print_unavailable("metadata keys")

    for field in (
        "number of tokens (exact unrolled total)",
        "number of unique event definitions",
        "number of unique sequence definitions",
    ):
        if field == "number of unique event definitions":
            print(f"unique_event_definitions={len(events)}")
        elif field == "number of unique sequence definitions":
            print(f"unique_sequence_definitions={len(sequences)}")
        else:
            print_unavailable(field)


def print_token_analysis(thread, max_tokens):
    print("=== Token Analysis ===")
    if thread is None:
        print_unavailable("token analysis")
        return

    root_sequence = get_thread_root_sequence(thread)
    if root_sequence is None:
        print_unavailable("root sequence / token stream")
        return

    root_content = list(safe_getattr(root_sequence, "content", []) or [])
    if not root_content:
        print("No root content available.")
        return

    token_infos = [format_token_like(item) for item in root_content]
    type_histogram = Counter(info["token_type"] or info["object_type"] for info in token_infos)
    name_histogram = Counter(info["name"] or info["record"] or info["object_type"] for info in token_infos)

    print(f"root_sequence_name={root_sequence.guessName()}")
    print(f"root_sequence_iterations={safe_getattr(root_sequence, 'n_iterations')}")
    print(f"high_level_token_count={len(token_infos)}")
    print(f"token_type_histogram={dict(type_histogram)}")
    print(f"event_like_tokens={type_histogram.get('EVENT', 0)}")
    print(f"sequence_like_tokens={type_histogram.get('SEQUENCE', 0)}")
    print(f"loop_like_tokens={type_histogram.get('LOOP', 0)}")
    print(f"most_common_high_level_tokens={name_histogram.most_common(10)}")
    print(f"first_{max_tokens}_tokens:")
    for idx, info in enumerate(token_infos[:max_tokens]):
        print(
            f"  [{idx}] type={info['token_type'] or info['object_type']} "
            f"id={info['token_id']} record={info['record']} name={info['name']}"
        )

    print_unavailable("exact fully unrolled token stream count")


def event_name(event):
    guess = safe_getattr(event, "guessName")
    if callable(guess):
        try:
            return guess()
        except Exception:
            pass
    record = safe_getattr(safe_getattr(event, "record"), "name")
    return record or "<unknown>"


def object_guess_name(obj):
    guess = safe_getattr(obj, "guessName")
    if callable(guess):
        try:
            return guess()
        except Exception:
            return None
    return None


def describe_grammar_node(obj):
    obj_type = type(obj).__name__
    token = safe_getattr(obj, "id")
    token_type = safe_getattr(safe_getattr(token, "type"), "name")
    token_id = safe_getattr(token, "id")

    if obj_type == "Event":
        record = safe_getattr(safe_getattr(obj, "record"), "name")
        name = event_name(obj)
        timestamps = safe_getattr(safe_getattr(obj, "timestamps"), "size")
        return f"EVENT id={token_id} record={record} name={name} timestamps={timestamps}"

    if obj_type == "Sequence":
        name = object_guess_name(obj)
        n_iterations = safe_getattr(obj, "n_iterations")
        durations = safe_getattr(safe_getattr(obj, "durations"), "size")
        timestamps = safe_getattr(safe_getattr(obj, "timestamps"), "size")
        token_count = len(list(safe_getattr(obj, "content", []) or []))
        return (
            f"SEQUENCE id={token_id} name={name} tokens={token_count} "
            f"iterations={n_iterations} duration_entries={durations} "
            f"timestamp_entries={timestamps}"
        )

    if obj_type == "Loop":
        loop_sequence = safe_getattr(obj, "sequence")
        repeated_token = safe_getattr(loop_sequence, "id")
        repeated_token_type = safe_getattr(safe_getattr(repeated_token, "type"), "name")
        repeated_token_id = safe_getattr(repeated_token, "id")
        return (
            f"LOOP id={token_id} nb_iterations={safe_getattr(obj, 'nb_iterations')} "
            f"repeated_token_type={repeated_token_type} repeated_token_id={repeated_token_id}"
        )

    return f"{obj_type} token_type={token_type} id={token_id}"


def flatten_sequence_leaf_events(obj, max_depth=32):
    leaves = []

    def walk(node, depth):
        if node is None or depth > max_depth:
            return
        obj_type = type(node).__name__
        if obj_type == "Event":
            leaves.append(node)
            return
        if obj_type == "Sequence":
            for child in list(safe_getattr(node, "content", []) or []):
                walk(child, depth + 1)
            return
        if obj_type == "Loop":
            walk(safe_getattr(node, "sequence"), depth + 1)

    walk(obj, 0)
    return leaves


def render_recursive_grammar(obj, indent=0, max_depth=12, seen=None):
    if seen is None:
        seen = set()

    prefix = "  " * indent
    lines = [f"{prefix}- {describe_grammar_node(obj)}"]
    if obj is None or indent >= max_depth:
        return lines

    obj_type = type(obj).__name__
    token = safe_getattr(obj, "id")
    token_key = (obj_type, safe_getattr(safe_getattr(token, "type"), "name"), safe_getattr(token, "id"))

    if token_key in seen:
        lines.append(f"{prefix}  (recursive reference omitted)")
        return lines

    child_seen = set(seen)
    child_seen.add(token_key)

    if obj_type == "Sequence":
        children = list(safe_getattr(obj, "content", []) or [])
        if not children:
            lines.append(f"{prefix}  (empty sequence content)")
        for child in children:
            lines.extend(render_recursive_grammar(child, indent + 1, max_depth, child_seen))
        return lines

    if obj_type == "Loop":
        repeated_sequence = safe_getattr(obj, "sequence")
        if repeated_sequence is None:
            lines.append(f"{prefix}  (loop has no repeated sequence object)")
            return lines
        lines.extend(render_recursive_grammar(repeated_sequence, indent + 1, max_depth, child_seen))

    return lines


def write_mpi_test_sequence_grammar_logs(mpi_test_sequences, trace_file, limit=5):
    if not mpi_test_sequences:
        return

    ranked = sorted(
        mpi_test_sequences,
        key=lambda seq: safe_getattr(seq, "n_iterations", 0) or 0,
        reverse=True,
    )

    for sequence in ranked[:limit]:
        token_id = safe_getattr(safe_getattr(sequence, "id"), "id")
        output_log_path = trace_file.parent / f"mpi_test_token_{token_id}_grammar.log"
        leaf_events = flatten_sequence_leaf_events(sequence)
        leaf_event_names = [event_name(event) for event in leaf_events]
        leaf_event_records = [
            safe_getattr(safe_getattr(event, "record"), "name") or "<unknown>"
            for event in leaf_events
        ]
        lines = [
            f"sequence_name={object_guess_name(sequence)}",
            f"token_id={token_id}",
            f"n_iterations={safe_getattr(sequence, 'n_iterations')}",
            f"duration_entries={safe_getattr(safe_getattr(sequence, 'durations'), 'size')}",
            f"timestamp_entries={safe_getattr(safe_getattr(sequence, 'timestamps'), 'size')}",
            "",
            "[leaf_event_summary]",
            f"leaf_event_count={len(leaf_events)}",
            f"leaf_event_names={Counter(leaf_event_names)}",
            f"leaf_event_records={Counter(leaf_event_records)}",
            f"contains_mpi_request_test={'MPI_REQUEST_TEST' in leaf_event_records}",
            "",
            "[recursive_grammar]",
        ]
        lines.extend(render_recursive_grammar(sequence))
        output_log_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        print(f"mpi_test_sequence_grammar token_id={token_id} log_output={output_log_path}")


def print_mpi_event_analysis(thread):
    print("=== MPI Event Analysis ===")
    if thread is None:
        print_unavailable("MPI event analysis")
        return

    events = list(safe_getattr(thread, "events", []) or [])
    if not events:
        print("No events available.")
        return

    interesting = []
    record_occurrences = Counter()
    name_occurrences = Counter()
    mpi_test_occurrences = 0

    for event in events:
        record_name = safe_getattr(safe_getattr(event, "record"), "name") or "<unknown>"
        guessed_name = event_name(event)
        occurrences = safe_getattr(event, "nb_occurrences", 0) or 0
        record_occurrences[record_name] += occurrences
        name_occurrences[guessed_name] += occurrences
        if any(part in guessed_name for part in MPI_NAME_FILTERS):
            interesting.append((guessed_name, record_name, occurrences, safe_getattr(event.timestamps, "size", None)))
        if "MPI_Test" in guessed_name or record_name == "MPI_REQUEST_TEST":
            mpi_test_occurrences += occurrences

    if interesting:
        print("matching_event_names:")
        for guessed_name, record_name, occurrences, ts_size in interesting:
            print(f"  name={guessed_name} record={record_name} occurrences={occurrences} timestamps={ts_size}")
    else:
        print("No matching MPI_Test / MPI_Irecv / MPI_Isend / MPI_Wait / MPI_Barrier event names found.")

    print(f"mpi_test_related_occurrences={mpi_test_occurrences}")
    print(f"top_event_records_by_occurrence={record_occurrences.most_common(10)}")
    print(f"top_event_names_by_occurrence={name_occurrences.most_common(10)}")


def plot_dominant_mpi_test_sequence_distributions(mpi_test_sequences, trace_file):
    if not mpi_test_sequences:
        print("No MPI_Test sequences available for plotting.")
        return

    dominant_sequence = max(
        mpi_test_sequences,
        key=lambda seq: len(vector_to_list(safe_getattr(seq, "timestamps"))),
    )
    token_id = safe_getattr(safe_getattr(dominant_sequence, "id"), "id")
    timestamps = vector_to_list(safe_getattr(dominant_sequence, "timestamps"))
    durations = vector_to_list(safe_getattr(dominant_sequence, "durations"))
    exclusive_durations = vector_to_list(safe_getattr(dominant_sequence, "exclusive_durations"))

    if not durations or not exclusive_durations:
        print("Dominant MPI_Test sequence does not expose enough duration data for plotting.")
        return

    output_svg_path = trace_file.parent / f"mpi_test_token_{token_id}_distributions.svg"
    output_png_path = trace_file.parent / f"mpi_test_token_{token_id}_distributions.png"
    os.environ.setdefault("MPLCONFIGDIR", "/tmp/matplotlib-pallas")

    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    def summarize_sorted(ordered):
        return {
            "count": len(ordered),
            "min": ordered[0],
            "p50": ordered[len(ordered) // 2],
            "p90": ordered[min(len(ordered) - 1, int(len(ordered) * 0.90))],
            "p99": ordered[min(len(ordered) - 1, int(len(ordered) * 0.99))],
            "max": ordered[-1],
            "mean": statistics.fmean(ordered),
        }

    def sampled_curve(ordered, max_points=20000):
        count = len(ordered)
        if count <= 1:
            return ordered, [1.0] * count, [100.0] * count
        if count <= max_points:
            indices = list(range(count))
        else:
            step = (count - 1) / (max_points - 1)
            indices = [round(i * step) for i in range(max_points)]
        xs = [ordered[index] for index in indices]
        cdf = [index / (count - 1) for index in indices]
        percentiles = [100.0 * index / (count - 1) for index in indices]
        return xs, cdf, percentiles

    ordered_durations = sorted(durations)
    ordered_exclusive_durations = sorted(exclusive_durations)
    duration_stats = summarize_sorted(ordered_durations)
    exclusive_stats = summarize_sorted(ordered_exclusive_durations)
    duration_x, duration_cdf, duration_pct = sampled_curve(ordered_durations)
    exclusive_x, exclusive_cdf, exclusive_pct = sampled_curve(ordered_exclusive_durations)

    fig, axes = plt.subplots(2, 2, figsize=(14, 9), constrained_layout=True)
    fig.suptitle(
        "Dominant MPI_Test sequence distributions\n"
        f"token_id={token_id} timestamp_entries={len(timestamps)} "
        f"duration_entries={len(durations)} exclusive_duration_entries={len(exclusive_durations)}"
    )

    plot_specs = [
        (axes[0][0], axes[0][1], duration_x, duration_cdf, duration_pct, duration_stats, "Sequence durations", "#2563eb"),
        (axes[1][0], axes[1][1], exclusive_x, exclusive_cdf, exclusive_pct, exclusive_stats, "Sequence exclusive durations", "#dc2626"),
    ]

    for cdf_axis, quantile_axis, xs, cdf, pct, stats_map, title, color in plot_specs:
        cdf_axis.plot(xs, cdf, color=color, linewidth=1.4)
        cdf_axis.set_title(f"{title} ECDF")
        cdf_axis.set_xlabel("Value")
        cdf_axis.set_ylabel("Cumulative fraction")
        cdf_axis.set_xscale("symlog", linthresh=1.0)
        cdf_axis.set_ylim(0.0, 1.0)
        cdf_axis.grid(True, alpha=0.25)
        cdf_axis.text(
            0.985,
            0.95,
            "\n".join(
                [
                    f"count={stats_map['count']}",
                    f"min={stats_map['min']}",
                    f"p50={stats_map['p50']}",
                    f"p90={stats_map['p90']}",
                    f"p99={stats_map['p99']}",
                    f"max={stats_map['max']}",
                    f"mean={stats_map['mean']:.3f}",
                ]
            ),
            transform=cdf_axis.transAxes,
            ha="right",
            va="top",
            fontsize=9,
            bbox={"boxstyle": "round", "facecolor": "white", "alpha": 0.9, "edgecolor": "#9ca3af"},
        )
        quantile_axis.plot(pct, xs, color=color, linewidth=1.4)
        quantile_axis.set_title(f"{title} percentile curve")
        quantile_axis.set_xlabel("Percentile")
        quantile_axis.set_ylabel("Value")
        quantile_axis.set_yscale("symlog", linthresh=1.0)
        quantile_axis.set_xlim(0.0, 100.0)
        quantile_axis.grid(True, alpha=0.25)

    fig.savefig(output_svg_path, format="svg")
    fig.savefig(output_png_path, format="png", dpi=220)
    plt.close(fig)
    print(f"dominant_mpi_test_plot_token_id={token_id} timestamp_entries={len(timestamps)} svg_output={output_svg_path} png_output={output_png_path}")


def plot_dominant_mpi_test_timestamp_deltas(mpi_test_sequences, trace_file):
    if not mpi_test_sequences:
        print("No MPI_Test sequences available for timestamp delta analysis.")
        return

    dominant_sequence = max(
        mpi_test_sequences,
        key=lambda seq: len(vector_to_list(safe_getattr(seq, "timestamps"))),
    )
    token_id = safe_getattr(safe_getattr(dominant_sequence, "id"), "id")
    timestamps = vector_to_list(safe_getattr(dominant_sequence, "timestamps"))
    if len(timestamps) < 3:
        print("Dominant MPI_Test sequence does not expose enough timestamps for delta analysis.")
        return

    deltas = [later - earlier for earlier, later in zip(timestamps[:-1], timestamps[1:])]
    delta_of_deltas = [later - earlier for earlier, later in zip(deltas[:-1], deltas[1:])]
    if not deltas or not delta_of_deltas:
        print("Dominant MPI_Test sequence does not expose enough timestamp deltas for analysis.")
        return

    output_svg_path = trace_file.parent / f"mpi_test_token_{token_id}_timestamp_deltas.svg"
    output_png_path = trace_file.parent / f"mpi_test_token_{token_id}_timestamp_deltas.png"
    output_log_path = trace_file.parent / f"mpi_test_token_{token_id}_timestamp_deltas.log"
    os.environ.setdefault("MPLCONFIGDIR", "/tmp/matplotlib-pallas")

    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    def summarize(values):
        ordered = sorted(values)
        return {
            "count": len(values),
            "min": ordered[0],
            "p50": ordered[len(ordered) // 2],
            "p90": ordered[min(len(ordered) - 1, int(len(ordered) * 0.90))],
            "p99": ordered[min(len(ordered) - 1, int(len(ordered) * 0.99))],
            "max": ordered[-1],
            "mean": statistics.fmean(values),
            "zero_count": sum(1 for value in values if value == 0),
        }

    def sampled_series(values, max_points=20000):
        count = len(values)
        if count <= max_points:
            indices = list(range(count))
        else:
            step = (count - 1) / (max_points - 1)
            indices = [round(i * step) for i in range(max_points)]
        return indices, [values[index] for index in indices]

    def sampled_curve(values, max_points=20000):
        ordered = sorted(values)
        count = len(ordered)
        if count == 1:
            return ordered, [1.0]
        if count <= max_points:
            indices = list(range(count))
        else:
            step = (count - 1) / (max_points - 1)
            indices = [round(i * step) for i in range(max_points)]
        xs = [ordered[index] for index in indices]
        ys = [index / (count - 1) for index in indices]
        return xs, ys

    def top_counts(values, limit=10):
        return Counter(values).most_common(limit)

    delta_stats = summarize(deltas)
    delta_of_delta_stats = summarize(delta_of_deltas)
    delta_indices, delta_sample = sampled_series(deltas)
    delta_of_delta_indices, delta_of_delta_sample = sampled_series(delta_of_deltas)
    delta_curve_x, delta_curve_y = sampled_curve(deltas)
    delta_of_delta_curve_x, delta_of_delta_curve_y = sampled_curve(delta_of_deltas)

    fig, axes = plt.subplots(2, 2, figsize=(14, 9), constrained_layout=True)
    fig.suptitle(
        "Dominant MPI_Test timestamp delta analysis\n"
        f"token_id={token_id} timestamp_entries={len(timestamps)} "
        f"delta_entries={len(deltas)} delta_of_delta_entries={len(delta_of_deltas)}"
    )

    plot_specs = [
        (axes[0][0], axes[0][1], delta_indices, delta_sample, delta_curve_x, delta_curve_y, delta_stats, "Timestamp deltas", "#2563eb"),
        (axes[1][0], axes[1][1], delta_of_delta_indices, delta_of_delta_sample, delta_of_delta_curve_x, delta_of_delta_curve_y, delta_of_delta_stats, "Delta of deltas", "#dc2626"),
    ]

    for series_axis, cdf_axis, indices, sample_values, curve_x, curve_y, stats_map, title, color in plot_specs:
        series_axis.plot(indices, sample_values, color=color, linewidth=0.8)
        series_axis.set_title(f"{title} sampled over occurrence index")
        series_axis.set_xlabel("Occurrence index")
        series_axis.set_ylabel("Value")
        series_axis.set_yscale("symlog", linthresh=1.0)
        series_axis.grid(True, alpha=0.25)
        series_axis.text(
            0.985,
            0.95,
            "\n".join(
                [
                    f"count={stats_map['count']}",
                    f"min={stats_map['min']}",
                    f"p50={stats_map['p50']}",
                    f"p90={stats_map['p90']}",
                    f"p99={stats_map['p99']}",
                    f"max={stats_map['max']}",
                    f"mean={stats_map['mean']:.3f}",
                    f"zero_count={stats_map['zero_count']}",
                ]
            ),
            transform=series_axis.transAxes,
            ha="right",
            va="top",
            fontsize=9,
            bbox={"boxstyle": "round", "facecolor": "white", "alpha": 0.9, "edgecolor": "#9ca3af"},
        )

        cdf_axis.plot(curve_x, curve_y, color=color, linewidth=1.4)
        cdf_axis.set_title(f"{title} ECDF")
        cdf_axis.set_xlabel("Value")
        cdf_axis.set_ylabel("Cumulative fraction")
        cdf_axis.set_xscale("symlog", linthresh=1.0)
        cdf_axis.set_ylim(0.0, 1.0)
        cdf_axis.grid(True, alpha=0.25)

    fig.savefig(output_svg_path, format="svg")
    fig.savefig(output_png_path, format="png", dpi=220)
    plt.close(fig)

    log_lines = [
        f"token_id={token_id}",
        f"timestamp_entries={len(timestamps)}",
        f"delta_entries={len(deltas)}",
        f"delta_of_delta_entries={len(delta_of_deltas)}",
        "",
        "[delta_stats]",
        f"min={delta_stats['min']}",
        f"p50={delta_stats['p50']}",
        f"p90={delta_stats['p90']}",
        f"p99={delta_stats['p99']}",
        f"max={delta_stats['max']}",
        f"mean={delta_stats['mean']:.6f}",
        f"zero_count={delta_stats['zero_count']}",
        f"zero_fraction={delta_stats['zero_count'] / len(deltas):.6f}",
        f"top_counts={top_counts(deltas)}",
        "",
        "[delta_of_delta_stats]",
        f"min={delta_of_delta_stats['min']}",
        f"p50={delta_of_delta_stats['p50']}",
        f"p90={delta_of_delta_stats['p90']}",
        f"p99={delta_of_delta_stats['p99']}",
        f"max={delta_of_delta_stats['max']}",
        f"mean={delta_of_delta_stats['mean']:.6f}",
        f"zero_count={delta_of_delta_stats['zero_count']}",
        f"zero_fraction={delta_of_delta_stats['zero_count'] / len(delta_of_deltas):.6f}",
        f"top_counts={top_counts(delta_of_deltas)}",
        "",
        f"first_20_timestamps={timestamps[:20]}",
        f"first_20_deltas={deltas[:20]}",
        f"first_20_delta_of_deltas={delta_of_deltas[:20]}",
    ]
    output_log_path.write_text("\n".join(log_lines) + "\n", encoding="utf-8")
    print(f"dominant_mpi_test_timestamp_delta_token_id={token_id} svg_output={output_svg_path} png_output={output_png_path} log_output={output_log_path}")


def plot_mpi_test_subarray_timestamp_deltas(mpi_test_sequences, trace_file, batch_size=DEFAULT_SUBARRAY_BATCH_SIZE):
    if not mpi_test_sequences:
        print("No MPI_Test sequences available for subarray-level timestamp delta analysis.")
        return

    subarray_records = []
    pooled_deltas = []
    pooled_delta_of_deltas = []

    for sequence in mpi_test_sequences:
        token_id = safe_getattr(safe_getattr(sequence, "id"), "id")
        sequence_name = safe_getattr(sequence, "guessName")
        if callable(sequence_name):
            try:
                sequence_name = sequence_name()
            except Exception:
                sequence_name = None
        timestamps = vector_to_list(safe_getattr(sequence, "timestamps"))
        if len(timestamps) < 3:
            continue

        for block_index, start in enumerate(range(0, len(timestamps), batch_size)):
            subarray_values = timestamps[start:start + batch_size]
            if len(subarray_values) < 3:
                continue

            deltas = [later - earlier for earlier, later in zip(subarray_values[:-1], subarray_values[1:])]
            delta_of_deltas = [later - earlier for earlier, later in zip(deltas[:-1], deltas[1:])]
            if not deltas or not delta_of_deltas:
                continue

            pooled_deltas.extend(deltas)
            pooled_delta_of_deltas.extend(delta_of_deltas)
            subarray_records.append(
                {
                    "token_id": token_id,
                    "sequence_name": sequence_name,
                    "block_index": block_index,
                    "start_offset": start,
                    "value_count": len(subarray_values),
                    "delta_count": len(deltas),
                    "delta_of_delta_count": len(delta_of_deltas),
                    "delta_zero_count": sum(1 for value in deltas if value == 0),
                    "delta_of_delta_zero_count": sum(1 for value in delta_of_deltas if value == 0),
                    "first_values": subarray_values[:8],
                    "first_deltas": deltas[:8],
                    "first_delta_of_deltas": delta_of_deltas[:8],
                }
            )

    if not pooled_deltas or not pooled_delta_of_deltas:
        print("No subarray-sized timestamp batches exposed enough values for delta analysis.")
        return

    output_png_path = trace_file.parent / "mpi_test_subarray_timestamp_deltas.png"
    output_log_path = trace_file.parent / "mpi_test_subarray_timestamp_deltas.log"
    os.environ.setdefault("MPLCONFIGDIR", "/tmp/matplotlib-pallas")

    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    def summarize(values):
        ordered = sorted(values)
        return {
            "count": len(values),
            "min": ordered[0],
            "p50": ordered[len(ordered) // 2],
            "p90": ordered[min(len(ordered) - 1, int(len(ordered) * 0.90))],
            "p99": ordered[min(len(ordered) - 1, int(len(ordered) * 0.99))],
            "max": ordered[-1],
            "mean": statistics.fmean(values),
            "zero_count": sum(1 for value in values if value == 0),
        }

    def sampled_series(values, max_points=20000):
        count = len(values)
        if count <= max_points:
            indices = list(range(count))
        else:
            step = (count - 1) / (max_points - 1)
            indices = [round(i * step) for i in range(max_points)]
        return indices, [values[index] for index in indices]

    def sampled_curve(values, max_points=20000):
        ordered = sorted(values)
        count = len(ordered)
        if count == 1:
            return ordered, [1.0]
        if count <= max_points:
            indices = list(range(count))
        else:
            step = (count - 1) / (max_points - 1)
            indices = [round(i * step) for i in range(max_points)]
        xs = [ordered[index] for index in indices]
        ys = [index / (count - 1) for index in indices]
        return xs, ys

    def top_counts(values, limit=10):
        return Counter(values).most_common(limit)

    delta_stats = summarize(pooled_deltas)
    delta_of_delta_stats = summarize(pooled_delta_of_deltas)
    delta_indices, delta_sample = sampled_series(pooled_deltas)
    delta_of_delta_indices, delta_of_delta_sample = sampled_series(pooled_delta_of_deltas)
    delta_curve_x, delta_curve_y = sampled_curve(pooled_deltas)
    delta_of_delta_curve_x, delta_of_delta_curve_y = sampled_curve(pooled_delta_of_deltas)

    fig, axes = plt.subplots(2, 2, figsize=(14, 9), constrained_layout=True)
    fig.suptitle(
        "MPI_Test subarray-level timestamp delta analysis\n"
        f"batch_size={batch_size} subarrays={len(subarray_records)} "
        f"delta_entries={len(pooled_deltas)} delta_of_delta_entries={len(pooled_delta_of_deltas)}"
    )

    plot_specs = [
        (axes[0][0], axes[0][1], delta_indices, delta_sample, delta_curve_x, delta_curve_y, delta_stats, "Subarray timestamp deltas", "#2563eb"),
        (axes[1][0], axes[1][1], delta_of_delta_indices, delta_of_delta_sample, delta_of_delta_curve_x, delta_of_delta_curve_y, delta_of_delta_stats, "Subarray delta of deltas", "#dc2626"),
    ]

    for series_axis, cdf_axis, indices, sample_values, curve_x, curve_y, stats_map, title, color in plot_specs:
        series_axis.plot(indices, sample_values, color=color, linewidth=0.8)
        series_axis.set_title(f"{title} sampled over pooled occurrence index")
        series_axis.set_xlabel("Pooled occurrence index")
        series_axis.set_ylabel("Value")
        series_axis.set_yscale("symlog", linthresh=1.0)
        series_axis.grid(True, alpha=0.25)
        series_axis.text(
            0.985,
            0.95,
            "\n".join(
                [
                    f"count={stats_map['count']}",
                    f"min={stats_map['min']}",
                    f"p50={stats_map['p50']}",
                    f"p90={stats_map['p90']}",
                    f"p99={stats_map['p99']}",
                    f"max={stats_map['max']}",
                    f"mean={stats_map['mean']:.3f}",
                    f"zero_count={stats_map['zero_count']}",
                ]
            ),
            transform=series_axis.transAxes,
            ha="right",
            va="top",
            fontsize=9,
            bbox={"boxstyle": "round", "facecolor": "white", "alpha": 0.9, "edgecolor": "#9ca3af"},
        )

        cdf_axis.plot(curve_x, curve_y, color=color, linewidth=1.4)
        cdf_axis.set_title(f"{title} ECDF")
        cdf_axis.set_xlabel("Value")
        cdf_axis.set_ylabel("Cumulative fraction")
        cdf_axis.set_xscale("symlog", linthresh=1.0)
        cdf_axis.set_ylim(0.0, 1.0)
        cdf_axis.grid(True, alpha=0.25)

    fig.savefig(output_png_path, format="png", dpi=220)
    plt.close(fig)

    log_lines = [
        f"batch_size={batch_size}",
        f"subarray_count={len(subarray_records)}",
        f"delta_entries={len(pooled_deltas)}",
        f"delta_of_delta_entries={len(pooled_delta_of_deltas)}",
        "",
        "[delta_stats]",
        f"min={delta_stats['min']}",
        f"p50={delta_stats['p50']}",
        f"p90={delta_stats['p90']}",
        f"p99={delta_stats['p99']}",
        f"max={delta_stats['max']}",
        f"mean={delta_stats['mean']:.6f}",
        f"zero_count={delta_stats['zero_count']}",
        f"zero_fraction={delta_stats['zero_count'] / len(pooled_deltas):.6f}",
        f"top_counts={top_counts(pooled_deltas)}",
        "",
        "[delta_of_delta_stats]",
        f"min={delta_of_delta_stats['min']}",
        f"p50={delta_of_delta_stats['p50']}",
        f"p90={delta_of_delta_stats['p90']}",
        f"p99={delta_of_delta_stats['p99']}",
        f"max={delta_of_delta_stats['max']}",
        f"mean={delta_of_delta_stats['mean']:.6f}",
        f"zero_count={delta_of_delta_stats['zero_count']}",
        f"zero_fraction={delta_of_delta_stats['zero_count'] / len(pooled_delta_of_deltas):.6f}",
        f"top_counts={top_counts(pooled_delta_of_deltas)}",
        "",
        "[subarray_records]",
    ]
    for record in subarray_records:
        log_lines.extend(
            [
                (
                    f"token_id={record['token_id']} sequence_name={record['sequence_name']} "
                    f"block_index={record['block_index']} start_offset={record['start_offset']} "
                    f"value_count={record['value_count']} delta_count={record['delta_count']} "
                    f"delta_zero_count={record['delta_zero_count']} "
                    f"delta_of_delta_count={record['delta_of_delta_count']} "
                    f"delta_of_delta_zero_count={record['delta_of_delta_zero_count']}"
                ),
                f"  first_values={record['first_values']}",
                f"  first_deltas={record['first_deltas']}",
                f"  first_delta_of_deltas={record['first_delta_of_deltas']}",
            ]
        )
    output_log_path.write_text("\n".join(log_lines) + "\n", encoding="utf-8")
    print(f"mpi_test_subarray_timestamp_delta_analysis png_output={output_png_path} log_output={output_log_path}")


def print_duration_analysis(thread, trace_file):
    print("=== Duration / Time-Series Analysis ===")
    if thread is None:
        print_unavailable("duration analysis")
        return

    events = list(safe_getattr(thread, "events", []) or [])
    sequences = list(safe_getattr(thread, "sequences", []) or [])

    event_duration_proxy = []
    event_timestamps = []
    for event in events:
        timestamps = vector_to_list(safe_getattr(event, "timestamps"))
        if timestamps:
            event_timestamps.extend(timestamps)
            if len(timestamps) >= 2:
                event_duration_proxy.extend(later - earlier for earlier, later in zip(timestamps[:-1], timestamps[1:]))

    sequence_durations = []
    sequence_timestamps = []
    sequence_exclusive_durations = []
    for sequence in sequences:
        sequence_durations.extend(vector_to_list(safe_getattr(sequence, "durations")))
        sequence_timestamps.extend(vector_to_list(safe_getattr(sequence, "timestamps")))
        sequence_exclusive_durations.extend(vector_to_list(safe_getattr(sequence, "exclusive_durations")))

    print(f"event_timestamp_entries={len(event_timestamps)}")
    if event_duration_proxy:
        summarize_numeric_series(event_duration_proxy, "within_event_timestamp_gaps")
    else:
        print_unavailable("event durations (only timestamps are exposed on Event)")

    print(f"sequence_duration_entries={len(sequence_durations)}")
    summarize_numeric_series(sequence_durations, "sequence_durations")
    print(f"sequence_timestamp_entries={len(sequence_timestamps)}")
    summarize_numeric_series(sequence_timestamps, "sequence_timestamps")
    print(f"sequence_exclusive_duration_entries={len(sequence_exclusive_durations)}")
    summarize_numeric_series(sequence_exclusive_durations, "sequence_exclusive_durations")

    mpi_test_sequences = []
    for sequence in sequences:
        guess = safe_getattr(sequence, "guessName")
        name = None
        if callable(guess):
            try:
                name = guess()
            except Exception:
                name = None
        if name and "MPI_Test" in name:
            mpi_test_sequences.append(sequence)

    if mpi_test_sequences:
        print("mpi_test_sequence_summaries:")
        ranked = sorted(mpi_test_sequences, key=lambda seq: safe_getattr(seq, "n_iterations", 0) or 0, reverse=True)
        for sequence in ranked[:10]:
            durations = vector_to_list(safe_getattr(sequence, "durations"))
            timestamps = vector_to_list(safe_getattr(sequence, "timestamps"))
            mean_duration = f"{statistics.fmean(durations):.3f}" if durations else "None"
            print(
                f"  name={sequence.guessName()} token_id={safe_getattr(safe_getattr(sequence, 'id'), 'id')} "
                f"iterations={safe_getattr(sequence, 'n_iterations')} duration_entries={len(durations)} "
                f"timestamp_entries={len(timestamps)} min={min(durations) if durations else None} "
                f"max={max(durations) if durations else None} mean={mean_duration}"
            )
        write_mpi_test_sequence_grammar_logs(ranked, trace_file)
        # plot_dominant_mpi_test_sequence_distributions(ranked, trace_file)
        # plot_dominant_mpi_test_timestamp_deltas(ranked, trace_file)
        # plot_mpi_test_subarray_timestamp_deltas(ranked, trace_file)
    else:
        print("No MPI_Test sequences found in selected thread.")

