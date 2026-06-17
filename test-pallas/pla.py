from __future__ import annotations

from abc import ABC, abstractmethod
from bisect import bisect_left
from dataclasses import dataclass
from typing import Sequence


@dataclass(frozen=True)
class LineSegment:
    start_index: int
    end_index: int
    start_value: int
    end_value: int


@dataclass(frozen=True)
class BlockMaxError:
    block_index: int
    logical_index: int
    max_abs_error: float


class PLAAlgorithm(ABC):
    name = "base"

    @abstractmethod
    def fit(self, indices: Sequence[int], values: Sequence[int]) -> list[LineSegment]:
        raise NotImplementedError


class FirstLastPLA(PLAAlgorithm):
    name = "first-last"

    def fit(self, indices: Sequence[int], values: Sequence[int]) -> list[LineSegment]:
        if not indices or not values:
            return []
        return [
            LineSegment(
                start_index=int(indices[0]),
                end_index=int(indices[-1]),
                start_value=int(values[0]),
                end_value=int(values[-1]),
            )
        ]


def build_segments_from_split_positions(
    indices: Sequence[int],
    values: Sequence[int],
    split_positions: Sequence[int],
) -> list[LineSegment]:
    ordered_split_positions = sorted(split_positions)
    segments: list[LineSegment] = []
    segment_start = 0

    for next_start in ordered_split_positions:
        segment_end = next_start - 1
        segments.append(
            LineSegment(
                start_index=int(indices[segment_start]),
                end_index=int(indices[segment_end]),
                start_value=int(values[segment_start]),
                end_value=int(values[segment_end]),
            )
        )
        segment_start = next_start

    segments.append(
        LineSegment(
            start_index=int(indices[segment_start]),
            end_index=int(indices[-1]),
            start_value=int(values[segment_start]),
            end_value=int(values[-1]),
        )
    )
    return segments


class PostMortemAlphaPLA(PLAAlgorithm):
    name = "postmortem-alpha"
    K = 8

    def fit(self, indices: Sequence[int], values: Sequence[int]) -> list[LineSegment]:
        if not indices or not values:
            return []
        if len(indices) == 1:
            return [
                LineSegment(
                    start_index=int(indices[0]),
                    end_index=int(indices[0]),
                    start_value=int(values[0]),
                    end_value=int(values[0]),
                )
            ]

        delta_anchor_positions = sorted(
            range(1, len(values)),
            key=lambda idx: abs(int(values[idx]) - int(values[idx - 1])),
            reverse=True,
        )
        return build_segments_from_split_positions(
            indices,
            values,
            sorted(delta_anchor_positions[: self.K]),
        )


class PostMortemBetaPLA(PLAAlgorithm):
    name = "postmortem-beta"
    K = 30
    MIN_WINDOW = 10

    def fit(self, indices: Sequence[int], values: Sequence[int]) -> list[LineSegment]:
        if not indices or not values:
            return []
        if len(indices) == 1:
            return [
                LineSegment(
                    start_index=int(indices[0]),
                    end_index=int(indices[0]),
                    start_value=int(values[0]),
                    end_value=int(values[0]),
                )
            ]

        delta_anchor_positions = sorted(
            range(1, len(values)),
            key=lambda idx: abs(int(values[idx]) - int(values[idx - 1])),
            reverse=True,
        )
        target_split_count = min(self.K, len(delta_anchor_positions))
        if target_split_count == 0:
            return FirstLastPLA().fit(indices, values)

        seed_count = min(2, target_split_count)
        selected_splits = sorted(delta_anchor_positions[:seed_count])
        remaining_candidates = delta_anchor_positions[seed_count:]
        window = max(len(values) // 2, self.MIN_WINDOW)

        while len(selected_splits) < target_split_count and window >= self.MIN_WINDOW:
            accepted_this_pass: list[int] = []

            for candidate in remaining_candidates:
                insert_at = bisect_left(selected_splits, candidate)
                left_boundary = 0 if insert_at == 0 else selected_splits[insert_at - 1]
                right_boundary = len(values) if insert_at == len(selected_splits) else selected_splits[insert_at]
                left_segment_size = candidate - left_boundary
                right_segment_size = right_boundary - candidate

                if left_segment_size > window or right_segment_size > window:
                    selected_splits.insert(insert_at, candidate)
                    accepted_this_pass.append(candidate)
                    if len(selected_splits) == target_split_count:
                        break

            if accepted_this_pass:
                accepted_candidates = set(accepted_this_pass)
                remaining_candidates = [
                    candidate
                    for candidate in remaining_candidates
                    if candidate not in accepted_candidates
                ]

            if len(selected_splits) == target_split_count:
                break
            if window == self.MIN_WINDOW:
                break
            window = max(window // 2, self.MIN_WINDOW)

        if len(selected_splits) < target_split_count:
            missing_count = target_split_count - len(selected_splits)
            selected_splits.extend(remaining_candidates[:missing_count])
            selected_splits.sort()

        return build_segments_from_split_positions(indices, values, selected_splits)


def create_pla_algorithm(name: str) -> PLAAlgorithm:
    normalized = name.strip().lower()
    if normalized in {"first-last", "first_last", "default"}:
        return FirstLastPLA()
    if normalized in {
        "postmortem-alpha",
        "postmortem_alpha",
        "alpha",
        "alpha-pla",
    }:
        return PostMortemAlphaPLA()
    if normalized in {
        "postmortem-beta",
        "postmortem_beta",
        "beta",
        "beta-pla",
    }:
        return PostMortemBetaPLA()
    raise ValueError(f"unknown PLA algorithm: {name}")


def predict_segment_value(segment: LineSegment, logical_index: int) -> float:
    if segment.start_index == segment.end_index:
        return float(segment.start_value)
    position = (logical_index - segment.start_index) / (segment.end_index - segment.start_index)
    return float(segment.start_value) + position * (segment.end_value - segment.start_value)


def compute_block_max_abs_error(
    block_index: int,
    indices: Sequence[int],
    values: Sequence[int],
    segments: Sequence[LineSegment],
) -> BlockMaxError | None:
    if not indices or not values or not segments:
        return None

    worst_error = -1.0
    worst_logical_index = int(indices[0])
    segment_idx = 0

    for logical_index, actual_value in zip(indices, values):
        while (
            segment_idx + 1 < len(segments)
            and int(logical_index) > segments[segment_idx].end_index
        ):
            segment_idx += 1
        predicted_value = predict_segment_value(segments[segment_idx], int(logical_index))
        abs_error = abs(float(actual_value) - predicted_value)
        if abs_error > worst_error:
            worst_error = abs_error
            worst_logical_index = int(logical_index)

    return BlockMaxError(
        block_index=block_index,
        logical_index=worst_logical_index,
        max_abs_error=worst_error,
    )
