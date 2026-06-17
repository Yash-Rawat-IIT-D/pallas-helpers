#!/usr/bin/env python3

import argparse
import ctypes
import importlib
import math
import os
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PALLAS_LIB_CANDIDATES = (
    ROOT / "pallas" / "install-pallas" / "lib" / "libpallas.so",
    ROOT / "pallas" / "install-pallas" / "lib64" / "libpallas.so",
    ROOT / "pallas" / "build-pallas" / "libraries" / "pallas" / "libpallas.so",
)
PALLAS_TRACE_PATH_CANDIDATES = (
    ROOT / "pallas" / "libraries" / "pallas_python",
)


def preload_pallas_library():
    for candidate in PALLAS_LIB_CANDIDATES:
        if not candidate.exists():
            continue
        lib_dir = str(candidate.parent)
        current = os.environ.get("LD_LIBRARY_PATH", "")
        if lib_dir not in current.split(":"):
            os.environ["LD_LIBRARY_PATH"] = f"{lib_dir}:{current}" if current else lib_dir
        ctypes.CDLL(str(candidate), mode=ctypes.RTLD_GLOBAL)
        return candidate
    return None


def add_local_pallas_trace_path():
    for candidate in PALLAS_TRACE_PATH_CANDIDATES:
        if candidate.exists():
            candidate_str = str(candidate)
            if candidate_str not in sys.path:
                sys.path.insert(0, candidate_str)
            return candidate
    return None


def import_pallas_trace():
    try:
        return importlib.import_module("pallas_trace")
    except ModuleNotFoundError as exc:
        if exc.name != "pallas_trace":
            raise
        add_local_pallas_trace_path()
        return importlib.import_module("pallas_trace")


def load_pallas_trace_module():
    try:
        return importlib.import_module("pallas_trace")
    except ImportError:
        preload_pallas_library()
        return import_pallas_trace()


def parse_args():
    parser = argparse.ArgumentParser(
        description="Print raw linked-vector/subarray stats for the largest Pallas events, sequences, and loops."
    )
    parser.add_argument("trace_path", help="Path to a trace root, archive directory, or .pallas file.")
    parser.add_argument("--archive", type=int, default=1, help="Archive id or index to inspect. Defaults to 1.")
    parser.add_argument("--thread", type=int, default=0, help="Thread id or index to inspect. Defaults to 0.")
    parser.add_argument("--top", type=int, default=5, help="How many largest entries to print per category.")
    parser.add_argument("--deep-sequence-id", type=int, default=3, help="Sequence id to inspect in detail. Defaults to 3.")
    parser.add_argument("--preview-count", type=int, default=64, help="How many timestamp/duration values to preview in the deep dive.")
    parser.add_argument("--plot-dir", default=None, help="Directory where ECDF plots should be saved. Defaults to <trace-parent>/analysis_plots.")
    parser.add_argument("--show-bokeh", action="store_true", help="Open the generated Bokeh HTML in a browser.")
    parser.add_argument("--plot-max-points", type=int, default=(1 << 20), help="Maximum number of plotted points per series after downsampling. Defaults to 2^20.")
    parser.add_argument("--print-raw-data", action="store_true", help="Print raw preview arrays for the deep-dive sequence.")
    return parser.parse_args()


def resolve_trace_file(input_path):
    path = Path(input_path).expanduser()
    if not path.exists():
        raise FileNotFoundError(f"path does not exist: {path}")

    if path.is_file():
        if path.name == "archive.pallas":
            parent_trace = path.parent.parent / "eztrace_log.pallas"
            if parent_trace.exists():
                return parent_trace.resolve()
        return path.resolve()

    preferred = path / "eztrace_log.pallas"
    if preferred.exists():
        return preferred.resolve()

    if path.name.startswith("archive_") or path.name.startswith("archive-"):
        parent_trace = path.parent / "eztrace_log.pallas"
        if parent_trace.exists():
            return parent_trace.resolve()
        archive_file = path / "archive.pallas"
        if archive_file.exists():
            return archive_file.resolve()

    candidates = sorted(path.glob("*.pallas"))
    if len(candidates) == 1:
        return candidates[0].resolve()
    if candidates:
        for candidate in candidates:
            if candidate.name == "eztrace_log.pallas":
                return candidate.resolve()
        return candidates[0].resolve()

    raise FileNotFoundError(f"could not resolve a .pallas trace file from: {path}")


def safe_getattr(obj, name, default=None):
    try:
        return getattr(obj, name)
    except Exception:
        return default


