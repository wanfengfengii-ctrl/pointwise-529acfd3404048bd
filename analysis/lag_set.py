from collections.abc import Iterable
from dataclasses import dataclass
from fractions import Fraction

from analysis.domain import EligibleCell, eligible_cells
from analysis.loss import build_statistics_cells
from handoff.evidence import CurveEvidence
from trial.rationals import RationalInput, parse_rational


@dataclass(frozen=True, slots=True)
class LagResult:
    minimum_mse: Fraction | None
    intervals: tuple[tuple[Fraction, Fraction], ...]


def coalesce_minimizers(
    intervals: Iterable[tuple[Fraction, Fraction]],
) -> tuple[tuple[Fraction, Fraction], ...]:
    merged = []
    for lower, upper in sorted(intervals):
        if merged and lower <= merged[-1][1]:
            previous_lower, previous_upper = merged[-1]
            merged[-1] = (previous_lower, max(previous_upper, upper))
        else:
            merged.append((lower, upper))
    return tuple(merged)


def _cell_minimum(cell: EligibleCell) -> tuple[Fraction, tuple[Fraction, Fraction]]:
    left_score = cell.left.mse
    right_score = cell.right.mse
    # A ratio of affine functions with positive denominator is monotone or constant.
    if left_score == right_score:
        return left_score, (cell.lower, cell.upper)
    if left_score < right_score:
        return left_score, (cell.lower, cell.lower)
    return right_score, (cell.upper, cell.upper)


def optimal_lags(
    a: CurveEvidence, b: CurveEvidence,
    lower: RationalInput, upper: RationalInput, min_seconds: RationalInput,
) -> LagResult:
    lower, upper, min_seconds = map(parse_rational, (lower, upper, min_seconds))
    if min_seconds <= 0:
        raise ValueError('minimum common time must be positive')
    cells = build_statistics_cells(a, b, lower, upper)
    best = None
    winners = []
    for cell in eligible_cells(cells, min_seconds):
        score, interval = _cell_minimum(cell)
        if best is None or score < best:
            best = score
            winners = [interval]
        elif score == best:
            winners.append(interval)
    return LagResult(best, coalesce_minimizers(winners))
