from dataclasses import dataclass
from fractions import Fraction

from trial.rationals import RationalInput, parse_rational
from trial.roles import require_label


@dataclass(frozen=True, slots=True)
class UnitBinding:
    input_unit: str
    report_unit: str
    factor: Fraction

    def __post_init__(self):
        require_label(self.input_unit, 'input unit')
        require_label(self.report_unit, 'report unit')
        factor = parse_rational(self.factor)
        if factor <= 0:
            raise ValueError('conversion factor must be positive')
        object.__setattr__(self, 'factor', factor)


def make_unit_binding(input_unit: str, report_unit: str, factor: RationalInput) -> UnitBinding:
    return UnitBinding(input_unit, report_unit, parse_rational(factor))


def convert_reading(binding: UnitBinding, value: RationalInput, unit: str) -> Fraction:
    if unit != binding.input_unit:
        raise ValueError(f'expected input unit {binding.input_unit!r}')
    return parse_rational(value) * binding.factor
