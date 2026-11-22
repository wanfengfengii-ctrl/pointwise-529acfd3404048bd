from collections.abc import Iterable
from fractions import Fraction

from ledger.observations import BoundObservation


def validate_disjoint_coverage(
    observations: Iterable[BoundObservation],
) -> tuple[BoundObservation, ...]:
    chronological = tuple(sorted(observations, key=lambda span: (span.start, span.end)))
    for previous, current in zip(chronological, chronological[1:]):
        if current.start < previous.end:
            raise ValueError(f'overlapping records {previous.ordinal} and {current.ordinal}')
    return chronological


def sum_covered_seconds(observations: Iterable[BoundObservation]) -> Fraction:
    return sum((span.end - span.start for span in observations), Fraction(0))
