#!/usr/bin/env python3

import argparse
import ctypes
import importlib
import os
import sys
from pathlib import Path

from pla import compute_block_max_abs_error, create_pla_algorithm

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


def import_numpy():
    try:
        import numpy as np
    except ImportError as exc:
        raise RuntimeError(
            "numpy is required for timestamp block viewing. Please install it in the active environment."
        ) from exc
    return np


def import_bokeh():
    try:
        from bokeh.io import output_file, save, show
        from bokeh.layouts import column, row
        from bokeh.models import Button, ColumnDataSource, CustomJS, Div, HoverTool, Range1d, Slider
        from bokeh.plotting import figure
    except ImportError as exc:
        raise RuntimeError(
            "bokeh is required for timestamp block viewing. Please install it in the active environment."
        ) from exc
    return output_file, save, show, column, row, Button, ColumnDataSource, CustomJS, Div, HoverTool, Range1d, Slider, figure


def parse_args():
    parser = argparse.ArgumentParser(
        description="View one timestamp block at a time for the spinloop trace sequence."
    )
    parser.add_argument(
        "trace_path",
        nargs="?",
        help="Optional trace root, archive directory, or .pallas file. If omitted, LOGFILE is used.",
    )
    parser.add_argument("--archive", type=int, default=1, help="Archive id or index to inspect. Defaults to 1.")
    parser.add_argument("--thread", type=int, default=0, help="Thread id or index to inspect. Defaults to 0.")
    parser.add_argument("--sequence-id", type=int, default=3, help="Sequence id to inspect. Defaults to 3.")
    parser.add_argument("--block-size", type=int, default=1000, help="Number of timestamps per viewed block. Defaults to 1000.")
    parser.add_argument("--block-index", type=int, default=0, help="Zero-based block index to view.")
    parser.add_argument(
        "--pla-algorithm",
        default="first-last",
        help="PLA overlay to run per block. Defaults to first-last.",
    )
    parser.add_argument("--plot-dir", default=None, help="Directory where the HTML plot should be saved.")
    parser.add_argument("--show-bokeh", action="store_true", help="Open the generated Bokeh HTML in a browser.")
    return parser.parse_args()


def resolve_input_trace_path(cli_trace_path):
    env_trace_path = os.environ.get("LOGFILE")
    selected_path = env_trace_path or cli_trace_path
    if not selected_path:
        raise RuntimeError(
            "no trace path provided. Set LOGFILE or pass a trace_path argument."
        )
    return selected_path


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


def find_sequence(thread, sequence_id):
    for sequence in list(thread.sequences):
        if sequence.id.id == sequence_id:
            return sequence
    raise RuntimeError(f"sequence id {sequence_id} not found in selected thread")


def vector_to_numpy(vector):
    np = import_numpy()
    return np.asarray(vector.as_numpy_array(), dtype=np.uint64)


def block_bounds(total_size, block_size, block_index):
    if block_size <= 0:
        raise ValueError("block_size must be strictly positive")
    block_count = (total_size + block_size - 1) // block_size
    if block_count == 0:
        raise RuntimeError("selected sequence has no timestamp values")
    if block_index < 0 or block_index >= block_count:
        raise ValueError(f"block_index {block_index} is out of range [0, {block_count - 1}]")
    start = block_index * block_size
    end = min(total_size, start + block_size)
    return start, end, block_count


def padded_range(min_value, max_value):
    if min_value == max_value:
        padding = 1.0 if min_value == 0 else abs(min_value) * 0.01
        return min_value - padding, max_value + padding
    padding = (max_value - min_value) * 0.05
    return min_value - padding, max_value + padding


def build_block_payload(timestamps, start, end):
    np = import_numpy()
    block_timestamps = timestamps[start:end]
    block_indices = np.arange(start, end, dtype=np.int64)
    block_deltas = np.diff(block_timestamps)
    delta_indices = block_indices[1:]
    block_delta_of_deltas = np.abs(np.diff(block_deltas))
    delta_of_delta_indices = block_indices[2:]
    return {
        "indices": block_indices,
        "timestamps": block_timestamps,
        "delta_indices": delta_indices,
        "deltas": block_deltas,
        "delta_of_delta_indices": delta_of_delta_indices,
        "delta_of_deltas": block_delta_of_deltas,
    }