def import_numpy():
    try:
        import numpy as np
    except ImportError as exc:
        raise RuntimeError(
            "numpy is required for delta / delta-of-delta analysis. Please install it in the active environment."
        ) from exc
    return np


def import_bokeh():
    try:
        from bokeh.io import output_file, save, show
        from bokeh.layouts import gridplot, column
        from bokeh.models import ColumnDataSource, Div, HoverTool, TabPanel, Tabs
        from bokeh.plotting import figure
    except ImportError as exc:
        raise RuntimeError(
            "bokeh is required to generate interactive ECDF graphs. Please install it in the active environment."
        ) from exc
    return output_file, save, show, gridplot, column, ColumnDataSource, Div, HoverTool, TabPanel, Tabs, figure


def select_archive(trace, selector):
    archives = list(safe_getattr(trace, "archives", []) or [])
    if not archives:
        raise RuntimeError("trace has no archives")

    for archive in archives:
        if safe_getattr(archive, "id") == selector:
            return archive

    if 0 <= selector < len(archives):
        return archives[selector]

    return archives[0]


def select_thread(archive, selector):
    threads = list(safe_getattr(archive, "threads", []) or [])
    if not threads:
        raise RuntimeError("archive has no threads")

    for thread in threads:
        if safe_getattr(thread, "id") == selector:
            return thread

    if 0 <= selector < len(threads):
        return threads[selector]

    return threads[0]


def policy_label(policy):
    name = safe_getattr(policy, "name")
    if name:
        return str(name)
    text = str(policy)
    if "." in text:
        return text.split(".")[-1]
    return text


def summarize_vector(vector):
    logical_size = int(safe_getattr(vector, "size", 0) or 0)
    subarray_policies = list(safe_getattr(vector, "subarray_policies", []) or [])
    subarray_count = len(subarray_policies)
    average_subarray_size = (logical_size / subarray_count) if subarray_count else 0.0
    preferred_policy = policy_label(safe_getattr(vector, "preferred_subarray_policy", "unknown"))
    policy_counts = Counter(policy_label(policy) for policy in subarray_policies)
    return {
        "logical_size": logical_size,
        "subarray_count": subarray_count,
        "average_subarray_size": average_subarray_size,
        "preferred_policy": preferred_policy,
        "policy_counts": dict(sorted(policy_counts.items())),
    }


def format_policy_counts(policy_counts):
    if not policy_counts:
        return "{}"
    return "{" + ", ".join(f"{key}:{value}" for key, value in policy_counts.items()) + "}"


def print_vector_summary(indent, label, vector):
    summary = summarize_vector(vector)
    print(
        f"{indent}{label}: size={summary['logical_size']} "
        f"subarrays={summary['subarray_count']} "
        f"avg_subarray_size={summary['average_subarray_size']:.2f} "
        f"preferred_policy={summary['preferred_policy']} "
        f"policies={format_policy_counts(summary['policy_counts'])}"
    )
    return summary


def event_total_size(event):
    return int(event.timestamps.size)


def sequence_total_size(sequence):
    return int(sequence.timestamps.size + sequence.durations.size + sequence.exclusive_durations.size)


def loop_total_size(loop):
    return sequence_total_size(loop.sequence)


def vector_preview(vector, count):
    limit = min(int(vector.size), count)
    return [vector[i] for i in range(limit)]


def vector_to_numpy(vector):
    np = import_numpy()
    values = vector.as_numpy_array()
    return np.asarray(values, dtype=np.uint64).astype(np.int64, copy=False)


def first_window_with_max_at_most(values, window_size, threshold):
    if len(values) < window_size:
        return None
    for start in range(0, len(values) - window_size + 1):
        window_max = max(values[start:start + window_size])
        if window_max <= threshold:
            return start, window_max
    return None


def series_stats(values):
    np = import_numpy()
    if values.size == 0:
        return None
    return {
        "count": int(values.size),
        "min": int(values.min()),
        "max": int(values.max()),
        "mean": float(values.mean()),
        "std": float(values.std()),
        "p50": float(np.percentile(values, 50)),
        "p90": float(np.percentile(values, 90)),
        "p99": float(np.percentile(values, 99)),
        "negative_fraction": float((values < 0).mean()),
        "zero_fraction": float((values == 0).mean()),
        "positive_fraction": float((values > 0).mean()),
    }


