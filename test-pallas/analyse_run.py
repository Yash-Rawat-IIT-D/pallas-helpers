#!/usr/bin/env python3

import argparse
import csv
import json
import os
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any


WRITE_TIME_FIELDS = {
    "event_timestamps": "event_timestamps_write_ns",
    "sequence_timestamps": "sequence_timestamps_write_ns",
    "sequence_durations": "sequence_durations_write_ns",
    "sequence_exclusive_durations": "sequence_exclusive_durations_write_ns",
}

VERIFICATION_TIME_FIELDS = {
    "event_timestamps": "event_timestamps_verification_ns",
    "sequence_timestamps": "sequence_timestamps_verification_ns",
    "sequence_durations": "sequence_durations_verification_ns",
    "sequence_exclusive_durations": "sequence_exclusive_durations_verification_ns",
}

VERIFICATION_VALUE_FIELDS = {
    "event_timestamps": "event_timestamps_verification_values",
    "sequence_timestamps": "sequence_timestamps_verification_values",
    "sequence_durations": "sequence_durations_verification_values",
    "sequence_exclusive_durations": "sequence_exclusive_durations_verification_values",
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


def parse_key_value_file(path: Path) -> dict[str, Any]:
    values: dict[str, Any] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        values[key.strip()] = parse_scalar(value)
    return values


def write_single_row_csv(path: Path, row: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(row.keys()))
        writer.writeheader()
        writer.writerow(row)


def write_rows_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        raise ValueError(f"Cannot write empty CSV: {path}")
    fieldnames = list(rows[0].keys())
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def read_single_row_csv(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        rows = list(reader)
    if len(rows) != 1:
        raise ValueError(f"Expected exactly one data row in {path}, found {len(rows)}")
    return {key: parse_scalar(value) for key, value in rows[0].items()}


def sum_numeric(rows: list[dict[str, Any]], key: str) -> int:
    total = 0
    for row in rows:
        total += int(row.get(key, 0))
    return total


@dataclass(frozen=True)
class ThreadMetrics:
    archive_id: int
    thread_id: int
    compression: dict[str, Any]
    write_time: dict[str, Any]
    write_verification: dict[str, Any]

    @classmethod
    def load(cls, thread_dir: Path) -> "ThreadMetrics":
        compression = parse_key_value_file(thread_dir / "compression.txt")
        write_time = parse_key_value_file(thread_dir / "write_time.txt")
        write_verification = parse_key_value_file(thread_dir / "write_verification.txt")
        return cls(
            archive_id=int(compression["archive"]),
            thread_id=int(compression["thread"]),
            compression=compression,
            write_time=write_time,
            write_verification=write_verification,
        )


@dataclass(frozen=True)
class TraceMetrics:
    trace_dir: Path
    read_metrics: dict[str, Any]

    @classmethod
    def load(cls, trace_dir: Path) -> "TraceMetrics":
        return cls(
            trace_dir=trace_dir,
            read_metrics=parse_key_value_file(trace_dir / "eztrace_log.read_benchmark.txt"),
        )

    def read_row(self, test_id: str) -> dict[str, Any]:
        row: dict[str, Any] = {
            "test_id": test_id,
            "trace_name": self.trace_dir.name,
        }
        row.update(self.read_metrics)
        return row


@dataclass
class ArchiveAnalysis:
    test_id: str
    archive_dir: Path
    trace_metrics: TraceMetrics
    thread_metrics: list[ThreadMetrics]

    @property
    def archive_id(self) -> int:
        return int(self.archive_dir.name.split("_", 1)[1])

    @classmethod
    def load(
        cls,
        test_id: str,
        archive_dir: Path,
        trace_metrics: TraceMetrics,
    ) -> "ArchiveAnalysis":
        thread_dirs = sorted(path for path in archive_dir.iterdir() if path.is_dir() and path.name.startswith("thread_"))
        thread_metrics = [ThreadMetrics.load(thread_dir) for thread_dir in thread_dirs]
        return cls(
            test_id=test_id,
            archive_dir=archive_dir,
            trace_metrics=trace_metrics,
            thread_metrics=thread_metrics,
        )

    def compression_row(self) -> dict[str, Any]:
        pre_raw_sum = sum_numeric([tm.compression for tm in self.thread_metrics], "pre_raw")
        raw_sum = sum_numeric([tm.compression for tm in self.thread_metrics], "raw")
        compressed_sum = sum_numeric([tm.compression for tm in self.thread_metrics], "compressed")
        effective_ratio = (raw_sum / compressed_sum) if compressed_sum else 0.0
        true_ratio = (pre_raw_sum / compressed_sum) if compressed_sum else 0.0

        row: dict[str, Any] = {
            "test_id": self.test_id,
            "trace_name": self.trace_metrics.trace_dir.name,
            "archive_id": self.archive_id,
            "thread_count": len(self.thread_metrics),
            "pre_raw_sum": pre_raw_sum,
            "raw_sum": raw_sum,
            "compressed_sum": compressed_sum,
            "effective_ratio": effective_ratio,
            "true_ratio": true_ratio,
        }
        return row

    def write_row(self) -> dict[str, Any]:
        row: dict[str, Any] = {
            "test_id": self.test_id,
            "trace_name": self.trace_metrics.trace_dir.name,
            "archive_id": self.archive_id,
            "thread_count": len(self.thread_metrics),
        }

        total_write_ns = 0
        total_verification_ns = 0
        total_net_write_ns = 0
        total_values = 0

        for family, write_key in WRITE_TIME_FIELDS.items():
            verification_key = VERIFICATION_TIME_FIELDS[family]
            value_key = VERIFICATION_VALUE_FIELDS[family]
            write_ns = sum_numeric([tm.write_time for tm in self.thread_metrics], write_key)
            verification_ns = sum_numeric([tm.write_verification for tm in self.thread_metrics], verification_key)
            value_count = sum_numeric([tm.write_verification for tm in self.thread_metrics], value_key)
            net_write_ns = write_ns - verification_ns
            if net_write_ns < 0:
                raise ValueError(
                    f"Archive {self.archive_id} in {self.trace_metrics.trace_dir} has negative net write time for {family}: "
                    f"{write_ns} - {verification_ns}"
                )

            row[f"{family}_values"] = value_count
            row[f"{family}_write_ns_raw"] = write_ns
            row[f"{family}_verification_ns"] = verification_ns
            row[f"{family}_write_ns"] = net_write_ns

            total_write_ns += write_ns
            total_verification_ns += verification_ns
            total_net_write_ns += net_write_ns
            total_values += value_count

        row["total_values"] = total_values
        row["total_write_ns_raw"] = total_write_ns
        row["total_verification_ns"] = total_verification_ns
        row["total_write_ns"] = total_net_write_ns
        return row

    def write_csvs(self, output_archive_dir: Path) -> None:
        write_single_row_csv(output_archive_dir / "archive_compression.csv", self.compression_row())
        write_single_row_csv(output_archive_dir / "archive_write.csv", self.write_row())


@dataclass
class TestAnalysis:
    test_dir: Path
    output_dir: Path

    @property
    def test_id(self) -> str:
        return self.test_dir.name

    def find_trace_dir(self) -> Path:
        trace_files = sorted(self.test_dir.glob("*/eztrace_log.pallas"))
        if len(trace_files) != 1:
            raise ValueError(f"Expected exactly one trace file under {self.test_dir}, found {len(trace_files)}")
        return trace_files[0].parent

    def config_values(self) -> dict[str, Any]:
        return parse_key_value_file(self.test_dir / "pallas.config")

    def write_trace_config(self, output_trace_dir: Path, config_values: dict[str, Any]) -> None:
        (output_trace_dir / "trace_config.json").write_text(
            json.dumps(config_values, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )

    def trace_compression_row(self, trace_name: str, archive_analyses: list[ArchiveAnalysis]) -> dict[str, Any]:
        pre_raw_sum = sum(analysis.compression_row()["pre_raw_sum"] for analysis in archive_analyses)
        raw_sum = sum(analysis.compression_row()["raw_sum"] for analysis in archive_analyses)
        compressed_sum = sum(analysis.compression_row()["compressed_sum"] for analysis in archive_analyses)
        effective_ratio = (raw_sum / compressed_sum) if compressed_sum else 0.0
        true_ratio = (pre_raw_sum / compressed_sum) if compressed_sum else 0.0
        return {
            "test_id": self.test_id,
            "trace_name": trace_name,
            "archive_count": len(archive_analyses),
            "pre_raw_sum": pre_raw_sum,
            "raw_sum": raw_sum,
            "compressed_sum": compressed_sum,
            "effective_ratio": effective_ratio,
            "true_ratio": true_ratio,
        }

    def trace_write_row(self, trace_name: str, archive_analyses: list[ArchiveAnalysis]) -> dict[str, Any]:
        row: dict[str, Any] = {
            "test_id": self.test_id,
            "trace_name": trace_name,
            "archive_count": len(archive_analyses),
        }

        total_write_ns_raw = 0
        total_verification_ns = 0
        total_write_ns = 0
        total_values = 0

        archive_write_rows = [analysis.write_row() for analysis in archive_analyses]
        for family in WRITE_TIME_FIELDS:
            family_values = sum_numeric(archive_write_rows, f"{family}_values")
            family_write_raw = sum_numeric(archive_write_rows, f"{family}_write_ns_raw")
            family_verification = sum_numeric(archive_write_rows, f"{family}_verification_ns")
            family_write = sum_numeric(archive_write_rows, f"{family}_write_ns")
            row[f"{family}_values"] = family_values
            row[f"{family}_write_ns_raw"] = family_write_raw
            row[f"{family}_verification_ns"] = family_verification
            row[f"{family}_write_ns"] = family_write
            total_values += family_values
            total_write_ns_raw += family_write_raw
            total_verification_ns += family_verification
            total_write_ns += family_write

        row["total_values"] = total_values
        row["total_write_ns_raw"] = total_write_ns_raw
        row["total_verification_ns"] = total_verification_ns
        row["total_write_ns"] = total_write_ns
        return row

    def prepare(self) -> None:
        trace_dir = self.find_trace_dir()
        trace_metrics = TraceMetrics.load(trace_dir)
        config_values = self.config_values()

        output_trace_dir = self.output_dir / self.test_id / trace_dir.name
        output_trace_dir.mkdir(parents=True, exist_ok=True)
        self.write_trace_config(output_trace_dir, config_values)

        archive_dirs = sorted(path for path in trace_dir.iterdir() if path.is_dir() and path.name.startswith("archive_"))
        archive_analyses: list[ArchiveAnalysis] = []
        for archive_dir in archive_dirs:
            archive_analysis = ArchiveAnalysis.load(self.test_id, archive_dir, trace_metrics)
            archive_analyses.append(archive_analysis)
            archive_output_dir = output_trace_dir / archive_dir.name
            archive_output_dir.mkdir(parents=True, exist_ok=True)
            archive_analysis.write_csvs(archive_output_dir)

        write_single_row_csv(output_trace_dir / "trace_read.csv", trace_metrics.read_row(self.test_id))
        write_single_row_csv(output_trace_dir / "trace_compression.csv", self.trace_compression_row(trace_dir.name, archive_analyses))
        write_single_row_csv(output_trace_dir / "trace_write.csv", self.trace_write_row(trace_dir.name, archive_analyses))


class GenericGraphing:
    @staticmethod
    def _plt():
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

    @staticmethod
    def stacked_bar(
        rows: list[dict[str, Any]],
        category_key: str,
        series_keys: list[str],
        title: str,
        ylabel: str,
        output_path: Path,
        annotation_key: str | None = None,
        annotation_formatter=None,
        annotate_segment_values: bool = False,
        segment_formatter=None,
    ) -> None:
        plt = GenericGraphing._plt()
        categories = [str(row[category_key]) for row in rows]
        x_positions = list(range(len(rows)))
        bottoms = [0.0 for _ in rows]

        fig, ax = plt.subplots(figsize=(10, 6))
        for key in series_keys:
            values = [float(row.get(key, 0.0)) for row in rows]
            bars = ax.bar(x_positions, values, bottom=bottoms, label=key)
            if annotate_segment_values:
                for bar, value, bottom in zip(bars, values, bottoms):
                    if value <= 0:
                        continue
                    text = segment_formatter(value) if segment_formatter else str(value)
                    ax.text(
                        bar.get_x() + bar.get_width() / 2,
                        bottom + value / 2,
                        text,
                        ha="center",
                        va="center",
                        fontsize=7,
                    )
            bottoms = [bottom + value for bottom, value in zip(bottoms, values)]

        ax.set_title(title)
        ax.set_ylabel(ylabel)
        ax.set_xticks(x_positions, categories)
        ax.legend(loc="upper right", fontsize=8, framealpha=0.4)
        ax.grid(axis="y", alpha=0.3)

        if annotation_key is not None:
            for index, row in enumerate(rows):
                annotation_value = row.get(annotation_key)
                if annotation_value is None:
                    continue
                text = annotation_formatter(annotation_value) if annotation_formatter else str(annotation_value)
                ax.text(index, bottoms[index], text, ha="center", va="bottom", fontsize=8)

        fig.tight_layout()
        output_path.parent.mkdir(parents=True, exist_ok=True)
        fig.savefig(output_path)
        plt.close(fig)

    @staticmethod
    def stacked_bar_with_optional_replay(
        rows: list[dict[str, Any]],
        category_key: str,
        primary_series_keys: list[str],
        replay_key: str,
        title: str,
        ylabel: str,
        output_path: Path,
        annotation_key: str | None = None,
        annotation_formatter=None,
        replay_annotation_key: str | None = None,
        replay_annotation_formatter=None,
        annotate_segment_values: bool = False,
        segment_formatter=None,
    ) -> None:
        plt = GenericGraphing._plt()
        categories = [str(row[category_key]) for row in rows]
        x_positions = list(range(len(rows)))
        has_replay = any(float(row.get(replay_key, 0.0)) > 0.0 for row in rows)

        if has_replay:
            fig, (ax_primary, ax_replay) = plt.subplots(
                2,
                1,
                figsize=(10, 9),
                sharex=True,
                gridspec_kw={"height_ratios": [3, 1]},
            )
        else:
            fig, ax_primary = plt.subplots(figsize=(10, 6))
            ax_replay = None

        bottoms = [0.0 for _ in rows]
        for key in primary_series_keys:
            values = [float(row.get(key, 0.0)) for row in rows]
            bars = ax_primary.bar(x_positions, values, bottom=bottoms, label=key)
            if annotate_segment_values:
                for bar, value, bottom in zip(bars, values, bottoms):
                    if value <= 0:
                        continue
                    text = segment_formatter(value) if segment_formatter else str(value)
                    ax_primary.text(
                        bar.get_x() + bar.get_width() / 2,
                        bottom + value / 2,
                        text,
                        ha="center",
                        va="center",
                        fontsize=7,
                    )
            bottoms = [bottom + value for bottom, value in zip(bottoms, values)]

        ax_primary.set_title(title)
        ax_primary.set_ylabel(ylabel)
        ax_primary.legend(loc="upper right", fontsize=8, framealpha=0.4)
        ax_primary.grid(axis="y", alpha=0.3)

        if annotation_key is not None:
            for index, row in enumerate(rows):
                annotation_value = row.get(annotation_key)
                if annotation_value is None:
                    continue
                text = annotation_formatter(annotation_value) if annotation_formatter else str(annotation_value)
                ax_primary.text(index, bottoms[index], text, ha="center", va="bottom", fontsize=8)

        if has_replay and ax_replay is not None:
            replay_values = [float(row.get(replay_key, 0.0)) for row in rows]
            bars = ax_replay.bar(x_positions, replay_values, label=replay_key)
            if annotate_segment_values:
                for bar, value in zip(bars, replay_values):
                    if value <= 0:
                        continue
                    text = segment_formatter(value) if segment_formatter else str(value)
                    ax_replay.text(
                        bar.get_x() + bar.get_width() / 2,
                        value / 2,
                        text,
                        ha="center",
                        va="center",
                        fontsize=7,
                    )
            if replay_annotation_key is not None:
                for index, row in enumerate(rows):
                    annotation_value = row.get(replay_annotation_key)
                    if annotation_value is None:
                        continue
                    text = (
                        replay_annotation_formatter(annotation_value)
                        if replay_annotation_formatter
                        else str(annotation_value)
                    )
                    ax_replay.text(index, replay_values[index], text, ha="center", va="bottom", fontsize=8)

            ax_replay.set_title("Replay Normalized Read Time")
            ax_replay.set_ylabel(ylabel)
            ax_replay.grid(axis="y", alpha=0.3)
            ax_replay.set_xticks(x_positions, categories)
        else:
            ax_primary.set_xticks(x_positions, categories)

        fig.tight_layout()
        output_path.parent.mkdir(parents=True, exist_ok=True)
        fig.savefig(output_path)
        plt.close(fig)

    @staticmethod
    def grouped_bar(
        rows: list[dict[str, Any]],
        category_key: str,
        series_keys: list[str],
        title: str,
        ylabel: str,
        output_path: Path,
        annotate_values: bool = False,
        annotation_formatter=None,
        legend_loc: str = "upper right",
    ) -> None:
        plt = GenericGraphing._plt()
        categories = [str(row[category_key]) for row in rows]
        x_positions = list(range(len(rows)))
        width = 0.8 / max(len(series_keys), 1)

        fig, ax = plt.subplots(figsize=(10, 6))
        for index, key in enumerate(series_keys):
            values = [float(row.get(key, 0.0)) for row in rows]
            shifted = [x + (index - (len(series_keys) - 1) / 2) * width for x in x_positions]
            bars = ax.bar(shifted, values, width=width, label=key)
            if annotate_values:
                for bar, value in zip(bars, values):
                    text = annotation_formatter(value) if annotation_formatter else str(value)
                    ax.text(
                        bar.get_x() + bar.get_width() / 2,
                        bar.get_height(),
                        text,
                        ha="center",
                        va="bottom",
                        fontsize=8,
                    )

        ax.set_title(title)
        ax.set_ylabel(ylabel)
        ax.set_xticks(x_positions, categories)
        ax.legend(loc=legend_loc, fontsize=8, framealpha=0.4)
        ax.grid(axis="y", alpha=0.3)
        fig.tight_layout()
        output_path.parent.mkdir(parents=True, exist_ok=True)
        fig.savefig(output_path)
        plt.close(fig)


@dataclass
class ArchiveGraphAnalysis:
    archive_id: int
    graph_dir: Path
    write_rows: list[dict[str, Any]]
    compression_rows: list[dict[str, Any]]

    @staticmethod
    def _normalize_write_row(row: dict[str, Any]) -> dict[str, Any]:
        total_values = int(row.get("total_values", 0))
        normalized: dict[str, Any] = {
            "test_id": row["test_id"],
            "trace_name": row["trace_name"],
            "archive_id": row["archive_id"],
            "thread_count": row["thread_count"],
            "total_values": total_values,
            "total_write_ns": int(row["total_write_ns"]),
            "total_write_ns_per_value": (float(row["total_write_ns"]) / total_values) if total_values else 0.0,
        }
        for family in WRITE_TIME_FIELDS:
            family_write_ns = float(row.get(f"{family}_write_ns", 0))
            family_values = int(row.get(f"{family}_values", 0))
            normalized[f"{family}_values"] = family_values
            normalized[f"{family}_write_ns_per_total_value"] = (family_write_ns / total_values) if total_values else 0.0
            normalized[f"{family}_write_ns_per_family_value"] = (family_write_ns / family_values) if family_values else 0.0
        return normalized

    def write(self) -> None:
        normalized_rows = [self._normalize_write_row(row) for row in self.write_rows]
        write_csv = self.graph_dir / f"archive_{self.archive_id}" / "archive_write.csv"
        compression_csv = self.graph_dir / f"archive_{self.archive_id}" / "archive_compression.csv"
        write_rows_csv(write_csv, normalized_rows)
        write_rows_csv(compression_csv, self.compression_rows)

        GenericGraphing.stacked_bar(
            normalized_rows,
            category_key="test_id",
            series_keys=[f"{family}_write_ns_per_total_value" for family in WRITE_TIME_FIELDS],
            title=f"Archive {self.archive_id} Normalized Write Time",
            ylabel="write ns / total value",
            output_path=self.graph_dir / f"archive_{self.archive_id}" / "archive_write.png",
            annotation_key="total_write_ns",
            annotation_formatter=lambda value: f"total={int(value) / 1e6:.2f} ms",
            annotate_segment_values=True,
            segment_formatter=lambda value: f"{float(value):.2f}",
        )
        GenericGraphing.grouped_bar(
            self.compression_rows,
            category_key="test_id",
            series_keys=["effective_ratio", "true_ratio"],
            title=f"Archive {self.archive_id} Compression Ratios",
            ylabel="compression ratio",
            output_path=self.graph_dir / f"archive_{self.archive_id}" / "archive_compression.png",
            annotate_values=True,
            annotation_formatter=lambda value: f"{float(value):.3f}",
            legend_loc="upper left",
        )


@dataclass
class OverallGraphAnalysis:
    graph_dir: Path
    trace_write_rows: list[dict[str, Any]]
    trace_compression_rows: list[dict[str, Any]]
    trace_read_rows: list[dict[str, Any]]

    @staticmethod
    def _normalize_write_row(row: dict[str, Any]) -> dict[str, Any]:
        total_values = int(row.get("total_values", 0))
        normalized: dict[str, Any] = {
            "test_id": row["test_id"],
            "trace_name": row["trace_name"],
            "archive_count": row["archive_count"],
            "total_values": total_values,
            "total_write_ns": int(row["total_write_ns"]),
            "total_write_ns_per_value": (float(row["total_write_ns"]) / total_values) if total_values else 0.0,
        }
        for family in WRITE_TIME_FIELDS:
            family_write_ns = float(row.get(f"{family}_write_ns", 0))
            family_values = int(row.get(f"{family}_values", 0))
            normalized[f"{family}_values"] = family_values
            normalized[f"{family}_write_ns_per_total_value"] = (family_write_ns / total_values) if total_values else 0.0
            normalized[f"{family}_write_ns_per_family_value"] = (family_write_ns / family_values) if family_values else 0.0
        return normalized

    @staticmethod
    def _normalize_read_row(row: dict[str, Any]) -> dict[str, Any]:
        load_total_values = (
            int(row.get("event_timestamp_values", 0))
            + int(row.get("sequence_timestamp_values", 0))
            + int(row.get("sequence_duration_values", 0))
            + int(row.get("sequence_exclusive_duration_values", 0))
        )
        replay_tokens = int(row.get("replay_token_occurrences", 0))
        total_units = load_total_values + replay_tokens
        total_read_ns = float(row.get("total_read_ns", 0))
        replay_read_ns = float(row.get("replay_read_ns", 0))
        family_sum = 0.0

        normalized: dict[str, Any] = {
            "test_id": row["test_id"],
            "trace_name": row["trace_name"],
            "mode": row.get("mode", ""),
            "load_total_values": load_total_values,
            "replay_token_occurrences": replay_tokens,
            "total_units": total_units,
            "total_read_ns": int(total_read_ns),
            "replay_read_ns": int(replay_read_ns),
            "total_read_ns_per_unit": (total_read_ns / total_units) if total_units else 0.0,
            "replay_read_ns_per_total_unit": (replay_read_ns / total_units) if total_units else 0.0,
            "replay_read_ns_per_token": (replay_read_ns / replay_tokens) if replay_tokens else 0.0,
        }

        read_value_fields = {
            "event_timestamps": "event_timestamp_values",
            "sequence_timestamps": "sequence_timestamp_values",
            "sequence_durations": "sequence_duration_values",
            "sequence_exclusive_durations": "sequence_exclusive_duration_values",
        }
        read_time_fields = {
            "event_timestamps": "event_timestamps_read_ns",
            "sequence_timestamps": "sequence_timestamps_read_ns",
            "sequence_durations": "sequence_durations_read_ns",
            "sequence_exclusive_durations": "sequence_exclusive_durations_read_ns",
        }

        for family, value_key in read_value_fields.items():
            family_values = int(row.get(value_key, 0))
            family_read_ns = float(row.get(read_time_fields[family], 0))
            normalized[f"{family}_values"] = family_values
            normalized[f"{family}_read_ns_per_total_unit"] = (family_read_ns / total_units) if total_units else 0.0
            normalized[f"{family}_read_ns_per_family_value"] = (family_read_ns / family_values) if family_values else 0.0
            family_sum += family_read_ns

        other_read_ns = total_read_ns - replay_read_ns - family_sum
        if other_read_ns < 0:
            other_read_ns = 0.0
        normalized["other_read_ns_per_total_unit"] = (other_read_ns / total_units) if total_units else 0.0
        return normalized

    def write(self) -> None:
        normalized_write_rows = [self._normalize_write_row(row) for row in self.trace_write_rows]
        normalized_read_rows = [self._normalize_read_row(row) for row in self.trace_read_rows]

        overall_write_csv = self.graph_dir / "overall_write.csv"
        overall_compression_csv = self.graph_dir / "overall_compression.csv"
        overall_read_csv = self.graph_dir / "overall_read.csv"
        write_rows_csv(overall_write_csv, normalized_write_rows)
        write_rows_csv(overall_compression_csv, self.trace_compression_rows)
        write_rows_csv(overall_read_csv, normalized_read_rows)

        GenericGraphing.stacked_bar(
            normalized_write_rows,
            category_key="test_id",
            series_keys=[f"{family}_write_ns_per_total_value" for family in WRITE_TIME_FIELDS],
            title="Overall Normalized Write Time",
            ylabel="write ns / total value",
            output_path=self.graph_dir / "overall_write.png",
            annotation_key="total_write_ns",
            annotation_formatter=lambda value: f"total={int(value) / 1e6:.2f} ms",
            annotate_segment_values=True,
            segment_formatter=lambda value: f"{float(value):.2f}",
        )
        GenericGraphing.grouped_bar(
            self.trace_compression_rows,
            category_key="test_id",
            series_keys=["effective_ratio", "true_ratio"],
            title="Overall Compression Ratios",
            ylabel="compression ratio",
            output_path=self.graph_dir / "overall_compression.png",
            annotate_values=True,
            annotation_formatter=lambda value: f"{float(value):.3f}",
            legend_loc="upper left",
        )
        GenericGraphing.stacked_bar_with_optional_replay(
            normalized_read_rows,
            category_key="test_id",
            primary_series_keys=[
                "event_timestamps_read_ns_per_total_unit",
                "sequence_timestamps_read_ns_per_total_unit",
                "sequence_durations_read_ns_per_total_unit",
                "sequence_exclusive_durations_read_ns_per_total_unit",
                "other_read_ns_per_total_unit",
            ],
            replay_key="replay_read_ns_per_total_unit",
            title="Overall Normalized Read Time",
            ylabel="read ns / total unit",
            output_path=self.graph_dir / "overall_read.png",
            annotation_key="total_read_ns",
            annotation_formatter=lambda value: f"total={int(value) / 1e6:.2f} ms",
            replay_annotation_key="replay_read_ns",
            replay_annotation_formatter=lambda value: f"replay={int(value) / 1e6:.2f} ms",
            annotate_segment_values=True,
            segment_formatter=lambda value: f"{float(value):.2f}",
        )


@dataclass
class RunAnalysis:
    run_dir: Path
    output_dir: Path

    @classmethod
    def load(cls, run_dir: Path) -> "RunAnalysis":
        resolved_run_dir = run_dir.resolve()
        if not resolved_run_dir.is_dir():
            raise FileNotFoundError(f"Run directory does not exist: {resolved_run_dir}")

        output_dir = cls.default_output_dir(resolved_run_dir)
        return cls(run_dir=resolved_run_dir, output_dir=output_dir)

    @staticmethod
    def default_output_dir(run_dir: Path) -> Path:
        name = run_dir.name
        if name.startswith("test-run-"):
            suffix = name[len("test-run-"):]
            output_name = f"run-analysis-{suffix}"
        else:
            output_name = f"{name}-analysis"
        return run_dir.parent / output_name

    def discover_tests(self) -> list[Path]:
        test_dirs = sorted(path for path in self.run_dir.iterdir() if path.is_dir() and path.name.startswith("test_"))
        if not test_dirs:
            raise ValueError(f"No test_* directories found under {self.run_dir}")
        return test_dirs

    def write_metadata(self) -> None:
        self.output_dir.mkdir(parents=True, exist_ok=True)
        metadata = {
            "source_run_dir": str(self.run_dir),
            "output_dir": str(self.output_dir),
            "baseline_test_id": "test_0",
            "phase": "first_pass_csv_generation",
        }
        (self.output_dir / "analysis_metadata.json").write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")

    def prepare(self) -> None:
        self.write_metadata()
        if self.output_dir.exists():
            for child in self.output_dir.iterdir():
                if child.name != "analysis_metadata.json":
                    if child.is_dir():
                        shutil.rmtree(child)
                    else:
                        child.unlink()
        for test_dir in self.discover_tests():
            TestAnalysis(test_dir=test_dir, output_dir=self.output_dir).prepare()

    def prepared_test_dirs(self) -> list[Path]:
        test_dirs = sorted(path for path in self.output_dir.iterdir() if path.is_dir() and path.name.startswith("test_"))
        if not test_dirs:
            raise ValueError(f"No prepared test_* directories found under {self.output_dir}")
        return test_dirs

    def trace_analysis_dir_for_test(self, test_dir: Path) -> Path:
        trace_dirs = [path for path in test_dir.iterdir() if path.is_dir()]
        if len(trace_dirs) != 1:
            raise ValueError(f"Expected exactly one trace analysis directory under {test_dir}, found {len(trace_dirs)}")
        return trace_dirs[0]

    def analyze(self) -> None:
        graph_dir = self.output_dir / "graphs"
        if graph_dir.exists():
            shutil.rmtree(graph_dir)
        graph_dir.mkdir(parents=True, exist_ok=True)

        test_trace_dirs = [self.trace_analysis_dir_for_test(test_dir) for test_dir in self.prepared_test_dirs()]
        trace_write_rows = [read_single_row_csv(trace_dir / "trace_write.csv") for trace_dir in test_trace_dirs]
        trace_compression_rows = [read_single_row_csv(trace_dir / "trace_compression.csv") for trace_dir in test_trace_dirs]
        trace_read_rows = [read_single_row_csv(trace_dir / "trace_read.csv") for trace_dir in test_trace_dirs]

        archive_ids = sorted(
            {
                int(path.name.split("_", 1)[1])
                for trace_dir in test_trace_dirs
                for path in trace_dir.iterdir()
                if path.is_dir() and path.name.startswith("archive_")
            }
        )

        for archive_id in archive_ids:
            archive_rows = []
            compression_rows = []
            for trace_dir in test_trace_dirs:
                archive_dir = trace_dir / f"archive_{archive_id}"
                if not archive_dir.exists():
                    continue
                archive_rows.append(read_single_row_csv(archive_dir / "archive_write.csv"))
                compression_rows.append(read_single_row_csv(archive_dir / "archive_compression.csv"))
            if archive_rows:
                ArchiveGraphAnalysis(
                    archive_id=archive_id,
                    graph_dir=graph_dir,
                    write_rows=archive_rows,
                    compression_rows=compression_rows,
                ).write()

        OverallGraphAnalysis(
            graph_dir=graph_dir,
            trace_write_rows=trace_write_rows,
            trace_compression_rows=trace_compression_rows,
            trace_read_rows=trace_read_rows,
        ).write()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate first-pass hierarchical CSV metrics for a Pallas benchmark run directory.")
    parser.add_argument("run_directory", type=Path, help="Path to a test-run-* directory produced by run_benchmark.py")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    run_analysis = RunAnalysis.load(args.run_directory)
    run_analysis.prepare()
    run_analysis.analyze()
    print(run_analysis.output_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
