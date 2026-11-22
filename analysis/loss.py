from collections.abc import Iterator
from dataclasses import dataclass
from fractions import Fraction

from analysis.overlap import common_spans_at, lag_knots
from handoff.evidence import CurveEvidence


@dataclass(frozen=True, slots=True)
class LagStatistics:
    common_seconds: Fraction
    squared_error_integral: Fraction

    @property
    def mse(self) -> Fraction:
        if self.common_seconds <= 0:
            raise ValueError('mean squared error requires positive common time')
        return self.squared_error_integral / self.common_seconds


@dataclass(frozen=True, slots=True)
class StatisticsCell:
    lower: Fraction
    upper: Fraction
    left: LagStatistics
    right: LagStatistics

    def at(self, lag: Fraction) -> LagStatistics:
        if not self.lower <= lag <= self.upper:
            raise ValueError('lag is outside the statistics cell')
        if lag == self.lower:
            return self.left
        if lag == self.upper:
            return self.right
        weight = (lag - self.lower) / (self.upper - self.lower)
        return LagStatistics(
            self.left.common_seconds + weight * (self.right.common_seconds - self.left.common_seconds),
            self.left.squared_error_integral
            + weight * (self.right.squared_error_integral - self.left.squared_error_integral),
        )


def measure_at(a: CurveEvidence, b: CurveEvidence, lag: Fraction) -> LagStatistics:
    common = Fraction(0)
    error = Fraction(0)
    for span in common_spans_at(a, b, lag):
        seconds = span.seconds
        common += seconds
        error += seconds * (span.a_value - span.b_value) ** 2
    return LagStatistics(common, error)


def build_statistics_cells(
    a: CurveEvidence, b: CurveEvidence, lower: Fraction, upper: Fraction
) -> Iterator[StatisticsCell]:
    if lower > upper:
        raise ValueError('lag window must be ordered')
    knots = iter(lag_knots(a, b, lower, upper))
    left_lag = next(knots)
    left = measure_at(a, b, left_lag)
    if lower == upper:
        yield StatisticsCell(left_lag, left_lag, left, left)
        return
    for right_lag in knots:
        right = measure_at(a, b, right_lag)
        yield StatisticsCell(left_lag, right_lag, left, right)
        left_lag, left = right_lag, right
