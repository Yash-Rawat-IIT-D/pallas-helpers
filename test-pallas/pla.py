from __future__ import annotations

from abc import ABC, abstractmethod
from bisect import bisect_left, insort
from dataclasses import dataclass
from enum import IntEnum
from math import sqrt
from statistics import median
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

    def get_last_fit_diagnostics(self) -> dict | None:
        return None


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


def build_local_segments(split_positions: Sequence[int], value_count: int) -> list[tuple[int, int]]:
    ordered_positions = sorted(split_positions)
    segments: list[tuple[int, int]] = []
    segment_start = 0

    for next_start in ordered_positions:
        segments.append((segment_start, next_start - 1))
        segment_start = next_start
    segments.append((segment_start, value_count - 1))
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


class CandidateState(IntEnum):
    NULL = 0
    FREE = 1
    SUPPRESSED = 2
    ANCHOR = 3


@dataclass
class GammaBlockStats:
    values: list[int]
    deltas: list[float]
    abs_deltas: list[float]
    delta_of_delta: list[float]
    abs_delta_of_delta: list[float]
    baseline_delta: float
    sum_y: list[float]
    sum_y2: list[float]
    sum_xy: list[float]
    sum_d: list[float]
    sum_d2: list[float]
    sum_abs_d: list[float]
    sum_abs_dd: list[float]
    abs_delta_deviation: list[float]
    sum_abs_delta_deviation: list[float]
    spike_scores: list[float]
    global_smoothness: float
    global_fit_score: float
    seed_pool_scores: list[float]
    jarring_threshold: float

    LOCAL_RADIUS = 8

    @classmethod
    def from_values(cls, values: Sequence[int], seed_pool_size: int) -> GammaBlockStats:
        raw_values = [int(value) for value in values]
        deltas = [
            float(raw_values[idx] - raw_values[idx - 1])
            for idx in range(1, len(raw_values))
        ]
        abs_deltas = [abs(value) for value in deltas]
        delta_of_delta = [
            deltas[idx] - deltas[idx - 1]
            for idx in range(1, len(deltas))
        ]
        abs_delta_of_delta = [abs(value) for value in delta_of_delta]
        baseline_delta = float(median(deltas)) if deltas else 0.0
        abs_delta_deviation = [abs(delta - baseline_delta) for delta in deltas]

        sum_y = cls._prefix_sum(raw_values)
        sum_y2 = cls._prefix_sum([float(value) * float(value) for value in raw_values])
        sum_xy = cls._prefix_sum([float(idx) * float(value) for idx, value in enumerate(raw_values)])
        sum_d = cls._prefix_sum(deltas)
        sum_d2 = cls._prefix_sum([value * value for value in deltas])
        sum_abs_d = cls._prefix_sum(abs_deltas)
        sum_abs_dd = cls._prefix_sum(abs_delta_of_delta)
        sum_abs_delta_deviation = cls._prefix_sum(abs_delta_deviation)

        temp = cls(
            values=raw_values,
            deltas=deltas,
            abs_deltas=abs_deltas,
            delta_of_delta=delta_of_delta,
            abs_delta_of_delta=abs_delta_of_delta,
            baseline_delta=baseline_delta,
            sum_y=sum_y,
            sum_y2=sum_y2,
            sum_xy=sum_xy,
            sum_d=sum_d,
            sum_d2=sum_d2,
            sum_abs_d=sum_abs_d,
            sum_abs_dd=sum_abs_dd,
            abs_delta_deviation=abs_delta_deviation,
            sum_abs_delta_deviation=sum_abs_delta_deviation,
            spike_scores=[0.0 for _ in raw_values],
            global_smoothness=0.0,
            global_fit_score=0.0,
            seed_pool_scores=[],
            jarring_threshold=0.0,
        )
        temp.spike_scores = temp._build_spike_scores()
        temp.global_smoothness = temp.segment_smoothness_score(0, len(raw_values) - 1)
        temp.global_fit_score = temp.segment_fit_score(0, len(raw_values) - 1)
        interior_scores = sorted(
            (
                temp.spike_scores[position]
                for position in range(1, max(1, len(raw_values) - 1))
            ),
            reverse=True,
        )
        temp.seed_pool_scores = interior_scores[:seed_pool_size]
        temp.jarring_threshold = temp._compute_jarring_threshold()
        return temp

    @staticmethod
    def _prefix_sum(values: Sequence[float]) -> list[float]:
        prefix = [0.0]
        running = 0.0
        for value in values:
            running += float(value)
            prefix.append(running)
        return prefix

    @staticmethod
    def _range_sum(prefix: Sequence[float], start: int, end_inclusive: int) -> float:
        if end_inclusive < start:
            return 0.0
        return float(prefix[end_inclusive + 1] - prefix[start])

    @staticmethod
    def _sum_of_squares(end_inclusive: int) -> float:
        end_value = float(end_inclusive)
        return end_value * (end_value + 1.0) * (2.0 * end_value + 1.0) / 6.0

    def _range_sum_x(self, start: int, end_inclusive: int) -> float:
        length = end_inclusive - start + 1
        return float(length) * float(start + end_inclusive) / 2.0

    def _range_sum_x2(self, start: int, end_inclusive: int) -> float:
        if end_inclusive < start:
            return 0.0
        low = self._sum_of_squares(start - 1) if start > 0 else 0.0
        return self._sum_of_squares(end_inclusive) - low

    def segment_fit_score(self, start: int, end_inclusive: int) -> float:
        if end_inclusive <= start:
            return 0.0
        count = float(end_inclusive - start + 1)
        sum_x = self._range_sum_x(start, end_inclusive)
        sum_x2 = self._range_sum_x2(start, end_inclusive)
        sum_y = self._range_sum(self.sum_y, start, end_inclusive)
        sum_y2 = self._range_sum(self.sum_y2, start, end_inclusive)
        sum_xy = self._range_sum(self.sum_xy, start, end_inclusive)

        centered_xx = sum_x2 - (sum_x * sum_x) / count
        centered_xy = sum_xy - (sum_x * sum_y) / count
        centered_yy = sum_y2 - (sum_y * sum_y) / count

        if centered_xx <= 0.0:
            return max(0.0, centered_yy) / count
        sse = centered_yy - (centered_xy * centered_xy) / centered_xx
        return max(0.0, sse) / count

    def segment_smoothness_score(self, start: int, end_inclusive: int) -> float:
        delta_start = start
        delta_end = end_inclusive - 1
        if delta_end < delta_start or not self.deltas:
            return 0.0

        delta_count = float(delta_end - delta_start + 1)
        sum_delta = self._range_sum(self.sum_d, delta_start, delta_end)
        sum_delta2 = self._range_sum(self.sum_d2, delta_start, delta_end)
        mean_delta = sum_delta / delta_count
        var_delta = max(0.0, (sum_delta2 / delta_count) - (mean_delta * mean_delta))
        std_delta = sqrt(var_delta)

        dod_start = start
        dod_end = end_inclusive - 2
        if dod_end < dod_start or not self.abs_delta_of_delta:
            mean_abs_dd = 0.0
        else:
            dod_count = float(dod_end - dod_start + 1)
            mean_abs_dd = self._range_sum(self.sum_abs_dd, dod_start, dod_end) / dod_count

        return mean_abs_dd + 0.5 * std_delta

    def candidate_spike_score(self, position: int) -> float:
        return self.spike_scores[position]

    def is_jarring_position(self, position: int) -> bool:
        return self.candidate_spike_score(position) >= self.jarring_threshold

    def _build_spike_scores(self) -> list[float]:
        scores = [0.0 for _ in self.values]
        if len(self.values) < 3:
            return scores

        for position in range(1, len(self.values) - 1):
            delta_idx = position - 1
            local_delta_start = max(0, delta_idx - self.LOCAL_RADIUS)
            local_delta_end = min(len(self.deltas) - 1, delta_idx + self.LOCAL_RADIUS)
            local_delta_count = float(local_delta_end - local_delta_start + 1)
            local_mean_abs_deviation = (
                self._range_sum(self.sum_abs_delta_deviation, local_delta_start, local_delta_end)
                / local_delta_count
            )

            local_dod_start = max(0, delta_idx - self.LOCAL_RADIUS)
            local_dod_end = min(len(self.abs_delta_of_delta) - 1, delta_idx + self.LOCAL_RADIUS)
            if local_dod_end >= local_dod_start and self.abs_delta_of_delta:
                local_dod_count = float(local_dod_end - local_dod_start + 1)
                local_mean_abs_dod = (
                    self._range_sum(self.sum_abs_dd, local_dod_start, local_dod_end)
                    / local_dod_count
                )
            else:
                local_mean_abs_dod = 0.0

            candidate_sharpness = 0.0
            if 0 <= delta_idx - 1 < len(self.abs_delta_of_delta):
                candidate_sharpness = max(candidate_sharpness, self.abs_delta_of_delta[delta_idx - 1])
            if 0 <= delta_idx < len(self.abs_delta_of_delta):
                candidate_sharpness = max(candidate_sharpness, self.abs_delta_of_delta[delta_idx])

            scores[position] = (
                self.abs_delta_deviation[delta_idx] / (1.0 + local_mean_abs_deviation)
                + 0.75 * candidate_sharpness / (1.0 + local_mean_abs_dod)
            )
        return scores

    def _compute_jarring_threshold(self) -> float:
        if not self.seed_pool_scores:
            return 0.0
        ordered_scores = sorted(self.seed_pool_scores)
        pivot_index = int(0.75 * (len(ordered_scores) - 1))
        return float(ordered_scores[pivot_index])


