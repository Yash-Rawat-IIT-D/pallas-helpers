from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from math import sqrt
from random import Random
from statistics import median
from typing import Sequence


@dataclass(frozen=True)
class BlockMaxError:
    block_index: int
    logical_index: int
    max_abs_error: float


class DurationPredictionAlgorithm(ABC):
    name = "base"

    @abstractmethod
    def predict_block(self, indices: Sequence[int], values: Sequence[int]) -> list[float]:
        raise NotImplementedError

    def get_last_fit_diagnostics(self) -> dict | None:
        return None


class BaselineSpikeDurationPredictor(DurationPredictionAlgorithm):
    name = "baseline-spikes"
    TOP_K = 32
    EXACT_COUNT_CAP = 8
    MAX_GROUPS = 4
    MIN_GROUP_SIZE = 2
    RELATIVE_GROUP_TOLERANCE = 0.20
    ABSOLUTE_GROUP_TOLERANCE = 96.0
    MIN_SPIKE_RESIDUAL = 64.0
    BASELINE_CLIP_SIGMA = 2.5
    BASELINE_MIN_CLIP_RADIUS = 32.0
    BASELINE_MAX_SAMPLE_SIGMA = 3.0

    def __init__(self) -> None:
        self._last_fit_diagnostics: dict | None = None

    def get_last_fit_diagnostics(self) -> dict | None:
        return self._last_fit_diagnostics

    def predict_block(self, indices: Sequence[int], values: Sequence[int]) -> list[float]:
        self._last_fit_diagnostics = None
        if not values:
            return []

        raw_values = [int(value) for value in values]
        initial_baseline = int(round(median(raw_values)))
        predictions = [float(initial_baseline) for _ in raw_values]
        residuals = [int(value - initial_baseline) for value in raw_values]

        abs_residuals = [abs(residual) for residual in residuals]
        median_abs_residual = float(median(abs_residuals)) if abs_residuals else 0.0
        spike_threshold = max(self.MIN_SPIKE_RESIDUAL, 3.0 * median_abs_residual)

        candidates = sorted(
            (
                (position, residual)
                for position, residual in enumerate(residuals)
                if residual >= spike_threshold
            ),
            key=lambda item: item[1],
            reverse=True,
        )[: self.TOP_K]

        exact_count = min(self.EXACT_COUNT_CAP, max(2, self.TOP_K // 2), len(candidates))
        exact_candidates = candidates[:exact_count]
        exact_positions = {position for position, _ in exact_candidates}
        for position, _ in exact_candidates:
            predictions[position] = float(raw_values[position])

        grouped_candidates = [
            (position, residual)
            for position, residual in candidates[exact_count:]
            if position not in exact_positions
        ]
        grouped_buckets: list[dict] = []
        grouped_positions: set[int] = set()

        while grouped_candidates and len(grouped_buckets) < self.MAX_GROUPS:
            seed_position, seed_residual = grouped_candidates[0]
            tolerance = max(
                self.ABSOLUTE_GROUP_TOLERANCE,
                abs(float(seed_residual)) * self.RELATIVE_GROUP_TOLERANCE,
            )
            bucket_members = [
                (position, residual)
                for position, residual in grouped_candidates
                if abs(float(residual) - float(seed_residual)) <= tolerance
            ]
            grouped_candidates = [
                (position, residual)
                for position, residual in grouped_candidates
                if abs(float(residual) - float(seed_residual)) > tolerance
            ]

            if len(bucket_members) < self.MIN_GROUP_SIZE:
                continue

            representative_residual = int(
                round(sum(residual for _, residual in bucket_members) / len(bucket_members))
            )
            representative_value = initial_baseline + representative_residual
            member_positions = sorted(position for position, _ in bucket_members)
            for position in member_positions:
                predictions[position] = float(representative_value)
                grouped_positions.add(position)

            grouped_buckets.append(
                {
                    "seed_position": int(indices[seed_position]),
                    "representative_value": representative_value,
                    "representative_residual": representative_residual,
                    "positions": [int(indices[position]) for position in member_positions],
                    "count": len(member_positions),
                }
            )

        selected_positions = set(exact_positions)
        selected_positions.update(grouped_positions)

        baseline_mean, baseline_std, baseline_sample_count = self._fit_baseline_noise_model(
            raw_values,
            selected_positions,
        )
        self._fill_baseline_predictions(
            predictions,
            indices,
            selected_positions,
            baseline_mean,
            baseline_std,
        )

        self._last_fit_diagnostics = {
            "baseline": round(baseline_mean, 3),
            "baseline_std": round(baseline_std, 3),
            "baseline_sample_count": baseline_sample_count,
            "initial_baseline": initial_baseline,
            "spike_threshold": round(spike_threshold, 3),
            "candidate_count": len(candidates),
            "exact_count": len(exact_candidates),
            "exact_positions": [int(indices[position]) for position, _ in exact_candidates],
            "groups": grouped_buckets,
        }
        return predictions

    def _fit_baseline_noise_model(
        self,
        raw_values: Sequence[int],
        selected_positions: set[int],
    ) -> tuple[float, float, int]:
        baseline_values = [
            float(value)
            for position, value in enumerate(raw_values)
            if position not in selected_positions
        ]
        if not baseline_values:
            fallback = float(median(raw_values)) if raw_values else 0.0
            return fallback, 0.0, 0

        robust_center = float(median(baseline_values))
        abs_deviations = [abs(value - robust_center) for value in baseline_values]
        mad = float(median(abs_deviations)) if abs_deviations else 0.0
        robust_sigma = 1.4826 * mad
        clip_radius = max(
            self.BASELINE_MIN_CLIP_RADIUS,
            robust_sigma * self.BASELINE_CLIP_SIGMA,
        )

        clipped_values = [
            value
            for value in baseline_values
            if abs(value - robust_center) <= clip_radius
        ]
        if not clipped_values:
            clipped_values = baseline_values

        mean_value = sum(clipped_values) / float(len(clipped_values))
        if len(clipped_values) <= 1:
            return mean_value, 0.0, len(clipped_values)

        variance = sum(
            (value - mean_value) * (value - mean_value)
            for value in clipped_values
        ) / float(len(clipped_values))
        std_value = sqrt(max(0.0, variance))
        return mean_value, std_value, len(clipped_values)

    def _fill_baseline_predictions(
        self,
        predictions: list[float],
        indices: Sequence[int],
        selected_positions: set[int],
        baseline_mean: float,
        baseline_std: float,
    ) -> None:
        if baseline_std <= 1e-9:
            rounded_mean = float(max(0, round(baseline_mean)))
            for position in range(len(predictions)):
                if position not in selected_positions:
                    predictions[position] = rounded_mean
            return

        seed = (
            (int(indices[0]) << 32)
            ^ int(indices[-1])
            ^ len(indices)
            ^ int(round(baseline_mean))
            ^ len(selected_positions)
        )
        rng = Random(seed)
        sample_low = baseline_mean - self.BASELINE_MAX_SAMPLE_SIGMA * baseline_std
        sample_high = baseline_mean + self.BASELINE_MAX_SAMPLE_SIGMA * baseline_std

        for position in range(len(predictions)):
            if position in selected_positions:
                continue
            sampled_value = rng.gauss(baseline_mean, baseline_std)
            sampled_value = min(max(sampled_value, sample_low), sample_high)
            predictions[position] = float(max(0, round(sampled_value)))


def create_duration_algorithm(name: str) -> DurationPredictionAlgorithm:
    normalized = name.strip().lower()
    if normalized in {"baseline-spikes", "baseline_spikes", "duration-default", "default"}:
        return BaselineSpikeDurationPredictor()
    raise ValueError(f"unknown duration algorithm: {name}")


def compute_prediction_block_max_abs_error(
    block_index: int,
    indices: Sequence[int],
    values: Sequence[int],
    predictions: Sequence[float],
) -> BlockMaxError | None:
    if not indices or not values or not predictions:
        return None

    worst_error = -1.0
    worst_logical_index = int(indices[0])
    for logical_index, actual_value, predicted_value in zip(indices, values, predictions):
        abs_error = abs(float(actual_value) - float(predicted_value))
        if abs_error > worst_error:
            worst_error = abs_error
            worst_logical_index = int(logical_index)

    return BlockMaxError(
        block_index=block_index,
        logical_index=worst_logical_index,
        max_abs_error=worst_error,
    )
