from collections.abc import Iterator
from dataclasses import dataclass
from fractions import Fraction

from trial.rationals import format_rational, parse_rational


@dataclass(frozen=True, slots=True)
class EffectiveSpan:
    start: Fraction
    end: Fraction
    value: Fraction

    def __post_init__(self):
        start, end, value = map(parse_rational, (self.start, self.end, self.value))
        if start >= end:
            raise ValueError('evidence span must have positive duration')
        object.__setattr__(self, 'start', start)
        object.__setattr__(self, 'end', end)
        object.__setattr__(self, 'value', value)


@dataclass(frozen=True, slots=True)
class CurveEvidence:
    spans: tuple[EffectiveSpan, ...]

    def __post_init__(self):
        spans = tuple(self.spans)
        if any(not isinstance(span, EffectiveSpan) for span in spans):
            raise ValueError('expected effective spans')
        for previous, current in zip(spans, spans[1:]):
            if current.start < previous.end:
                raise ValueError('evidence spans must be ordered and disjoint')
        object.__setattr__(self, 'spans', spans)


def encode_evidence(evidence: CurveEvidence) -> dict:
    return {'spans': [
        [format_rational(span.start), format_rational(span.end), format_rational(span.value)]
        for span in iter_effective_spans(evidence)
    ]}


def decode_evidence(payload: object) -> CurveEvidence:
    if not isinstance(payload, dict) or set(payload) != {'spans'}:
        raise ValueError('invalid curve evidence fields')
    rows = payload['spans']
    if not isinstance(rows, list):
        raise ValueError('evidence spans must be a list')
    spans = []
    for row in rows:
        if not isinstance(row, list) or len(row) != 3 or any(type(value) is not str for value in row):
            raise ValueError('each span must contain start, end and value as rational text')
        spans.append(EffectiveSpan(*row))
    return CurveEvidence(tuple(spans))


def iter_effective_spans(evidence: CurveEvidence) -> Iterator[EffectiveSpan]:
    return iter(evidence.spans)