class PostMortemGammaPLA(PLAAlgorithm):
    name = "postmortem-gamma"
    K = 16
    SEED_COUNT = 16
    SEED_POOL_SIZE = 64
    CANDIDATES_PER_SEGMENT = 4
    RIGHT_WINDOWS = (4, 16, 32, 64, 128, 256, 512)
    LEFT_WINDOWS = (4, 16, 32, 64)
    SUPPRESSED_OVERLAP_THRESHOLD = 0.6
    MIN_SEGMENT_LENGTH = 8
    MIN_GAIN_RATIO = 0.05
    MIN_GAIN_ABS = 1e-6

    def __init__(self) -> None:
        self._last_fit_diagnostics: dict | None = None

    def get_last_fit_diagnostics(self) -> dict | None:
        return self._last_fit_diagnostics

    def fit(self, indices: Sequence[int], values: Sequence[int]) -> list[LineSegment]:
        self._last_fit_diagnostics = None
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

        stats = GammaBlockStats.from_values(values, self.SEED_POOL_SIZE)
        candidate_states = self._build_initial_states(len(values))

        seed_pool = self._build_seed_pool(stats, candidate_states)
        selected_seeds = self._select_initial_seeds(stats, seed_pool)
        for seed in selected_seeds:
            candidate_states[seed] = CandidateState.ANCHOR

        for seed in selected_seeds:
            self._apply_anchor_suppression(stats, candidate_states, seed)

        anchor_positions = sorted(selected_seeds)
        refinement_history: list[dict] = []
        frozen_segments: set[tuple[int, int]] = set()
        target_anchor_count = min(self.K, len(values) - 2)

        while len(anchor_positions) < target_anchor_count:
            segments = build_local_segments(anchor_positions, len(values))
            best_refinement = self._choose_best_refinement(
                stats,
                candidate_states,
                segments,
                frozen_segments,
            )
            if best_refinement is None:
                break

            if best_refinement["gain"] <= best_refinement["gain_threshold"]:
                frozen_segments.add(best_refinement["segment"])
                continue

            split_position = int(best_refinement["split_position"])
            insort(anchor_positions, split_position)
            candidate_states[split_position] = CandidateState.ANCHOR
            refinement_history.append(
                {
                    "segment_start": int(indices[best_refinement["segment"][0]]),
                    "segment_end": int(indices[best_refinement["segment"][1]]),
                    "split_index": int(indices[split_position]),
                    "parent_score": round(best_refinement["parent_score"], 6),
                    "left_score": round(best_refinement["left_score"], 6),
                    "right_score": round(best_refinement["right_score"], 6),
                    "gain": round(best_refinement["gain"], 6),
                }
            )

            if stats.is_jarring_position(split_position):
                self._apply_anchor_suppression(stats, candidate_states, split_position)

        forced_fill_indices = self._fill_remaining_anchors(
            stats,
            candidate_states,
            anchor_positions,
            target_anchor_count,
        )
        segments = build_segments_from_split_positions(indices, values, anchor_positions)
        final_segment_scores = [
            {
                "segment_start": int(indices[start]),
                "segment_end": int(indices[end]),
                "normalized_badness": round(stats.segment_fit_score(start, end), 6),
            }
            for start, end in build_local_segments(anchor_positions, len(values))
        ]
        self._last_fit_diagnostics = {
            "seed_indices": [int(indices[position]) for position in selected_seeds],
            "final_anchor_indices": [int(indices[position]) for position in anchor_positions],
            "state_counts": self._count_states(candidate_states),
            "refinement_history": refinement_history,
            "forced_fill_indices": [int(indices[position]) for position in forced_fill_indices],
            "final_segment_scores": final_segment_scores,
        }
        return segments

    def _build_initial_states(self, value_count: int) -> list[CandidateState]:
        states = [CandidateState.FREE for _ in range(value_count)]
        if value_count >= 1:
            states[0] = CandidateState.NULL
            states[-1] = CandidateState.NULL
        return states

    def _build_seed_pool(
        self,
        stats: GammaBlockStats,
        candidate_states: Sequence[CandidateState],
    ) -> list[int]:
        ranked_candidates = sorted(
            (
                position
                for position in range(1, len(candidate_states) - 1)
                if candidate_states[position] == CandidateState.FREE
            ),
            key=stats.candidate_spike_score,
            reverse=True,
        )
        return ranked_candidates[: self.SEED_POOL_SIZE]

    def _select_initial_seeds(
        self,
        stats: GammaBlockStats,
        seed_pool: Sequence[int],
    ) -> list[int]:
        if not seed_pool:
            return []

        seeds = [int(seed_pool[0])]
        remaining = [int(position) for position in seed_pool[1:]]
        while remaining and len(seeds) < min(self.SEED_COUNT, len(seed_pool)):
            next_seed = max(
                remaining,
                key=lambda position: (
                    min(abs(position - seed) for seed in seeds),
                    stats.candidate_spike_score(position),
                ),
            )
            seeds.append(next_seed)
            remaining.remove(next_seed)
        seeds.sort()
        return seeds

    def _apply_anchor_suppression(
        self,
        stats: GammaBlockStats,
        candidate_states: list[CandidateState],
        anchor_position: int,
    ) -> None:
        self._suppress_direction(
            stats,
            candidate_states,
            anchor_position,
            direction=1,
            windows=self.RIGHT_WINDOWS,
        )
        self._suppress_direction(
            stats,
            candidate_states,
            anchor_position,
            direction=-1,
            windows=self.LEFT_WINDOWS,
        )

    def _suppress_direction(
        self,
        stats: GammaBlockStats,
        candidate_states: list[CandidateState],
        anchor_position: int,
        direction: int,
        windows: Sequence[int],
    ) -> None:
        smoothness_limit = max(stats.global_smoothness, 1e-6)
        value_count = len(candidate_states)

        for window_size in windows:
            if direction > 0:
                raw_start = anchor_position + 1
                raw_end = min(value_count - 2, anchor_position + window_size)
            else:
                raw_start = max(1, anchor_position - window_size)
                raw_end = anchor_position - 1

            if raw_end < raw_start:
                break

            blocked_position = self._first_blocking_position(
                stats,
                candidate_states,
                anchor_position,
                raw_start,
                raw_end,
                direction,
            )
            effective_start = raw_start
            effective_end = raw_end
            if blocked_position is not None:
                if direction > 0:
                    effective_end = blocked_position - 1
                else:
                    effective_start = blocked_position + 1

            if effective_end < effective_start:
                break

            if direction > 0:
                smooth_start = anchor_position
                smooth_end = effective_end
            else:
                smooth_start = effective_start
                smooth_end = anchor_position

            if stats.segment_smoothness_score(smooth_start, smooth_end) > smoothness_limit:
                break
            if self._suppressed_overlap(candidate_states, effective_start, effective_end) > self.SUPPRESSED_OVERLAP_THRESHOLD:
                break

            for position in range(effective_start, effective_end + 1):
                if candidate_states[position] == CandidateState.FREE:
                    candidate_states[position] = CandidateState.SUPPRESSED

            if blocked_position is not None:
                break

    def _first_blocking_position(
        self,
        stats: GammaBlockStats,
        candidate_states: Sequence[CandidateState],
        anchor_position: int,
        start: int,
        end_inclusive: int,
        direction: int,
    ) -> int | None:
        positions = range(start, end_inclusive + 1)
        if direction < 0:
            positions = range(end_inclusive, start - 1, -1)

        for position in positions:
            if position == anchor_position:
                continue
            if candidate_states[position] == CandidateState.ANCHOR:
                return position
            if stats.is_jarring_position(position):
                return position
        return None

    def _suppressed_overlap(
        self,
        candidate_states: Sequence[CandidateState],
        start: int,
        end_inclusive: int,
    ) -> float:
        length = end_inclusive - start + 1
        if length <= 0:
            return 0.0
        suppressed_count = sum(
            1
            for position in range(start, end_inclusive + 1)
            if candidate_states[position] == CandidateState.SUPPRESSED
        )
        return float(suppressed_count) / float(length)

    def _choose_best_refinement(
        self,
        stats: GammaBlockStats,
        candidate_states: Sequence[CandidateState],
        segments: Sequence[tuple[int, int]],
        frozen_segments: set[tuple[int, int]],
    ) -> dict | None:
        ranked_segments = sorted(
            (
                (segment, stats.segment_fit_score(*segment))
                for segment in segments
                if segment not in frozen_segments
            ),
            key=lambda item: item[1],
            reverse=True,
        )

        for segment, parent_score in ranked_segments:
            start, end_inclusive = segment
            if end_inclusive - start + 1 < self.MIN_SEGMENT_LENGTH:
                frozen_segments.add(segment)
                continue

            candidate_positions = self._candidate_positions_in_segment(
                candidate_states,
                start,
                end_inclusive,
            )
            if not candidate_positions:
                frozen_segments.add(segment)
                continue

            candidate_positions = sorted(
                candidate_positions,
                key=stats.candidate_spike_score,
                reverse=True,
            )[: self.CANDIDATES_PER_SEGMENT]

            best_candidate = None
            for split_position in candidate_positions:
                left_score = stats.segment_fit_score(start, split_position - 1)
                right_score = stats.segment_fit_score(split_position, end_inclusive)
                gain = parent_score - (left_score + right_score)
                candidate = {
                    "segment": segment,
                    "split_position": split_position,
                    "parent_score": parent_score,
                    "left_score": left_score,
                    "right_score": right_score,
                    "gain": gain,
                    "gain_threshold": max(self.MIN_GAIN_ABS, parent_score * self.MIN_GAIN_RATIO),
                }
                if best_candidate is None or candidate["gain"] > best_candidate["gain"]:
                    best_candidate = candidate

            if best_candidate is not None:
                return best_candidate
            frozen_segments.add(segment)
        return None

    def _candidate_positions_in_segment(
        self,
        candidate_states: Sequence[CandidateState],
        start: int,
        end_inclusive: int,
    ) -> list[int]:
        free_candidates = [
            position
            for position in range(max(1, start + 1), min(len(candidate_states) - 1, end_inclusive) + 1)
            if candidate_states[position] == CandidateState.FREE
        ]
        if free_candidates:
            return free_candidates
        return [
            position
            for position in range(max(1, start + 1), min(len(candidate_states) - 1, end_inclusive) + 1)
            if candidate_states[position] == CandidateState.SUPPRESSED
        ]

    def _count_states(self, candidate_states: Sequence[CandidateState]) -> dict[str, int]:
        return {
            "null": sum(1 for state in candidate_states if state == CandidateState.NULL),
            "free": sum(1 for state in candidate_states if state == CandidateState.FREE),
            "suppressed": sum(1 for state in candidate_states if state == CandidateState.SUPPRESSED),
            "anchor": sum(1 for state in candidate_states if state == CandidateState.ANCHOR),
        }

    def _fill_remaining_anchors(
        self,
        stats: GammaBlockStats,
        candidate_states: list[CandidateState],
        anchor_positions: list[int],
        target_anchor_count: int,
    ) -> list[int]:
        if len(anchor_positions) >= target_anchor_count:
            return []

        forced_fill_positions: list[int] = []
        for allowed_state in (CandidateState.FREE, CandidateState.SUPPRESSED):
            candidates = sorted(
                (
                    position
                    for position in range(1, len(candidate_states) - 1)
                    if candidate_states[position] == allowed_state
                ),
                key=stats.candidate_spike_score,
                reverse=True,
            )
            for position in candidates:
                if len(anchor_positions) >= target_anchor_count:
                    return forced_fill_positions
                insort(anchor_positions, position)
                candidate_states[position] = CandidateState.ANCHOR
                forced_fill_positions.append(position)

        if len(anchor_positions) >= target_anchor_count:
            return forced_fill_positions

        residual_positions = sorted(
            (
                position
                for position in range(1, len(candidate_states) - 1)
                if candidate_states[position] != CandidateState.ANCHOR
            ),
            key=stats.candidate_spike_score,
            reverse=True,
        )
        for position in residual_positions:
            if len(anchor_positions) >= target_anchor_count:
                break
            insort(anchor_positions, position)
            candidate_states[position] = CandidateState.ANCHOR
            forced_fill_positions.append(position)
        return forced_fill_positions


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
    if normalized in {
        "postmortem-gamma",
        "postmortem_gamma",
        "gamma",
        "gamma-pla",
    }:
        return PostMortemGammaPLA()
    raise ValueError(f"unknown PLA algorithm: {name}")


def predict_segment_value(segment: LineSegment, logical_index: int) -> float:
    if segment.start_index == segment.end_index:
        return float(segment.start_value)
    position = (logical_index - segment.start_index) / (segment.end_index - segment.start_index)
    return float(segment.start_value) + position * (segment.end_value - segment.start_value)


def materialize_segment_predictions(
    indices: Sequence[int],
    segments: Sequence[LineSegment],
) -> list[float]:
    if not indices or not segments:
        return []

    predictions: list[float] = []
    segment_idx = 0
    for logical_index in indices:
        while (
            segment_idx + 1 < len(segments)
            and int(logical_index) > segments[segment_idx].end_index
        ):
            segment_idx += 1
        predictions.append(
            predict_segment_value(segments[segment_idx], int(logical_index))
        )
    return predictions


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
