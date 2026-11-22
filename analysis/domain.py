from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from fractions import Fraction

from analysis.loss import LagStatistics, StatisticsCell


@dataclass(frozen=True, slots=True)
class EligibleCell:
    lower: Fraction
    upper: Fraction
    left: LagStatistics
    right: LagStatistics


def clip_support(cell: StatisticsCell, min_seconds: Fraction) -> EligibleCell | None:
    if min_seconds <= 0:
        raise ValueError('minimum common time must be positive')
    left_seconds = cell.left.common_seconds
    right_seconds = cell.right.common_seconds
    left_ok = left_seconds >= min_seconds
    right_ok = right_seconds >= min_seconds
    if left_ok and right_ok:
        return EligibleCell(cell.lower, cell.upper, cell.left, cell.right)
    if not left_ok and not right_ok:
        return None
    weight = (min_seconds - left_seconds) / (right_seconds - left_seconds)
    crossing = cell.lower + weight * (cell.upper - cell.lower)
    boundary = cell.at(crossing)
    if left_ok:
        return EligibleCell(cell.lower, crossing, cell.left, boundary)
    return EligibleCell(crossing, cell.upper, boundary, cell.right)


def eligible_cells(cells: Iterable[StatisticsCell], min_seconds: Fraction) -> Iterator[EligibleCell]:
    for cell in cells:
        eligible = clip_support(cell, min_seconds)
        if eligible is not None:
            yield eligible
