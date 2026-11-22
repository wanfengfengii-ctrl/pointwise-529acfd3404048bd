from dataclasses import dataclass
import sqlite3

from analysis.lag_set import optimal_lags
from analysis.trimmed import optimal_trimmed_lags
from handoff.acceptance import read_accepted, read_accepted_trimmed
from handoff.issuer import FrozenCurve, validate_pair_sources
from reports.issue import ReportParent, ReportSnapshot, issue_report
from reports.trimmed import issue_trimmed_report
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


def analyze_trimmed(
    db: sqlite3.Connection,
    piece_id: int,
    max_trim_seconds: RationalInput,
    min_retained_seconds: RationalInput,
) -> int:
    require_serial(piece_id, 'piece number')
    trim = parse_rational(max_trim_seconds)
    minimum = parse_rational(min_retained_seconds)
    if trim < 0:
        raise ValueError('trim budget must be nonnegative')
    if minimum <= 0:
        raise ValueError('minimum retained time must be positive')
    piece = read_accepted_trimmed(db, piece_id)
    result = optimal_trimmed_lags(piece.evidence, trim, minimum)
    return issue_trimmed_report(db, piece, trim, minimum, result)
