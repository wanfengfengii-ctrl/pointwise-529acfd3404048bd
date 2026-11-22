from decimal import Decimal
from fractions import Fraction
import re
from typing import TypeAlias


RationalInput: TypeAlias = int | str | Fraction
SerialLimit = 2**63 - 1
_FRACTION = re.compile(r'([+-]?[0-9]+)/([0-9]+)')
_DECIMAL = re.compile(r'[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?')


def parse_rational(value: RationalInput) -> Fraction:
    if isinstance(value, Fraction):
        return value
    if type(value) is int:
        return Fraction(value)
    if not isinstance(value, str):
        raise ValueError('expected an exact rational number')
    text = value.strip()
    parts = _FRACTION.fullmatch(text)
    if parts:
        numerator, denominator = (int(Decimal(part)) for part in parts.groups())
        if denominator == 0:
            raise ValueError('rational denominator must be nonzero')
        return Fraction(numerator, denominator)
    if _DECIMAL.fullmatch(text):
        try:
            return Fraction(Decimal(text))
        except ArithmeticError as exc:
            raise ValueError('invalid rational number') from exc
    raise ValueError('invalid rational number')


def format_rational(value: RationalInput) -> str:
    exact = parse_rational(value)
    numerator = str(Decimal(exact.numerator))
    if exact.denominator == 1:
        return numerator
    return f'{numerator}/{Decimal(exact.denominator)}'


def require_serial(value: int, label: str) -> int:
    if type(value) is not int or not 0 < value <= SerialLimit:
        raise ValueError(f'{label} must be a positive SQLite integer')
    return value
