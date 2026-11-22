"""Exact trimmed-lag optimization over joint residual evidence.

For every real lag ``t`` in the fixed window, the joint evidence gives the
common effective spans as rows ``(duration d_i(t), squared error q_i)`` where
each ``d_i`` is affine on its cell.  Trimming may remove any divisible part of
the common effective time up to the declared budget ``T`` while retaining at
least ``m`` seconds.  Removing the highest-error time first minimizes the
retained mean squared error, so at a feasible lag (``D(t) >= m``):

    R(t) = max(m, D(t) - T)          actual retained seconds
    M(t) = N(t) / R(t)

where ``N(t)`` is the squared-error integral after greedy trimming.  All
breakpoints of ``D``, ``R`` and the retained component set are rational;
between them ``N`` and ``R`` are affine and the ratio is monotone or constant.
The global minimum therefore occurs at rational breakpoints, and constant
pieces of the ratio yield whole rational closed intervals.  Ties and touching
pieces are coalesced and isolated points are kept as singleton intervals.
"""
from dataclasses import dataclass
from fractions import Fraction

from analysis.lag_set import coalesce_minimizers
from handoff.joint import JointCell, JointEvidence, JointRow
from trial.rationals import parse_rational


@dataclass(frozen=True, slots=True)
class TrimResult:
    minimum_mse: Fraction | None
    intervals: tuple[tuple[Fraction, Fraction], ...]


def _active_rows(cell: JointCell, lag: Fraction) -> tuple[JointRow, ...]:
    return tuple(row for row in cell.rows if row.duration_at(lag) > 0)


def _evaluate(cell: JointCell, lag: Fraction, trim: Fraction, minimum: Fraction):
    """Greedy high-error-first trimmed MSE at a single lag."""
    active = _active_rows(cell, lag)
    common = sum((row.duration_at(lag) for row in active), Fraction(0))
    if common < minimum:
        return None
    retained = max(minimum, common - trim)
    if retained <= 0:
        return None
    remaining_trim = common - retained
    numerator = Fraction(0)
    kept_seconds = Fraction(0)
    for row in sorted(active, key=lambda row: row.squared_error, reverse=True):
        duration = row.duration_at(lag)
        if remaining_trim > 0:
            removed = min(duration, remaining_trim)
            duration -= removed
            remaining_trim -= removed
        if duration > 0:
            numerator += duration * row.squared_error
            kept_seconds += duration
    if kept_seconds != retained:
        raise ValueError('trim accounting mismatch')
    return numerator / retained


def _affine_root(slope_sum: Fraction, intercept_sum: Fraction, target: Fraction):
    if slope_sum == 0:
        return None
    return (target - intercept_sum) / slope_sum


def optimal_trimmed_lags(
    evidence: JointEvidence,
    trim_seconds,
    minimum_retained,
) -> TrimResult:
    trim = parse_rational(trim_seconds)
    minimum = parse_rational(minimum_retained)
    if trim < 0:
        raise ValueError('trim budget must be nonnegative')
    if minimum <= 0:
        raise ValueError('minimum retained time must be positive')
    point_winners: list[tuple[Fraction, Fraction]] = []
    interval_winners: list[tuple[Fraction, Fraction]] = []
    best = None

    def consider(score: Fraction, lower: Fraction, upper: Fraction) -> None:
        nonlocal best
        if best is None or score < best:
            best = score
            point_winners.clear()
            interval_winners.clear()
        if score == best:
            if lower == upper:
                point_winners.append((lower, upper))
            else:
                interval_winners.append((lower, upper))

    for cell in evidence.cells:
        lower, upper = cell.lower, cell.upper
        if lower == upper:
            score = _evaluate(cell, lower, trim, minimum)
            if score is not None:
                consider(score, lower, upper)
            continue
        # High error first: the greedy trim walks this order.
        rows = tuple(sorted(cell.rows, key=lambda row: row.squared_error, reverse=True))
        common_slope = sum((row.slope for row in rows), Fraction(0))
        common_intercept = sum((row.intercept for row in rows), Fraction(0))

        def common_at(lag: Fraction) -> Fraction:
            return common_slope * lag + common_intercept

        cuts = {lower, upper}
        feasibility_root = _affine_root(common_slope, common_intercept, minimum)
        if feasibility_root is not None and lower < feasibility_root < upper:
            cuts.add(feasibility_root)
        # H_k is the set of the k highest-error rows.  Greedy trimming changes
        # regime when a high-error prefix duration crosses the actual trim
        # amount (0, T, or D-m), and when an individual row duration is born
        # or dies.  Every such crossing is a rational affine root.
        prefix_slope = Fraction(0)
        prefix_intercept = Fraction(0)
        for row in rows:
            prefix_slope += row.slope
            prefix_intercept += row.intercept
            for slope_sum, intercept_sum in (
                (prefix_slope, prefix_intercept),
                (row.slope, row.intercept),
            ):
                for target in (Fraction(0), trim, common_intercept - minimum):
                    root = _affine_root(slope_sum, intercept_sum, target)
                    if root is not None and lower < root < upper:
                        cuts.add(root)
        ordered = sorted(cuts)
        for left, right in zip(ordered, ordered[1:]):
            midpoint = (left + right) / 2
            if common_at(midpoint) < minimum:
                continue
            left_score = _evaluate(cell, left, trim, minimum)
            right_score = _evaluate(cell, right, trim, minimum)
            if left_score is None or right_score is None:
                raise ValueError('feasible segment has an infeasible endpoint')
            if left_score == right_score:
                consider(left_score, left, right)
            elif left_score < right_score:
                consider(left_score, left, left)
            else:
                consider(right_score, right, right)
        for cut in ordered:
            if lower <= cut <= upper:
                score = _evaluate(cell, cut, trim, minimum)
                if score is not None:
                    consider(score, cut, cut)
    if best is None:
        return TrimResult(None, ())
    return TrimResult(best, coalesce_minimizers([*interval_winners, *point_winners]))
