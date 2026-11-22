from dataclasses import dataclass
import sqlite3

from analysis.lag_set import optimal_lags
from handoff.acceptance import read_accepted
from handoff.issuer import FrozenCurve, validate_pair_sources
from reports.issue import ReportParent, ReportSnapshot, issue_report
from trial.rationals import RationalInput, parse_rational, require_serial


@dataclass(frozen=True, slots=True)
class LagRequest:
    a_piece_id: int
    b_piece_id: int
    lower: RationalInput
    upper: RationalInput
    min_seconds: RationalInput

    def __post_init__(self):
        require_serial(self.a_piece_id, 'A piece number')
        require_serial(self.b_piece_id, 'B piece number')
        lower, upper, minimum = map(parse_rational, (self.lower, self.upper, self.min_seconds))
        if lower > upper:
            raise ValueError('lag window must be ordered')
        if minimum <= 0:
            raise ValueError('minimum common time must be positive')
        object.__setattr__(self, 'lower', lower)
        object.__setattr__(self, 'upper', upper)
        object.__setattr__(self, 'min_seconds', minimum)


def select_pair(db: sqlite3.Connection, request: LagRequest) -> tuple[FrozenCurve, FrozenCurve]:
    a = read_accepted(db, request.a_piece_id)
    b = read_accepted(db, request.b_piece_id)
    validate_pair_sources(a.source, b.source)
    return a, b


def analyze(db: sqlite3.Connection, request: LagRequest) -> int:
    a, b = select_pair(db, request)
    result = optimal_lags(a.evidence, b.evidence, request.lower, request.upper, request.min_seconds)
    report = ReportSnapshot(
        (ReportParent(a.piece_id, a.source), ReportParent(b.piece_id, b.source)),
        request.lower, request.upper, request.min_seconds, result.minimum_mse, result.intervals,
    )
    return issue_report(db, report)
