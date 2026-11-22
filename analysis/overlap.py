from collections.abc import Iterator
from dataclasses import dataclass
from fractions import Fraction

from handoff.evidence import CurveEvidence, iter_effective_spans


@dataclass(frozen=True, slots=True)
class CommonSpan:
    start: Fraction
    end: Fraction
    a_value: Fraction
    b_value: Fraction

    @property
    def seconds(self) -> Fraction:
        return self.end - self.start


def common_spans_at(a: CurveEvidence, b: CurveEvidence, lag: Fraction) -> Iterator[CommonSpan]:
    a_iter = iter_effective_spans(a)
    b_iter = iter_effective_spans(b)
    left = next(a_iter, None)
    right = next(b_iter, None)
    while left is not None and right is not None:
        left_end = left.end
        right_end = right.end + lag
        start = max(left.start, right.start + lag)
        end = min(left_end, right_end)
        if start < end:
            yield CommonSpan(start, end, left.value, right.value)
        if left_end <= right_end:
            left = next(a_iter, None)
        if right_end <= left_end:
            right = next(b_iter, None)


def _boundaries(evidence: CurveEvidence) -> set[Fraction]:
    return {point for span in iter_effective_spans(evidence) for point in (span.start, span.end)}


def lag_knots(a: CurveEvidence, b: CurveEvidence, lower: Fraction, upper: Fraction) -> tuple[Fraction, ...]:
    knots = {lower, upper}
    a_bounds = _boundaries(a)
    b_bounds = _boundaries(b)
    for a_boundary in a_bounds:
        for b_boundary in b_bounds:
            collision = a_boundary - b_boundary
            if lower < collision < upper:
                knots.add(collision)
    return tuple(sorted(knots))
