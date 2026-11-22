from collections.abc import Iterable
from dataclasses import dataclass
from fractions import Fraction

from trial.rationals import RationalInput, parse_rational
from trial.units import UnitBinding, convert_reading


@dataclass(frozen=True, slots=True)
class ObservationInput:
    start: RationalInput
    end: RationalInput
    value: RationalInput
    unit: str


@dataclass(frozen=True, slots=True)
class BoundObservation:
    ordinal: int
    start: Fraction
    end: Fraction
    original_value: Fraction
    binding: UnitBinding
    value: Fraction

    @property
    def original_unit(self) -> str:
        return self.binding.input_unit


def bind_observations(
    records: Iterable[ObservationInput], binding: UnitBinding
) -> tuple[BoundObservation, ...]:
    bound = []
    for ordinal, record in enumerate(records, start=1):
        if not isinstance(record, ObservationInput):
            raise ValueError(f'record {ordinal} must be an ObservationInput')
        start = parse_rational(record.start)
        end = parse_rational(record.end)
        if start >= end:
            raise ValueError(f'record {ordinal} must have positive duration')
        original = parse_rational(record.value)
        converted = convert_reading(binding, original, record.unit)
        bound.append(BoundObservation(ordinal, start, end, original, binding, converted))
    return tuple(bound)