def print_series_stats(indent, label, values):
    stats = series_stats(values)
    if stats is None:
        print(f"{indent}{label}: no data")
        return
    print(
        f"{indent}{label}: count={stats['count']} min={stats['min']} max={stats['max']} "
        f"mean={stats['mean']:.3f} std={stats['std']:.3f} "
        f"p50={stats['p50']:.3f} p90={stats['p90']:.3f} p99={stats['p99']:.3f} "
        f"neg={stats['negative_fraction']:.4f} zero={stats['zero_fraction']:.4f} pos={stats['positive_fraction']:.4f}"
    )


def compute_delta_series(values):
    np = import_numpy()
    delta = np.diff(values) if values.size >= 2 else np.array([], dtype=np.int64)
    delta_of_delta = np.diff(delta) if delta.size >= 2 else np.array([], dtype=np.int64)
    return delta, delta_of_delta


def downsample_xy(x_values, y_values, max_points):
    if max_points <= 0 or x_values.size <= max_points:
        return x_values, y_values
    stride = max(1, math.ceil(x_values.size / max_points))
    return x_values[::stride], y_values[::stride]


def sample_series(values, max_points):
    np = import_numpy()
    if values.size == 0:
        return np.array([], dtype=np.float64), np.array([], dtype=np.float64)
    x_values = np.arange(values.size, dtype=np.float64)
    y_values = values.astype(np.float64, copy=False)
    return downsample_xy(x_values, y_values, max_points)


def ecdf_xy(values, max_points):
    np = import_numpy()
    if values.size == 0:
        return np.array([], dtype=np.float64), np.array([], dtype=np.float64)
    unique_values, counts = np.unique(values, return_counts=True)
    ecdf_y = np.cumsum(counts, dtype=np.float64) / values.size
    return downsample_xy(unique_values.astype(np.float64, copy=False), ecdf_y, max_points)


def print_top_events(thread, top):
    events = sorted(list(thread.events), key=event_total_size, reverse=True)
    print(f"\nTop {min(top, len(events))} events by timestamp vector size")
    for index, event in enumerate(events[:top], start=1):
        name = safe_getattr(event, "guessName", lambda: "<unknown>")()
        record = safe_getattr(event, "record", "<unknown>")
        print(f"\n[{index}] Event id={event.id.id} name={name} record={record}")
        print_vector_summary("  ", "timestamps", event.timestamps)


def print_top_sequences(thread, top):
    sequences = sorted(list(thread.sequences), key=sequence_total_size, reverse=True)
    print(f"\nTop {min(top, len(sequences))} sequences by total LV size")
    for index, sequence in enumerate(sequences[:top], start=1):
        total_size = sequence_total_size(sequence)
        name = safe_getattr(sequence, "guessName", lambda: "<unknown>")()
        token_count = len(list(safe_getattr(sequence, "tokens", []) or []))
        print(
            f"\n[{index}] Sequence id={sequence.id.id} name={name} "
            f"total_size={total_size} n_iterations={sequence.n_iterations} tokens={token_count}"
        )
        ts_summary = print_vector_summary("  ", "timestamps", sequence.timestamps)
        dur_summary = print_vector_summary("  ", "durations", sequence.durations)
        ex_summary = print_vector_summary("  ", "exclusive_durations", sequence.exclusive_durations)
        total_subarrays = (
            ts_summary["subarray_count"] +
            dur_summary["subarray_count"] +
            ex_summary["subarray_count"]
        )
        average_subarray_size = (total_size / total_subarrays) if total_subarrays else 0.0
        print(
            f"  combined: total_size={total_size} subarrays={total_subarrays} "
            f"avg_subarray_size={average_subarray_size:.2f}"
        )


def print_top_loops(thread, top):
    loops = sorted(list(thread.loops), key=loop_total_size, reverse=True)
    print(f"\nTop {min(top, len(loops))} loops by repeated-sequence LV size")
    for index, loop in enumerate(loops[:top], start=1):
        sequence = loop.sequence
        total_size = sequence_total_size(sequence)
        name = safe_getattr(sequence, "guessName", lambda: "<unknown>")()
        print(
            f"\n[{index}] Loop id={loop.id.id} sequence_id={sequence.id.id} "
            f"sequence_name={name} nb_iterations={loop.nb_iterations} total_size={total_size}"
        )
        ts_summary = print_vector_summary("  ", "timestamps", sequence.timestamps)
        dur_summary = print_vector_summary("  ", "durations", sequence.durations)
        ex_summary = print_vector_summary("  ", "exclusive_durations", sequence.exclusive_durations)
        total_subarrays = (
            ts_summary["subarray_count"] +
            dur_summary["subarray_count"] +
            ex_summary["subarray_count"]
        )
        average_subarray_size = (total_size / total_subarrays) if total_subarrays else 0.0
        print(
            f"  combined: total_size={total_size} subarrays={total_subarrays} "
            f"avg_subarray_size={average_subarray_size:.2f}"
        )


