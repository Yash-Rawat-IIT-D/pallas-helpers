#!/usr/bin/env python3

import argparse
import csv
import json
import math
import os
import shutil
from pathlib import Path
from typing import Any


FAMILY_ORDER = [
    "event_timestamps",
    "sequence_timestamps",
    "sequence_durations",
    "sequence_exclusive_durations",
    "all_families",
]

FAMILY_LABELS = {
    "event_timestamps": "event_ts",
    "sequence_timestamps": "seq_ts",
    "sequence_durations": "inc_dur",
    "sequence_exclusive_durations": "exc_dur",
    "all_families": "all",
}

RUN_BENCHMARK_SUM_FIELDS = [
    "pre_raw_bytes",
    "raw_bytes",
    "compressed_bytes",
    "write_ns",
    "write_calls",
    "subarray_writes",
    "value_count",
    "sum_abs_error",
    "sum_squared_abs_error",
    "nonzero_error_count",
    "add_ns",
    "add_calls",
    "at_ns",
    "at_calls",
    "operator_ns",
    "operator_calls",
]

RUN_BENCHMARK_MAX_FIELDS = [
    "max_abs_error",
]

PERF_BENCHMARK_SUM_FIELDS = [
    "value_count",
    "recent_value_hits",
    "recent_value_misses",
    "find_subarray_calls",
    "find_subarray_steps",
    "subarray_loads",
    "subarray_load_bytes",
    "subarray_decompressed_bytes",
    "subarray_evictions",
    "subarray_evicted_bytes",
]

GROUPED_GRAPH_COLORS = {
    "raw_to_compressed_ratio": "#5DADE2",
    "pre_raw_to_compressed_ratio": "#F5B041",
    "add_ns_per_value": "#58D68D",
    "at_ns_per_call": "#EC7063",
    "operator_ns_per_call": "#AF7AC5",
}

STACKED_GRAPH_COLORS = {
    "materialize_ns_per_value": "#5DADE2",
    "at_ns_per_call": "#F5B041",
    "index_ns_per_call": "#58D68D",
}

GROUPED_GRAPH_LABELS = {
    "raw_to_compressed_ratio": "Raw / Compressed",
    "pre_raw_to_compressed_ratio": "Pre-raw / Compressed",
    "add_ns_per_value": "Add ns / value",
    "at_ns_per_call": "At ns / call",
    "operator_ns_per_call": "Index ns / call",
}

STACKED_GRAPH_LABELS = {
    "materialize_ns_per_value": "Materialize ns / value",
    "at_ns_per_call": "At ns / call",
    "index_ns_per_call": "Index ns / call",
}

ERROR_GRAPH_COLORS = {
    "mean_abs_error": "#5DADE2",
    "stddev_abs_error": "#58D68D",
    "max_abs_error": "#EC7063",
}

ERROR_GRAPH_LABELS = {
    "mean_abs_error": "Mean abs error",
    "stddev_abs_error": "Stddev abs error",
    "max_abs_error": "Max abs error",
}


def parse_scalar(value: str) -> Any:
    text = value.strip()
    if not text:
        return ""
    try:
        return int(text)
    except ValueError:
        pass
    try:
        return float(text)
    except ValueError:
        return text


