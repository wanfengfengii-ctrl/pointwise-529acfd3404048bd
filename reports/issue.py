from dataclasses import dataclass
from fractions import Fraction
import json
import sqlite3

from handoff.acceptance import read_accepted
from handoff.issuer import FrozenSource, decode_source, source_payload, validate_pair_sources
from reports.archive import append_report
from trial.rationals import format_rational, parse_rational, require_serial


@dataclass(frozen=True, slots=True)
class ReportParent:
    piece_id: int
    source: FrozenSource

    def __post_init__(self):
        require_serial(self.piece_id, 'parent piece number')
        if not isinstance(self.source, FrozenSource):
            raise ValueError('report parent requires a frozen source')


@dataclass(frozen=True, slots=True)
class ReportSnapshot:
    parents: tuple[ReportParent, ReportParent]
    lower: Fraction
    upper: Fraction
    min_seconds: Fraction
    minimum_mse: Fraction | None
    intervals: tuple[tuple[Fraction, Fraction], ...]

    def __post_init__(self):
        parents = tuple(self.parents)
        if len(parents) != 2 or any(not isinstance(parent, ReportParent) for parent in parents):
            raise ValueError('report requires two parent pieces')
        a, b = parents
        if a.piece_id == b.piece_id:
            raise ValueError('report parent piece numbers must differ')
        validate_pair_sources(a.source, b.source)
        lower, upper, min_seconds = map(parse_rational, (self.lower, self.upper, self.min_seconds))
        if lower > upper or min_seconds <= 0:
            raise ValueError('invalid archived lag request')
        score = None if self.minimum_mse is None else parse_rational(self.minimum_mse)
        if score is not None and score < 0:
            raise ValueError('minimum mean squared error must be nonnegative')
        intervals = []
        for start, end in self.intervals:
            start, end = map(parse_rational, (start, end))
            if not lower <= start <= end <= upper:
                raise ValueError('report interval is outside the lag window')
            if intervals and start <= intervals[-1][1]:
                raise ValueError('report intervals must be ordered and separated')
            intervals.append((start, end))
        if (score is None) != (not intervals):
            raise ValueError('empty report and minimum score are inconsistent')
        object.__setattr__(self, 'parents', parents)
        object.__setattr__(self, 'lower', lower)
        object.__setattr__(self, 'upper', upper)
        object.__setattr__(self, 'min_seconds', min_seconds)
        object.__setattr__(self, 'minimum_mse', score)
        object.__setattr__(self, 'intervals', tuple(intervals))

    @property
    def trial_id(self) -> str:
        return self.parents[0].source.trial_id

    @property
    def report_unit(self) -> str:
        return self.parents[0].source.report_unit


def encode_report_snapshot(report: ReportSnapshot) -> str:
    payload = {
        'parents': [
            {'piece_id': parent.piece_id, 'source': source_payload(parent.source)}
            for parent in report.parents
        ],
        'request': {
            'lag_window_seconds': [format_rational(report.lower), format_rational(report.upper)],
            'min_common_seconds': format_rational(report.min_seconds),
        },
        'result': {
            'status': 'empty' if report.minimum_mse is None else 'ok',
            'minimum_mse': None if report.minimum_mse is None else format_rational(report.minimum_mse),
            'intervals': [[format_rational(start), format_rational(end)] for start, end in report.intervals],
        },
    }
    return json.dumps(payload, sort_keys=True, separators=(',', ':'))


def decode_report_snapshot(encoded: str) -> ReportSnapshot:
    payload = json.loads(encoded)
    parents = tuple(ReportParent(row['piece_id'], decode_source(row['source'])) for row in payload['parents'])
    request = payload['request']
    lower, upper = request['lag_window_seconds']
    result = payload['result']
    score = result['minimum_mse']
    expected_status = 'empty' if score is None else 'ok'
    if result['status'] != expected_status:
        raise ValueError('unexpected archived result status')
    return ReportSnapshot(parents, lower, upper, request['min_common_seconds'], score, result['intervals'])


def issue_report(db: sqlite3.Connection, report: ReportSnapshot) -> int:
    for parent in report.parents:
        if read_accepted(db, parent.piece_id).source != parent.source:
            raise ValueError('report source differs from the accepted parent')
    a, b = report.parents
    return append_report(db, a.piece_id, b.piece_id, encode_report_snapshot(report))