def print_sequence_deep_dive(thread, sequence_id, preview_count, print_raw_data):
    target = None
    for sequence in list(thread.sequences):
        if sequence.id.id == sequence_id:
            target = sequence
            break

    if target is None:
        print(f"\nDeep dive sequence id={sequence_id}: not found")
        return

    name = safe_getattr(target, "guessName", lambda: "<unknown>")()
    print(f"\nDeep dive for sequence id={sequence_id} name={name}")
    print_vector_summary("  ", "timestamps", target.timestamps)
    print_vector_summary("  ", "durations", target.durations)
    print_vector_summary("  ", "exclusive_durations", target.exclusive_durations)

    if print_raw_data:
        timestamps_preview = vector_preview(target.timestamps, preview_count)
        durations_preview = vector_preview(target.durations, preview_count)
        exclusive_preview = vector_preview(target.exclusive_durations, preview_count)
        print(f"  timestamps_first_{len(timestamps_preview)}={timestamps_preview}")
        print(f"  durations_first_{len(durations_preview)}={durations_preview}")
        print(f"  exclusive_durations_first_{len(exclusive_preview)}={exclusive_preview}")
    else:
        durations_preview = vector_preview(target.durations, preview_count)

    if durations_preview:
        print(
            f"  durations_preview_stats: min={min(durations_preview)} "
            f"max={max(durations_preview)} mean={sum(durations_preview) / len(durations_preview):.3f}"
        )

    hot_loop_window = 64
    hot_loop_threshold = 300
    analysis_values = vector_to_numpy(target.durations)
    if len(analysis_values) >= hot_loop_window:
        first_window = analysis_values[:hot_loop_window]
        print(
            f"  hot_loop_window[0:{hot_loop_window - 1}]_stats: "
            f"min={min(first_window)} max={max(first_window)}"
        )
        first_good_window = first_window_with_max_at_most(
            analysis_values, hot_loop_window, hot_loop_threshold
        )
        if first_good_window is None:
            print(
                f"  first_window_with_max<= {hot_loop_threshold}: not found "
                f"in first {len(analysis_values)} durations"
            )
        else:
            start, window_max = first_good_window
            preview = analysis_values[start:start + min(12, hot_loop_window)]
            print(
                f"  first_window_with_max<= {hot_loop_threshold}: "
                f"start={start} max={window_max} preview={preview}"
            )


def build_bokeh_ecdf_figure(title, values, max_points):
    output_file, save, show, gridplot, column, ColumnDataSource, Div, HoverTool, TabPanel, Tabs, figure = import_bokeh()
    x_values, y_values = ecdf_xy(values, max_points)
    plot = figure(
        title=title,
        width=720,
        height=320,
        tools="pan,wheel_zoom,box_zoom,reset,save",
        active_scroll="wheel_zoom",
    )
    if x_values.size == 0:
        plot.text(x=[0], y=[0.5], text=["no data"])
        return plot

    source = ColumnDataSource({"x": x_values, "y": y_values})
    renderer = plot.line("x", "y", source=source, line_width=2)
    plot.xaxis.axis_label = "value"
    plot.yaxis.axis_label = "ECDF"
    plot.add_tools(HoverTool(renderers=[renderer], tooltips=[("value", "@x{0,0.###}"), ("ecdf", "@y{0.000000}")]))
    return plot


def build_bokeh_series_figure(title, values, max_points):
    output_file, save, show, gridplot, column, ColumnDataSource, Div, HoverTool, TabPanel, Tabs, figure = import_bokeh()
    x_values, y_values = sample_series(values, max_points)
    plot = figure(
        title=title,
        width=720,
        height=320,
        tools="pan,wheel_zoom,box_zoom,reset,save",
        active_scroll="wheel_zoom",
    )
    if x_values.size == 0:
        plot.text(x=[0], y=[0.5], text=["no data"])
        return plot

    source = ColumnDataSource({"index": x_values, "value": y_values})
    renderer = plot.line("index", "value", source=source, line_width=1.5)
    plot.xaxis.axis_label = "logical index"
    plot.yaxis.axis_label = "value"
    plot.add_tools(HoverTool(renderers=[renderer], tooltips=[("index", "@index{0,0}"), ("value", "@value{0,0.###}")]))
    return plot