def compute_block_pla_segments(timestamps, block_size, pla_algorithm):
    block_segment_xs = []
    block_segment_ys = []
    block_segments = []
    for block_start in range(0, timestamps.size, block_size):
        block_end = min(timestamps.size, block_start + block_size)
        block_indices = list(range(block_start, block_end))
        block_values = timestamps[block_start:block_end].tolist()
        segments = pla_algorithm.fit(block_indices, block_values)
        block_segments.append(segments)
        block_segment_xs.append(
            [[segment.start_index, segment.end_index] for segment in segments]
        )
        block_segment_ys.append(
            [[segment.start_value, segment.end_value] for segment in segments]
        )
    return block_segments, block_segment_xs, block_segment_ys


def compute_top_block_errors(timestamps, block_size, block_segments, limit=10):
    block_errors = []
    for block_index, segments in enumerate(block_segments):
        block_start = block_index * block_size
        block_end = min(timestamps.size, block_start + block_size)
        block_indices = list(range(block_start, block_end))
        block_values = timestamps[block_start:block_end].tolist()
        error_summary = compute_block_max_abs_error(
            block_index=block_index,
            indices=block_indices,
            values=block_values,
            segments=segments,
        )
        if error_summary is not None:
            block_errors.append(error_summary)
    return sorted(
        block_errors,
        key=lambda item: item.max_abs_error,
        reverse=True,
    )[:limit]


def build_info_html(trace_file, archive_id, thread_id, sequence_id, block_size, block_index, block_count, block_payload, pla_name, pla_segment_count):
    block_timestamps = block_payload["timestamps"]
    return (
        f"<h2>Spinloop timestamp block viewer</h2>"
        f"<p><b>Trace:</b> {trace_file}</p>"
        f"<p><b>Archive:</b> {archive_id} | <b>Thread:</b> {thread_id} | "
        f"<b>Sequence:</b> {sequence_id} | <b>Block size:</b> {block_size} | "
        f"<b>Block index:</b> {block_index} / {block_count - 1}</p>"
        f"<p><b>PLA algorithm:</b> {pla_name} | <b>PLA segments in block:</b> {pla_segment_count}</p>"
        f"<p><b>Window:</b> [{int(block_payload['indices'][0])}, {int(block_payload['indices'][-1]) + 1}) | "
        f"<b>Timestamp range:</b> [{int(block_timestamps.min())}, {int(block_timestamps.max())}]</p>"
    )