def read_csv_rows(path: Path) -> list[dict[str, Any]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        return [{key: parse_scalar(value) for key, value in row.items()} for row in reader]


def write_csv_rows(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        raise ValueError(f"Cannot write empty CSV: {path}")
    fieldnames = list(rows[0].keys())
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def parse_config_file(path: Path) -> dict[str, Any]:
    values: dict[str, Any] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        values[key.strip()] = parse_scalar(value)
    return values


def sort_test_dirs(test_dirs: list[Path]) -> list[Path]:
    def key(path: Path) -> tuple[int, str]:
        suffix = path.name.split("_", 1)[1]
        return (int(suffix), path.name)

    return sorted(test_dirs, key=key)


def family_sort_key(family: str) -> tuple[int, str]:
    try:
        return (FAMILY_ORDER.index(family), family)
    except ValueError:
        return (len(FAMILY_ORDER), family)


def format_int(value: Any) -> str:
    return f"{int(round(float(value))):,}"


def format_number(value: Any) -> str:
    numeric_value = float(value)
    if numeric_value.is_integer():
        return f"{int(numeric_value):,}"
    return f"{numeric_value:,.2f}"


def format_megabytes(value: Any) -> str:
    megabytes = float(value) / 1_000_000.0
    formatted = f"{megabytes:,.3f}".rstrip("0").rstrip(".")
    return f"{formatted} MB"


def get_plt():
    try:
        os.environ.setdefault("MPLCONFIGDIR", "/tmp/matplotlib-codex")
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError as exc:
        raise RuntimeError(
            "matplotlib is required to generate graphs. Please install it in the active environment."
        ) from exc
    return plt


def make_output_dir(run_dir: Path) -> Path:
    if run_dir.name.startswith("test-run-"):
        return run_dir.parent / f"run-analysis-{run_dir.name[len('test-run-'):]}"
    return run_dir.parent / f"{run_dir.name}-analysis"


def find_matrix_file(run_dir: Path) -> Path | None:
    matches = sorted(run_dir.glob("*matrix*.json"))
    if not matches:
        return None
    if len(matches) > 1:
        raise ValueError(f"Expected at most one matrix JSON under {run_dir}, found {len(matches)}")
    return matches[0]


def find_trace_dir(test_dir: Path) -> Path:
    trace_files = sorted(test_dir.glob("*/eztrace_log.pallas"))
    if len(trace_files) != 1:
        raise ValueError(f"Expected exactly one trace file under {test_dir}, found {len(trace_files)}")
    return trace_files[0].parent


def safe_ratio(numerator: Any, denominator: Any) -> float:
    denominator_value = float(denominator)
    if denominator_value == 0.0:
        return 0.0
    return float(numerator) / denominator_value


def sum_numeric_field(rows: list[dict[str, Any]], field: str) -> Any:
    if field == "sum_squared_abs_error":
        return sum(float(row.get(field, 0.0)) for row in rows)
    return sum(int(row.get(field, 0)) for row in rows)


def normalize_run_benchmark_row(row: dict[str, Any]) -> dict[str, Any]:
    value_count = int(row.get("value_count", 0))
    add_calls = int(row.get("add_calls", 0))
    at_calls = int(row.get("at_calls", 0))
    operator_calls = int(row.get("operator_calls", 0))
    sum_abs_error = float(row.get("sum_abs_error", 0))
    sum_squared_abs_error = float(row.get("sum_squared_abs_error", 0))
    nonzero_error_count = int(row.get("nonzero_error_count", 0))

    row["pre_raw_to_compressed_ratio"] = safe_ratio(row["pre_raw_bytes"], row["compressed_bytes"])
    row["raw_to_compressed_ratio"] = safe_ratio(row["raw_bytes"], row["compressed_bytes"])
    row["write_ns_per_value"] = safe_ratio(row["write_ns"], value_count)
    row["add_ns_per_value"] = safe_ratio(row["add_ns"], value_count if value_count else add_calls)
    row["at_ns_per_call"] = safe_ratio(row["at_ns"], at_calls)
    row["operator_ns_per_call"] = safe_ratio(row["operator_ns"], operator_calls)
    row["mean_abs_error"] = safe_ratio(sum_abs_error, value_count)
    row["mean_squared_abs_error"] = safe_ratio(sum_squared_abs_error, value_count)
    row["rms_abs_error"] = math.sqrt(max(0.0, row["mean_squared_abs_error"]))
    variance_abs_error = row["mean_squared_abs_error"] - (row["mean_abs_error"] ** 2)
    row["stddev_abs_error"] = math.sqrt(max(0.0, variance_abs_error))
    row["nonzero_error_fraction"] = safe_ratio(nonzero_error_count, value_count)
    return row


def normalize_bool(value: Any) -> bool:
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def load_test_matrix_configs(run_dir: Path, test_ids: list[str]) -> dict[str, dict[str, Any]]:
    matrix_path = find_matrix_file(run_dir)
    if matrix_path is None:
        return {}

    matrix_data = json.loads(matrix_path.read_text(encoding="utf-8"))
    if not isinstance(matrix_data, list):
        raise ValueError(f"Expected matrix JSON list in {matrix_path}")

    configs_by_test: dict[str, dict[str, Any]] = {}
    for index, test_id in enumerate(test_ids):
        if index >= len(matrix_data):
            print(
                f"WARNING: matrix file {matrix_path.name} has fewer entries than test directories; "
                f"no matrix config for {test_id}"
            )
            continue
        entry = matrix_data[index]
        if not isinstance(entry, dict):
            raise ValueError(f"Matrix entry {index} in {matrix_path} is not an object")
        configs_by_test[test_id] = entry

    if len(matrix_data) > len(test_ids):
        print(
            f"WARNING: matrix file {matrix_path.name} has {len(matrix_data)} entries but only "
            f"{len(test_ids)} test directories were found"
        )

    return configs_by_test


def expects_zero_error(config: dict[str, Any]) -> bool:
    storage_policy = str(config.get("storagePolicy", "")).strip()
    return storage_policy in {"None", "Delta"} and normalize_bool(config.get("overrideLoopDetection", False))


def aggregate_family_rows(
    archive_rows: list[dict[str, Any]],
    test_id: str,
    trace_name: str,
    archive_count: int,
) -> list[dict[str, Any]]:
    by_family: dict[str, list[dict[str, Any]]] = {}
    for row in archive_rows:
        by_family.setdefault(str(row["family"]), []).append(row)

    aggregated_rows: list[dict[str, Any]] = []
    for family in sorted(by_family, key=family_sort_key):
        family_rows = by_family[family]
        aggregate: dict[str, Any] = {
            "test_id": test_id,
            "trace_name": trace_name,
            "archive_count": archive_count,
            "family": family,
        }
        for field in RUN_BENCHMARK_SUM_FIELDS:
            aggregate[field] = sum_numeric_field(family_rows, field)
        for field in RUN_BENCHMARK_MAX_FIELDS:
            aggregate[field] = max(int(row.get(field, 0)) for row in family_rows)
        aggregated_rows.append(normalize_run_benchmark_row(aggregate))

    if aggregated_rows:
        total_row: dict[str, Any] = {
            "test_id": test_id,
            "trace_name": trace_name,
            "archive_count": archive_count,
            "family": "all_families",
        }
        for field in RUN_BENCHMARK_SUM_FIELDS:
            total_row[field] = sum_numeric_field(aggregated_rows, field)
        for field in RUN_BENCHMARK_MAX_FIELDS:
            total_row[field] = max(int(row.get(field, 0)) for row in aggregated_rows)
        aggregated_rows.append(normalize_run_benchmark_row(total_row))

    return aggregated_rows


def aggregate_perf_rows(
    archive_rows: list[dict[str, Any]],
    test_id: str,
    trace_name: str,
    archive_count: int,
) -> list[dict[str, Any]]:
    by_family: dict[str, list[dict[str, Any]]] = {}
    for row in archive_rows:
        by_family.setdefault(str(row["family"]), []).append(row)

    aggregated_rows: list[dict[str, Any]] = []
    for family in sorted(by_family, key=family_sort_key):
        family_rows = by_family[family]
        aggregate: dict[str, Any] = {
            "test_id": test_id,
            "trace_name": trace_name,
            "archive_count": archive_count,
            "family": family,
        }
        for field in PERF_BENCHMARK_SUM_FIELDS:
            aggregate[field] = sum_numeric_field(family_rows, field)
        aggregated_rows.append(aggregate)

    if aggregated_rows:
        total_row: dict[str, Any] = {
            "test_id": test_id,
            "trace_name": trace_name,
            "archive_count": archive_count,
            "family": "all_families",
        }
        for field in PERF_BENCHMARK_SUM_FIELDS:
            total_row[field] = sum_numeric_field(aggregated_rows, field)
        aggregated_rows.append(total_row)

    return aggregated_rows


def load_run_benchmark_rows(test_id: str, trace_dir: Path) -> list[dict[str, Any]]:
    archive_files = sorted(trace_dir.glob("archive_*/archive_benchmark.csv"))
    if not archive_files:
        raise ValueError(f"No archive_benchmark.csv files found under {trace_dir}")

    archive_rows: list[dict[str, Any]] = []
    for archive_file in archive_files:
        archive_rows.extend(read_csv_rows(archive_file))

    return aggregate_family_rows(
        archive_rows=archive_rows,
        test_id=test_id,
        trace_name=trace_dir.name,
        archive_count=len(archive_files),
    )


def load_perf_benchmark_rows(test_id: str, trace_dir: Path) -> list[dict[str, Any]]:
    perf_files = sorted(trace_dir.glob("archive_*/perf_benchmark.csv"))
    if not perf_files:
        return []

    perf_rows: list[dict[str, Any]] = []
    for perf_file in perf_files:
        perf_rows.extend(read_csv_rows(perf_file))

    return aggregate_perf_rows(
        archive_rows=perf_rows,
        test_id=test_id,
        trace_name=trace_dir.name,
        archive_count=len(perf_files),
    )


def copy_read_benchmark_files(trace_dir: Path, output_test_dir: Path) -> None:
    for name in ("read_bulk_benchmark.csv", "read_replay_benchmark.csv"):
        source = trace_dir / name
        if source.exists():
            shutil.copy2(source, output_test_dir / name)


def load_read_bulk_rows(test_id: str, trace_dir: Path) -> list[dict[str, Any]]:
    bulk_path = trace_dir / "read_bulk_benchmark.csv"
    if not bulk_path.exists():
        return []

    rows = read_csv_rows(bulk_path)
    for row in rows:
        row["test_id"] = test_id
        row["trace_name"] = trace_dir.name
        row["family"] = str(row["family"])
        row["category_label"] = f"{test_id}\n{FAMILY_LABELS.get(str(row['family']), str(row['family']))}"
    return rows


def load_read_replay_rows(test_id: str, trace_dir: Path) -> list[dict[str, Any]]:
    replay_path = trace_dir / "read_replay_benchmark.csv"
    if not replay_path.exists():
        return []

    rows = read_csv_rows(replay_path)
    for row in rows:
        row["test_id"] = test_id
        row["trace_name"] = trace_dir.name
    return rows


def write_analysis_metadata(run_dir: Path, output_dir: Path) -> None:
    metadata = {
        "source_run_dir": str(run_dir),
        "output_dir": str(output_dir),
        "baseline_test_id": "test_0",
        "phase": "archive_level_csv_generation",
    }
    (output_dir / "analysis_metadata.json").write_text(
        json.dumps(metadata, indent=2) + "\n",
        encoding="utf-8",
    )


def clean_output_dir(output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    for child in output_dir.iterdir():
        if child.name == "analysis_metadata.json":
            continue
        if child.is_dir():
            shutil.rmtree(child)
        else:
            child.unlink()


def prepare_test_outputs(
    run_dir: Path,
    output_dir: Path,
) -> tuple[
    list[dict[str, Any]],
    list[dict[str, Any]],
    list[dict[str, Any]],
    list[dict[str, Any]],
    dict[str, dict[str, Any]],
]:
    combined_run_rows: list[dict[str, Any]] = []
    combined_perf_rows: list[dict[str, Any]] = []
    combined_read_bulk_rows: list[dict[str, Any]] = []
    combined_read_replay_rows: list[dict[str, Any]] = []

    test_dirs = sort_test_dirs([path for path in run_dir.iterdir() if path.is_dir() and path.name.startswith("test_")])
    if not test_dirs:
        raise ValueError(f"No test_* directories found under {run_dir}")
    test_ids = [path.name for path in test_dirs]
    test_matrix_configs = load_test_matrix_configs(run_dir, test_ids)

    for test_dir in test_dirs:
        test_id = test_dir.name
        trace_dir = find_trace_dir(test_dir)
        output_test_dir = output_dir / test_id
        output_test_dir.mkdir(parents=True, exist_ok=True)

        config_path = test_dir / "pallas.config"
        if config_path.exists():
            shutil.copy2(config_path, output_test_dir / "pallas.config")
            (output_test_dir / "trace_config.json").write_text(
                json.dumps(parse_config_file(config_path), indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )

        run_rows = load_run_benchmark_rows(test_id, trace_dir)
        write_csv_rows(output_test_dir / "run_benchmark.csv", run_rows)
        combined_run_rows.extend(run_rows)

        perf_rows = load_perf_benchmark_rows(test_id, trace_dir)
        if perf_rows:
            write_csv_rows(output_test_dir / "perf_benchmark.csv", perf_rows)
            combined_perf_rows.extend(perf_rows)

        copy_read_benchmark_files(trace_dir, output_test_dir)

        read_bulk_rows = load_read_bulk_rows(test_id, trace_dir)
        read_replay_rows = load_read_replay_rows(test_id, trace_dir)
        combined_read_bulk_rows.extend(read_bulk_rows)
        combined_read_replay_rows.extend(read_replay_rows)

    return combined_run_rows, combined_perf_rows, combined_read_bulk_rows, combined_read_replay_rows, test_matrix_configs


def write_top_level_csvs(
    output_dir: Path,
    run_rows: list[dict[str, Any]],
    perf_rows: list[dict[str, Any]],
    read_bulk_rows: list[dict[str, Any]],
    read_replay_rows: list[dict[str, Any]],
) -> None:
    if run_rows:
        write_csv_rows(output_dir / "run_benchmark.csv", run_rows)
    if perf_rows:
        write_csv_rows(output_dir / "perf_benchmark.csv", perf_rows)
    if read_bulk_rows:
        write_csv_rows(output_dir / "read_bulk_benchmark.csv", read_bulk_rows)
    if read_replay_rows:
        write_csv_rows(output_dir / "read_replay_benchmark.csv", read_replay_rows)


def grouped_bar_chart(
    rows: list[dict[str, Any]],
    category_labels: list[str],
    metric_keys: list[str],
    metric_labels: dict[str, str],
    metric_colors: dict[str, str],
    title: str,
    ylabel: str,
    output_path: Path,
    value_formatter,
    group_annotations: list[str] | None = None,
) -> None:
    plt = get_plt()
    active_metrics = [key for key in metric_keys if any(float(row.get(key, 0.0)) > 0.0 for row in rows)]
    if not active_metrics:
        return

    x_positions = list(range(len(rows)))
    width = 0.8 / len(active_metrics)
    fig_width = max(10, len(rows) * 0.9)
    fig, ax = plt.subplots(figsize=(fig_width, 6))

    max_height = 0.0
    group_maxima = [0.0 for _ in rows]
    for metric_index, metric_key in enumerate(active_metrics):
        values = [float(row.get(metric_key, 0.0)) for row in rows]
        shifted_positions = [
            x + (metric_index - (len(active_metrics) - 1) / 2) * width for x in x_positions
        ]
        bars = ax.bar(
            shifted_positions,
            values,
            width=width,
            label=metric_labels.get(metric_key, metric_key),
            color=metric_colors.get(metric_key),
        )
        for row_index, (bar, value) in enumerate(zip(bars, values)):
            if value <= 0.0:
                continue
            max_height = max(max_height, value)
            group_maxima[row_index] = max(group_maxima[row_index], value)
            ax.text(
                bar.get_x() + bar.get_width() / 2,
                bar.get_height(),
                value_formatter(value),
                ha="center",
                va="bottom",
                fontsize=8,
                rotation=90 if len(rows) > 6 else 0,
            )

    if group_annotations:
        annotation_offset = max_height * 0.04 if max_height > 0 else 0.05
        max_annotation_lines = 1
        for index, annotation in enumerate(group_annotations):
            if not annotation:
                continue
            max_annotation_lines = max(max_annotation_lines, annotation.count("\n") + 1)
            ax.text(
                index,
                group_maxima[index] + annotation_offset,
                annotation,
                ha="center",
                va="bottom",
                fontsize=8,
                linespacing=1.05,
                bbox={"boxstyle": "round,pad=0.2", "facecolor": "white", "alpha": 0.7, "edgecolor": "none"},
            )
        if max_height > 0:
            ax.set_ylim(0.0, max_height * (1.10 + 0.08 * max_annotation_lines))

    ax.set_title(title)
    ax.set_ylabel(ylabel)
    ax.set_xticks(x_positions, category_labels)
    ax.tick_params(axis="x", rotation=0 if len(rows) <= 6 else 45)
    ax.grid(axis="y", alpha=0.3)
    ax.legend(loc="upper right", fontsize=8, framealpha=0.25)
    fig.tight_layout()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output_path)
    plt.close(fig)


def stacked_bar_chart(
    rows: list[dict[str, Any]],
    category_labels: list[str],
    metric_keys: list[str],
    metric_labels: dict[str, str],
    metric_colors: dict[str, str],
    title: str,
    ylabel: str,
    output_path: Path,
    value_formatter,
) -> None:
    plt = get_plt()
    active_metrics = [key for key in metric_keys if any(float(row.get(key, 0.0)) > 0.0 for row in rows)]
    if not active_metrics:
        return

    x_positions = list(range(len(rows)))
    fig_width = max(12, len(rows) * 0.65)
    fig, ax = plt.subplots(figsize=(fig_width, 6))
    bottoms = [0.0 for _ in rows]

    for metric_key in active_metrics:
        values = [float(row.get(metric_key, 0.0)) for row in rows]
        bars = ax.bar(
            x_positions,
            values,
            bottom=bottoms,
            label=metric_labels.get(metric_key, metric_key),
            color=metric_colors.get(metric_key),
        )
        for bar, value, bottom in zip(bars, values, bottoms):
            if value <= 0.0:
                continue
            ax.text(
                bar.get_x() + bar.get_width() / 2,
                bottom + value / 2.0,
                value_formatter(value),
                ha="center",
                va="center",
                fontsize=7,
                rotation=90 if len(rows) > 12 else 0,
            )
        bottoms = [bottom + value for bottom, value in zip(bottoms, values)]

    ax.set_title(title)
    ax.set_ylabel(ylabel)
    ax.set_xticks(x_positions, category_labels)
    ax.tick_params(axis="x", rotation=0 if len(rows) <= 10 else 45)
    ax.grid(axis="y", alpha=0.3)
    ax.legend(loc="upper right", fontsize=8, framealpha=0.25)
    fig.tight_layout()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output_path)
    plt.close(fig)


def error_bar_chart(
    rows: list[dict[str, Any]],
    category_labels: list[str],
    title: str,
    ylabel: str,
    output_path: Path,
) -> None:
    plt = get_plt()
    x_positions = list(range(len(rows)))
    width = 0.6
    fig_width = max(10, len(rows) * 1.0)
    fig, (top_ax, bottom_ax) = plt.subplots(
        2,
        1,
        figsize=(fig_width, 8),
        sharex=True,
        gridspec_kw={"height_ratios": [3, 2]},
    )

    mean_values = [float(row.get("mean_abs_error", 0.0)) for row in rows]
    stddev_values = [float(row.get("stddev_abs_error", 0.0)) for row in rows]
    max_values = [float(row.get("max_abs_error", 0.0)) for row in rows]
    stacked_totals = [mean + stddev for mean, stddev in zip(mean_values, stddev_values)]

    mean_bars = top_ax.bar(
        x_positions,
        mean_values,
        width=width,
        label=ERROR_GRAPH_LABELS["mean_abs_error"],
        color=ERROR_GRAPH_COLORS["mean_abs_error"],
    )
    stddev_bars = top_ax.bar(
        x_positions,
        stddev_values,
        width=width,
        bottom=mean_values,
        label=ERROR_GRAPH_LABELS["stddev_abs_error"],
        color=ERROR_GRAPH_COLORS["stddev_abs_error"],
    )
    max_bars = bottom_ax.bar(
        x_positions,
        max_values,
        width=width,
        label=ERROR_GRAPH_LABELS["max_abs_error"],
        color=ERROR_GRAPH_COLORS["max_abs_error"],
    )

    for bar, value in zip(mean_bars, mean_values):
        if value <= 0.0:
            continue
        top_ax.text(
            bar.get_x() + bar.get_width() / 2,
            value / 2.0,
            format_number(value),
            ha="center",
            va="center",
            fontsize=7,
        )

    for bar, value, bottom in zip(stddev_bars, stddev_values, mean_values):
        if value <= 0.0:
            continue
        top_ax.text(
            bar.get_x() + bar.get_width() / 2,
            bottom + value / 2.0,
            format_number(value),
            ha="center",
            va="center",
            fontsize=7,
        )

    top_max_height = max(stacked_totals + [0.0])
    for bar, value in zip(max_bars, max_values):
        if value <= 0.0:
            continue
        bottom_ax.text(
            bar.get_x() + bar.get_width() / 2,
            value,
            format_number(value),
            ha="center",
            va="bottom",
            fontsize=7,
        )

    if top_max_height > 0.0:
        top_ax.set_ylim(0.0, top_max_height * 1.18)
    else:
        top_ax.set_ylim(0.0, 1.0)

    bottom_max_height = max(max_values + [0.0])
    if bottom_max_height > 0.0:
        bottom_ax.set_ylim(0.0, bottom_max_height * 1.18)
    else:
        bottom_ax.set_ylim(0.0, 1.0)

    top_ax.set_title(title)
    top_ax.set_ylabel(f"{ylabel}\nmean + stddev")
    bottom_ax.set_ylabel(f"{ylabel}\nmax")
    bottom_ax.set_xticks(x_positions, category_labels)
    bottom_ax.tick_params(axis="x", rotation=0 if len(rows) <= 8 else 45)
    top_ax.grid(axis="y", alpha=0.3)
    bottom_ax.grid(axis="y", alpha=0.3)
    top_ax.legend(loc="upper right", fontsize=8, framealpha=0.25)
    bottom_ax.legend(loc="upper right", fontsize=8, framealpha=0.25)
    fig.tight_layout()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output_path)
    plt.close(fig)


def warn_on_unexpected_nonzero_error(
    run_rows: list[dict[str, Any]],
    test_matrix_configs: dict[str, dict[str, Any]],
) -> None:
    family_rows = [row for row in run_rows if str(row.get("family")) != "all_families"]
    for row in family_rows:
        test_id = str(row.get("test_id"))
        config = test_matrix_configs.get(test_id)
        if not config or not expects_zero_error(config):
            continue
        if (
            float(row.get("max_abs_error", 0.0)) <= 0.0
            and float(row.get("sum_abs_error", 0.0)) <= 0.0
            and float(row.get("stddev_abs_error", 0.0)) <= 0.0
        ):
            continue
        family = str(row.get("family"))
        print(
            "WARNING: expected zero error for "
            f"{test_id} {FAMILY_LABELS.get(family, family)} "
            f"(storagePolicy={config.get('storagePolicy')}, "
            f"overrideLoopDetection={config.get('overrideLoopDetection')}) "
            f"but found mean_abs_error={float(row.get('mean_abs_error', 0.0)):.6f}, "
            f"stddev_abs_error={float(row.get('stddev_abs_error', 0.0)):.6f}, "
            f"max_abs_error={float(row.get('max_abs_error', 0.0)):.6f}"
        )


def build_graphs(
    output_dir: Path,
    run_rows: list[dict[str, Any]],
    read_bulk_rows: list[dict[str, Any]],
) -> None:
    graphs_dir = output_dir / "graphs"
    graphs_dir.mkdir(parents=True, exist_ok=True)

    all_family_run_rows = [row for row in run_rows if str(row.get("family")) == "all_families"]
    all_family_run_rows = sorted(all_family_run_rows, key=lambda row: int(str(row["test_id"]).split("_", 1)[1]))
    if all_family_run_rows:
        grouped_bar_chart(
            rows=all_family_run_rows,
            category_labels=[str(row["test_id"]) for row in all_family_run_rows],
            metric_keys=["raw_to_compressed_ratio", "pre_raw_to_compressed_ratio"],
            metric_labels=GROUPED_GRAPH_LABELS,
            metric_colors=GROUPED_GRAPH_COLORS,
            title="Compression Ratios",
            ylabel="ratio",
            output_path=graphs_dir / "compression_ratios.png",
            value_formatter=lambda value: f"{value:.2f}",
            group_annotations=[
                "\n".join(
                    [
                        f"pre {format_megabytes(row['pre_raw_bytes'])}",
                        f"raw {format_megabytes(row['raw_bytes'])}",
                        f"cmp {format_megabytes(row['compressed_bytes'])}",
                    ]
                )
                for row in all_family_run_rows
            ],
        )

        grouped_bar_chart(
            rows=all_family_run_rows,
            category_labels=[str(row["test_id"]) for row in all_family_run_rows],
            metric_keys=["add_ns_per_value", "at_ns_per_call", "operator_ns_per_call"],
            metric_labels=GROUPED_GRAPH_LABELS,
            metric_colors=GROUPED_GRAPH_COLORS,
            title="Normalized Add / At / Index Cost",
            ylabel="ns",
            output_path=graphs_dir / "run_benchmark_runtime.png",
            value_formatter=lambda value: f"{value:.2f}",
            group_annotations=[
                f"values {format_int(row['value_count'])}"
                for row in all_family_run_rows
            ],
        )

    error_graphs = [
        ("event_timestamps", "Absolute Error: Event Timestamps", graphs_dir / "error_event_ts.png"),
        ("sequence_timestamps", "Absolute Error: Sequence Timestamps", graphs_dir / "error_seq_ts.png"),
        ("sequence_durations", "Absolute Error: Inclusive Durations", graphs_dir / "error_inc_dur.png"),
        (
            "sequence_exclusive_durations",
            "Absolute Error: Exclusive Durations",
            graphs_dir / "error_exc_dur.png",
        ),
    ]
    for family, title, output_path in error_graphs:
        family_rows = [row for row in run_rows if str(row.get("family")) == family]
        family_rows = sorted(family_rows, key=lambda row: int(str(row["test_id"]).split("_", 1)[1]))
        if not family_rows:
            continue
        error_bar_chart(
            rows=family_rows,
            category_labels=[str(row["test_id"]) for row in family_rows],
            title=title,
            ylabel="abs error",
            output_path=output_path,
        )

    if read_bulk_rows:
        ordered_read_rows = sorted(
            read_bulk_rows,
            key=lambda row: (
                int(str(row["test_id"]).split("_", 1)[1]),
                family_sort_key(str(row["family"])),
            ),
        )
        bulk_graphs = [
            (
                "Read Bulk Benchmark: All Families",
                graphs_dir / "read_bulk_all.png",
                ["all_families"],
            ),
            (
                "Read Bulk Benchmark: Event and Sequence Timestamps",
                graphs_dir / "read_bulk_timestamps.png",
                ["event_timestamps", "sequence_timestamps"],
            ),
            (
                "Read Bulk Benchmark: Inclusive and Exclusive Durations",
                graphs_dir / "read_bulk_durations.png",
                ["sequence_durations", "sequence_exclusive_durations"],
            ),
        ]

        for title, output_path, families in bulk_graphs:
            selected_rows = [
                row for row in ordered_read_rows if str(row.get("family")) in families
            ]
            if not selected_rows:
                continue
            stacked_bar_chart(
                rows=selected_rows,
                category_labels=[str(row["category_label"]) for row in selected_rows],
                metric_keys=["materialize_ns_per_value", "at_ns_per_call", "index_ns_per_call"],
                metric_labels=STACKED_GRAPH_LABELS,
                metric_colors=STACKED_GRAPH_COLORS,
                title=title,
                ylabel="ns",
                output_path=output_path,
                value_formatter=lambda value: f"{value:.2f}",
            )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate archive-level CSVs and graphs for a Pallas benchmark run directory."
    )
    parser.add_argument(
        "run_directory",
        type=Path,
        help="Path to a test-run-* directory produced by run_benchmark.py",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    run_dir = args.run_directory.resolve()
    if not run_dir.is_dir():
        raise FileNotFoundError(f"Run directory does not exist: {run_dir}")

    output_dir = make_output_dir(run_dir)
    clean_output_dir(output_dir)
    write_analysis_metadata(run_dir, output_dir)

    run_rows, perf_rows, read_bulk_rows, read_replay_rows, test_matrix_configs = prepare_test_outputs(run_dir, output_dir)
    warn_on_unexpected_nonzero_error(run_rows, test_matrix_configs)
    write_top_level_csvs(output_dir, run_rows, perf_rows, read_bulk_rows, read_replay_rows)
    build_graphs(output_dir, run_rows, read_bulk_rows)

    print(output_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