def analyze_sequence_patterns(thread, sequence_id, preview_count, plot_dir, show_bokeh, plot_max_points, print_raw_data):
    target = None
    for sequence in list(thread.sequences):
        if sequence.id.id == sequence_id:
            target = sequence
            break

    if target is None:
        print(f"\nPattern analysis for sequence id={sequence_id}: not found")
        return

    timestamps = vector_to_numpy(target.timestamps)
    durations = vector_to_numpy(target.durations)
    exclusive_durations = vector_to_numpy(target.exclusive_durations)

    series_map = {
        "timestamps": timestamps,
        "durations": durations,
        "exclusive_durations": exclusive_durations,
    }

    print(f"\nPattern analysis for sequence id={sequence_id}")
    for label, values in series_map.items():
        delta, delta_of_delta = compute_delta_series(values)
        if print_raw_data:
            preview_delta = delta[:preview_count].tolist()
            preview_delta_of_delta = delta_of_delta[:preview_count].tolist()
        print_series_stats("  ", f"{label}_delta", delta)
        if print_raw_data:
            print(f"  {label}_delta_first_{len(preview_delta)}={preview_delta}")
        print_series_stats("  ", f"{label}_delta_of_delta", delta_of_delta)
        if print_raw_data:
            print(f"  {label}_delta_of_delta_first_{len(preview_delta_of_delta)}={preview_delta_of_delta}")

    output_file, save, show, gridplot, column, ColumnDataSource, Div, HoverTool, TabPanel, Tabs, figure = import_bokeh()
    rows = [
        ("timestamps", timestamps),
        ("durations", durations),
        ("exclusive_durations", exclusive_durations),
    ]
    ecdf_grid_rows = []
    series_grid_rows = []
    for label, values in rows:
        delta, delta_of_delta = compute_delta_series(values)
        ecdf_grid_rows.append([
            build_bokeh_ecdf_figure(f"{label} delta ECDF", delta, plot_max_points),
            build_bokeh_ecdf_figure(f"{label} delta-of-delta ECDF", delta_of_delta, plot_max_points),
        ])
        series_grid_rows.append([
            build_bokeh_series_figure(f"{label} delta series", delta, plot_max_points),
            build_bokeh_series_figure(f"{label} delta-of-delta series", delta_of_delta, plot_max_points),
        ])

    output_dir = plot_dir
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"sequence_{sequence_id}_delta_ecdfs.html"
    header = Div(text=f"<h2>Sequence {sequence_id} delta / delta-of-delta analysis</h2>")
    summary = Div(text=(
        f"<p>Plots use the full sequence data. Rendering is downsampled only for display, "
        f"with a cap of {plot_max_points:,} points per curve/series.</p>"
    ))
    ecdf_panel = TabPanel(
        child=gridplot(ecdf_grid_rows, toolbar_location="above", merge_tools=True),
        title="ECDFs",
    )
    series_panel = TabPanel(
        child=gridplot(series_grid_rows, toolbar_location="above", merge_tools=True),
        title="Series",
    )
    layout = column(header, summary, Tabs(tabs=[ecdf_panel, series_panel]))
    output_file(output_path, title=f"Sequence {sequence_id} delta ECDFs")
    save(layout)
    print(f"\nSaved interactive Bokeh ECDF plot to: {output_path}")

    if show_bokeh:
        show(layout)


def main():
    args = parse_args()
    pallas_trace = load_pallas_trace_module()
    trace_file = resolve_trace_file(args.trace_path)
    trace = pallas_trace.open_trace(str(trace_file))
    archive = select_archive(trace, args.archive)
    thread = select_thread(archive, args.thread)
    plot_dir = Path(args.plot_dir) if args.plot_dir else trace_file.resolve().parent / "analysis_plots"

    print(f"Trace file: {trace_file}")
    print(f"Archive: id={archive.id} dir={archive.dir_name}")
    print(f"Thread: id={thread.id}")

    print_top_events(thread, args.top)
    print_top_sequences(thread, args.top)
    print_top_loops(thread, args.top)
    print_sequence_deep_dive(thread, args.deep_sequence_id, args.preview_count, args.print_raw_data)
    analyze_sequence_patterns(
        thread,
        args.deep_sequence_id,
        args.preview_count,
        plot_dir,
        args.show_bokeh,
        args.plot_max_points,
        args.print_raw_data,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