def main():
    args = parse_args()
    np = import_numpy()
    output_file, save, show, column, row, Button, ColumnDataSource, CustomJS, Div, HoverTool, Range1d, Slider, figure = import_bokeh()
    pla_algorithm = create_pla_algorithm(args.pla_algorithm)

    pallas_trace = load_pallas_trace_module()
    trace_file = resolve_trace_file(resolve_input_trace_path(args.trace_path))
    trace = pallas_trace.open_trace(str(trace_file))
    archive = select_archive(trace, args.archive)
    thread = select_thread(archive, args.thread)
    sequence = find_sequence(thread, args.sequence_id)

    timestamps = vector_to_numpy(sequence.timestamps).astype(np.int64, copy=False)
    start, end, block_count = block_bounds(timestamps.size, args.block_size, args.block_index)
    initial_block = build_block_payload(timestamps, start, end)
    block_segments, block_segment_xs, block_segment_ys = compute_block_pla_segments(
        timestamps, args.block_size, pla_algorithm
    )
    top_block_errors = compute_top_block_errors(
        timestamps,
        args.block_size,
        block_segments,
    )

    plot_dir = Path(args.plot_dir) if args.plot_dir else trace_file.resolve().parent / "analysis_plots"
    plot_dir.mkdir(parents=True, exist_ok=True)
    output_path = plot_dir / f"sequence_{args.sequence_id}_timestamps_blocks_viewer.html"

    timestamp_source = ColumnDataSource({
        "index": initial_block["indices"].tolist(),
        "timestamp": initial_block["timestamps"].tolist(),
    })

    all_data_source = ColumnDataSource({
        "timestamps": timestamps.tolist(),
        "pla_xs": block_segment_xs,
        "pla_ys": block_segment_ys,
    })

    pla_source = ColumnDataSource({
        "xs": block_segment_xs[args.block_index],
        "ys": block_segment_ys[args.block_index],
    })

    timestamp_plot = figure(
        title=f"Sequence {args.sequence_id} timestamps block viewer with PLA overlay",
        width=1400,
        height=420,
        tools="pan,wheel_zoom,box_zoom,reset,save",
        active_scroll="wheel_zoom",
    )
    timestamp_renderer = timestamp_plot.line("index", "timestamp", source=timestamp_source, line_width=2)
    pla_renderer = timestamp_plot.multi_line(
        xs="xs",
        ys="ys",
        source=pla_source,
        line_width=3,
        line_color="darkorange",
        alpha=0.9,
        legend_label=f"PLA ({pla_algorithm.name})",
    )
    timestamp_plot.circle("index", "timestamp", source=timestamp_source, size=3, alpha=0.5)
    timestamp_plot.xaxis.axis_label = "logical index"
    timestamp_plot.yaxis.axis_label = "timestamp"
    timestamp_plot.legend.location = "top_left"
    timestamp_plot.legend.click_policy = "hide"
    ts_ymin, ts_ymax = padded_range(
        float(initial_block["timestamps"].min()),
        float(initial_block["timestamps"].max()),
    )
    timestamp_plot.y_range = Range1d(ts_ymin, ts_ymax)
    timestamp_plot.add_tools(HoverTool(
        renderers=[timestamp_renderer],
        tooltips=[("logical index", "@index{0,0}"), ("timestamp", "@timestamp{0,0}")]
    ))
    timestamp_plot.add_tools(HoverTool(
        renderers=[pla_renderer],
        tooltips=[("segment start", "$x{0,0}"), ("segment value", "$y{0,0}")]
    ))

    delta_source = ColumnDataSource({
        "index": initial_block["delta_indices"].tolist(),
        "delta": initial_block["deltas"].tolist(),
    })
    delta_of_delta_source = ColumnDataSource({
        "index": initial_block["delta_of_delta_indices"].tolist(),
        "delta_of_delta": initial_block["delta_of_deltas"].tolist(),
    })
    delta_plot = figure(
        title="Sequence timestamp deltas",
        width=1400,
        height=320,
        tools="pan,wheel_zoom,box_zoom,reset,save",
        active_scroll="wheel_zoom",
        x_range=timestamp_plot.x_range,
    )
    delta_renderer = delta_plot.line("index", "delta", source=delta_source, line_width=1.5, color="firebrick")
    delta_plot.circle("index", "delta", source=delta_source, size=3, alpha=0.5, color="firebrick")
    delta_plot.xaxis.axis_label = "logical index"
    delta_plot.yaxis.axis_label = "delta"
    if initial_block["deltas"].size > 0:
        delta_ymin, delta_ymax = padded_range(
            float(initial_block["deltas"].min()),
            float(initial_block["deltas"].max()),
        )
    else:
        delta_ymin, delta_ymax = padded_range(0.0, 1.0)
    delta_plot.y_range = Range1d(delta_ymin, delta_ymax)
    delta_plot.add_tools(HoverTool(
        renderers=[delta_renderer],
        tooltips=[("logical index", "@index{0,0}"), ("delta", "@delta{0,0}")]
    ))

    delta_of_delta_plot = figure(
        title="Sequence absolute timestamp delta-of-delta",
        width=1400,
        height=320,
        tools="pan,wheel_zoom,box_zoom,reset,save",
        active_scroll="wheel_zoom",
        x_range=timestamp_plot.x_range,
    )
    delta_of_delta_renderer = delta_of_delta_plot.line(
        "index",
        "delta_of_delta",
        source=delta_of_delta_source,
        line_width=1.5,
        color="seagreen",
    )
    delta_of_delta_plot.circle(
        "index",
        "delta_of_delta",
        source=delta_of_delta_source,
        size=3,
        alpha=0.5,
        color="seagreen",
    )
    delta_of_delta_plot.xaxis.axis_label = "logical index"
    delta_of_delta_plot.yaxis.axis_label = "|delta-of-delta|"
    if initial_block["delta_of_deltas"].size > 0:
        dod_ymin, dod_ymax = padded_range(
            float(initial_block["delta_of_deltas"].min()),
            float(initial_block["delta_of_deltas"].max()),
        )
    else:
        dod_ymin, dod_ymax = padded_range(0.0, 1.0)
    delta_of_delta_plot.y_range = Range1d(dod_ymin, dod_ymax)
    delta_of_delta_plot.add_tools(HoverTool(
        renderers=[delta_of_delta_renderer],
        tooltips=[("logical index", "@index{0,0}"), ("|delta-of-delta|", "@delta_of_delta{0,0}")]
    ))

    info = Div(text=build_info_html(
        trace_file=trace_file,
        archive_id=archive.id,
        thread_id=thread.id,
        sequence_id=args.sequence_id,
        block_size=args.block_size,
        block_index=args.block_index,
        block_count=block_count,
        block_payload=initial_block,
        pla_name=pla_algorithm.name,
        pla_segment_count=len(block_segment_xs[args.block_index]),
    ))

    slider = Slider(
        start=0,
        end=max(0, block_count - 1),
        value=args.block_index,
        step=1,
        title="Block index",
        width=1100,
    )
    prev_button = Button(label="Previous block", width=140)
    next_button = Button(label="Next block", width=140)

    callback = CustomJS(
        args=dict(
            all_data=all_data_source,
            ts_source=timestamp_source,
            pla_source=pla_source,
            delta_source=delta_source,
            delta_of_delta_source=delta_of_delta_source,
            ts_plot=timestamp_plot,
            delta_plot=delta_plot,
            delta_of_delta_plot=delta_of_delta_plot,
            slider=slider,
            info=info,
            block_size=args.block_size,
            block_count=block_count,
            sequence_id=args.sequence_id,
            archive_id=archive.id,
            thread_id=thread.id,
            trace_path=str(trace_file),
            pla_algorithm=pla_algorithm.name,
        ),
        code="""
const timestamps = all_data.data.timestamps;
const allPlaXs = all_data.data.pla_xs;
const allPlaYs = all_data.data.pla_ys;
const blockIndex = slider.value;
const start = blockIndex * block_size;
const end = Math.min(timestamps.length, start + block_size);

const blockIndices = [];
const blockTimestamps = [];
for (let i = start; i < end; ++i) {
    blockIndices.push(i);
    blockTimestamps.push(timestamps[i]);
}
ts_source.data = {
    index: blockIndices,
    timestamp: blockTimestamps,
};
ts_source.change.emit();

pla_source.data = {
    xs: allPlaXs[blockIndex],
    ys: allPlaYs[blockIndex],
};
pla_source.change.emit();

const deltaIndices = [];
const deltaValues = [];
for (let i = 1; i < blockTimestamps.length; ++i) {
    deltaIndices.push(start + i);
    deltaValues.push(blockTimestamps[i] - blockTimestamps[i - 1]);
}
delta_source.data = {
    index: deltaIndices,
    delta: deltaValues,
};
delta_source.change.emit();

const deltaOfDeltaIndices = [];
const deltaOfDeltaValues = [];
for (let i = 1; i < deltaValues.length; ++i) {
    deltaOfDeltaIndices.push(start + i + 1);
    deltaOfDeltaValues.push(Math.abs(deltaValues[i] - deltaValues[i - 1]));
}
delta_of_delta_source.data = {
    index: deltaOfDeltaIndices,
    delta_of_delta: deltaOfDeltaValues,
};
delta_of_delta_source.change.emit();

if (blockIndices.length > 0) {
    ts_plot.x_range.start = start;
    ts_plot.x_range.end = Math.max(start + 1, end - 1);

    let tsMin = blockTimestamps[0];
    let tsMax = blockTimestamps[0];
    for (const value of blockTimestamps) {
        if (value < tsMin) tsMin = value;
        if (value > tsMax) tsMax = value;
    }
    let tsPad = tsMin === tsMax ? (tsMin === 0 ? 1.0 : Math.abs(tsMin) * 0.01) : (tsMax - tsMin) * 0.05;
    ts_plot.y_range.start = tsMin - tsPad;
    ts_plot.y_range.end = tsMax + tsPad;

    let infoText = `<h2>Spinloop timestamp block viewer</h2>`;
    infoText += `<p><b>Trace:</b> ${trace_path}</p>`;
    infoText += `<p><b>Archive:</b> ${archive_id} | <b>Thread:</b> ${thread_id} | <b>Sequence:</b> ${sequence_id} | <b>Block size:</b> ${block_size} | <b>Block index:</b> ${blockIndex} / ${block_count - 1}</p>`;
    infoText += `<p><b>PLA algorithm:</b> ${pla_algorithm} | <b>PLA segments in block:</b> ${allPlaXs[blockIndex].length}</p>`;
    infoText += `<p><b>Window:</b> [${start}, ${end}) | <b>Timestamp range:</b> [${tsMin}, ${tsMax}]</p>`;

    if (deltaValues.length > 0) {
        let deltaMin = deltaValues[0];
        let deltaMax = deltaValues[0];
        for (const value of deltaValues) {
            if (value < deltaMin) deltaMin = value;
            if (value > deltaMax) deltaMax = value;
        }
        let deltaPad = deltaMin === deltaMax ? (deltaMin === 0 ? 1.0 : Math.abs(deltaMin) * 0.01) : (deltaMax - deltaMin) * 0.05;
        delta_plot.y_range.start = deltaMin - deltaPad;
        delta_plot.y_range.end = deltaMax + deltaPad;
        infoText += `<p><b>Delta range:</b> [${deltaMin}, ${deltaMax}]</p>`;
    } else {
        delta_plot.y_range.start = -1.0;
        delta_plot.y_range.end = 1.0;
    }

    if (deltaOfDeltaValues.length > 0) {
        let dodMin = deltaOfDeltaValues[0];
        let dodMax = deltaOfDeltaValues[0];
        for (const value of deltaOfDeltaValues) {
            if (value < dodMin) dodMin = value;
            if (value > dodMax) dodMax = value;
        }
        let dodPad = dodMin === dodMax ? (dodMin === 0 ? 1.0 : Math.abs(dodMin) * 0.01) : (dodMax - dodMin) * 0.05;
        delta_of_delta_plot.y_range.start = dodMin - dodPad;
        delta_of_delta_plot.y_range.end = dodMax + dodPad;
        infoText += `<p><b>|Delta-of-delta| range:</b> [${dodMin}, ${dodMax}]</p>`;
    } else {
        delta_of_delta_plot.y_range.start = -1.0;
        delta_of_delta_plot.y_range.end = 1.0;
    }
    info.text = infoText;
}
"""
    )
    slider.js_on_change("value", callback)
    prev_button.js_on_click(CustomJS(args=dict(slider=slider), code="""
if (slider.value > slider.start) {
    slider.value = slider.value - 1;
}
"""))
    next_button.js_on_click(CustomJS(args=dict(slider=slider), code="""
if (slider.value < slider.end) {
    slider.value = slider.value + 1;
}
"""))

    controls = row(prev_button, next_button, slider)
    layout_children = [info, controls, timestamp_plot, delta_plot, delta_of_delta_plot]
    layout = column(*layout_children)

    output_file(output_path, title=f"Sequence {args.sequence_id} block {args.block_index}")
    save(layout)

    print(f"Saved interactive timestamp block view to: {output_path}")
    print(f"Top {len(top_block_errors)} max absolute block errors for PLA '{pla_algorithm.name}':")
    for error_summary in top_block_errors:
        print(
            f"  block={error_summary.block_index} "
            f"max_abs_error={error_summary.max_abs_error:.3f} "
            f"logical_index={error_summary.logical_index}"
        )

    if args.show_bokeh:
        show(layout)

    return 0


if __name__ == "__main__":
    sys.exit(main())
