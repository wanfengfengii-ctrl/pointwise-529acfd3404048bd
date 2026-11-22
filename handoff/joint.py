"""Joint residual evidence for version 2 trimmed pieces.

A trimmed piece keeps no raw observations and no single-table curves: only the
joint squared-error measurement over the fixed closed lag window.

Evidence representation
-----------------------
The closed lag window ``[lower, upper]`` is tiled by *cells* whose boundaries
are the lower/upper window ends and every interior lag at which an A boundary
collides with a B boundary (``analysis.overlap.lag_knots``).  Inside one cell
the set of simultaneously effective span pairs is fixed.  Each pair contributes
one row whose common-time duration is an affine function of the real lag ``t``
within that closed cell::

    duration(t) = slope * t + intercept          slope in {-1, 0, 1}
    squared_error                                exact nonnegative rational

The squared error is ``(a_value - b_value) ** 2`` in report units; zero values
participate and missing time simply produces no rows.  Rows with zero duration
on the whole closed cell are omitted.  Cells without any positive-duration row
are kept with an empty row list, so a window with no common effective time is
still fully covered.

Value domains and acceptance invariants
---------------------------------------
* every row carries rational text for slope, intercept and squared error;
* slope is one of ``-1``, ``0`` or ``1``;
* the squared error is nonnegative;
* ``slope * t + intercept >= 0`` at both ends of its cell;
* cells are ordered, closed, touching, and tile the whole window;
* the per-error totals at a shared knot match between the two adjacent cells,
  which guarantees the representation has no gaps, jumps or duplicated time;
* the evidence window equals the envelope window and uses the piece's sources.

From these rows, for any real lag in the window one can reconstruct the total
common effective duration ``D(t)`` and every squared-error component, which is
all that any legal trimming application (trim budget and retained threshold)
needs.
"""
from dataclasses import dataclass
import json
from fractions import Fraction

from analysis.overlap import common_pairs_at, lag_knots
from handoff.evidence import CurveEvidence, iter_effective_spans
from handoff.issuer import FrozenSource, decode_source, source_payload, validate_pair_sources
from trial.rationals import format_rational, parse_rational, require_serial


@dataclass(frozen=True, slots=True)
class JointRow:
    slope: Fraction
    intercept: Fraction
    squared_error: Fraction

    def duration_at(self, lag: Fraction) -> Fraction:
        return self.slope * lag + self.intercept


@dataclass(frozen=True, slots=True)
class JointCell:
    lower: Fraction
    upper: Fraction
    rows: tuple[JointRow, ...]

    def totals_at(self, lag: Fraction) -> dict[Fraction, Fraction]:
        totals: dict[Fraction, Fraction] = {}
        for row in self.rows:
            duration = row.duration_at(lag)
            if duration > 0:
                totals[row.squared_error] = totals.get(row.squared_error, Fraction(0)) + duration
        return totals

    def common_seconds_at(self, lag: Fraction) -> Fraction:
        return sum((row.duration_at(lag) for row in self.rows), Fraction(0))


@dataclass(frozen=True, slots=True)
class JointEvidence:
    lower: Fraction
    upper: Fraction
    cells: tuple[JointCell, ...]

    def __post_init__(self):
        lower, upper = parse_rational(self.lower), parse_rational(self.upper)
        if lower > upper:
            raise ValueError('joint evidence window must be ordered')
        cells = tuple(self.cells)
        if not cells:
            raise ValueError('joint evidence must cover its window')
        if cells[0].lower != lower or cells[-1].upper != upper:
            raise ValueError('joint evidence cells do not cover the window')
        for previous, current in zip(cells, cells[1:]):
            if previous.upper != current.lower or current.lower > current.upper:
                raise ValueError('joint evidence cells must be ordered and touching')
        object.__setattr__(self, 'lower', lower)
        object.__setattr__(self, 'upper', upper)
        object.__setattr__(self, 'cells', cells)


@dataclass(frozen=True, slots=True)
class JointPiece:
    piece_id: int
    sources: tuple[FrozenSource, FrozenSource]
    lower: Fraction
    upper: Fraction
    evidence: JointEvidence

    def __post_init__(self):
        require_serial(self.piece_id, 'piece number')
        sources = tuple(self.sources)
        if len(sources) != 2 or any(not isinstance(source, FrozenSource) for source in sources):
            raise ValueError('joint piece requires two frozen sources')
        validate_pair_sources(sources[0], sources[1])
        lower, upper = parse_rational(self.lower), parse_rational(self.upper)
        if lower > upper:
            raise ValueError('lag window must be ordered')
        if not isinstance(self.evidence, JointEvidence) or self.evidence.lower != lower \
                or self.evidence.upper != upper:
            raise ValueError('joint piece evidence must match its window')
        object.__setattr__(self, 'sources', sources)
        object.__setattr__(self, 'lower', lower)
        object.__setattr__(self, 'upper', upper)


def _row_key(row: JointRow) -> tuple:
    return (row.squared_error, row.slope, row.intercept)


def _pair_duration(a_span, b_span, lag: Fraction) -> Fraction:
    start = max(a_span.start, b_span.start + lag)
    end = min(a_span.end, b_span.end + lag)
    return max(Fraction(0), end - start)


def build_joint_evidence(
    a: CurveEvidence, b: CurveEvidence, lower: Fraction, upper: Fraction
) -> JointEvidence:
    knots = lag_knots(a, b, lower, upper)
    a_spans = tuple(iter_effective_spans(a))
    b_spans = tuple(iter_effective_spans(b))
    cells = []
    if lower == upper:
        cells.append(JointCell(lower, upper, tuple(sorted(
            (JointRow(Fraction(0), _pair_duration(a_span, b_span, lower),
                      (a_span.value - b_span.value) ** 2)
             for a_span in a_spans for b_span in b_spans
             if _pair_duration(a_span, b_span, lower) > 0),
            key=_row_key,
        ))))
    for left_lag, right_lag in zip(knots, knots[1:]):
        width = right_lag - left_lag
        midpoint = (left_lag + right_lag) / 2
        # In a cell's interior the pair structure is fixed: enumerate the
        # overlapping (A span, B span) pairs at the midpoint.  A pair may be
        # born or die exactly on a knot, giving zero duration there.
        interior = {
            (left_span, right_span)
            for left_span in a_spans
            for right_span in b_spans
            if _pair_duration(left_span, right_span, midpoint) > 0
        }
        rows = []
        for a_span, b_span in sorted(interior, key=lambda pair: (pair[0].start, pair[1].start)):
            left_seconds = _pair_duration(a_span, b_span, left_lag)
            right_seconds = _pair_duration(a_span, b_span, right_lag)
            slope = (right_seconds - left_seconds) / width
            if slope not in (Fraction(-1), Fraction(0), Fraction(1)):
                raise ValueError('common span duration must move with slope -1, 0 or 1')
            intercept = left_seconds - slope * left_lag
            if slope * midpoint + intercept != _pair_duration(a_span, b_span, midpoint):
                raise ValueError('common span duration is not affine across the cell')
            if left_seconds > 0 or right_seconds > 0:
                squared_error = (a_span.value - b_span.value) ** 2
                rows.append(JointRow(slope, intercept, squared_error))
        cells.append(JointCell(left_lag, right_lag, tuple(sorted(rows, key=_row_key))))
    evidence = JointEvidence(lower, upper, tuple(cells))
    _check_knot_totals(evidence, a, b)
    return evidence


def _cell_covering(evidence: JointEvidence, lag: Fraction) -> JointCell:
    for cell in evidence.cells:
        if cell.lower <= lag <= cell.upper:
            # A shared interior knot belongs to two closed cells; account for
            # it on the cell that ends there, except a singleton point cell.
            if cell.upper == lag or cell.lower == cell.upper:
                return cell
    return next(cell for cell in evidence.cells if cell.lower <= lag <= cell.upper)


def _check_knot_totals(evidence: JointEvidence, a: CurveEvidence, b: CurveEvidence) -> None:
    knots = {evidence.lower, evidence.upper}
    for cell in evidence.cells:
        knots.add(cell.lower)
        knots.add(cell.upper)
    for lag in sorted(knots):
        measured: dict[Fraction, Fraction] = {}
        for pair in common_pairs_at(a, b, lag):
            measured[pair.squared_error] = measured.get(pair.squared_error, Fraction(0)) + pair.seconds
        rebuilt = _cell_covering(evidence, lag).totals_at(lag)
        if rebuilt != measured:
            raise ValueError('joint evidence fails the knot total invariant')


def encode_joint_cell(cell: JointCell) -> dict:
    return {
        'lag_window_seconds': [format_rational(cell.lower), format_rational(cell.upper)],
        'rows': [
            [format_rational(row.slope), format_rational(row.intercept),
             format_rational(row.squared_error)]
            for row in cell.rows
        ],
    }


def encode_joint_evidence(evidence: JointEvidence) -> dict:
    return {
        'lag_window_seconds': [format_rational(evidence.lower), format_rational(evidence.upper)],
        'cells': [encode_joint_cell(cell) for cell in evidence.cells],
    }


def _parse_window(payload: object) -> tuple[Fraction, Fraction]:
    if not isinstance(payload, list) or len(payload) != 2 \
            or any(type(value) is not str for value in payload):
        raise ValueError('lag window must contain two rational texts')
    lower, upper = (parse_rational(value) for value in payload)
    if lower > upper:
        raise ValueError('lag window must be ordered')
    return lower, upper


def decode_joint_cell(payload: object) -> JointCell:
    if not isinstance(payload, dict) or set(payload) != {'lag_window_seconds', 'rows'}:
        raise ValueError('invalid joint evidence cell fields')
    lower, upper = _parse_window(payload['lag_window_seconds'])
    raw_rows = payload['rows']
    if not isinstance(raw_rows, list):
        raise ValueError('joint evidence rows must be a list')
    rows = []
    for raw in raw_rows:
        if not isinstance(raw, list) or len(raw) != 3 \
                or any(type(value) is not str for value in raw):
            raise ValueError('each joint row must contain slope, intercept and error text')
        slope, intercept, squared_error = (parse_rational(value) for value in raw)
        if slope not in (Fraction(-1), Fraction(0), Fraction(1)):
            raise ValueError('joint row slope must be -1, 0 or 1')
        if squared_error < 0:
            raise ValueError('joint squared error must be nonnegative')
        if slope * lower + intercept < 0 or slope * upper + intercept < 0:
            raise ValueError('joint row duration must stay nonnegative on its cell')
        rows.append(JointRow(slope, intercept, squared_error))
    return JointCell(lower, upper, tuple(rows))


def decode_joint_evidence(payload: object, lower: Fraction, upper: Fraction) -> JointEvidence:
    if not isinstance(payload, dict) or set(payload) != {'lag_window_seconds', 'cells'}:
        raise ValueError('invalid joint evidence fields')
    window_lower, window_upper = _parse_window(payload['lag_window_seconds'])
    if (window_lower, window_upper) != (lower, upper):
        raise ValueError('joint evidence window does not match the envelope')
    raw_cells = payload['cells']
    if not isinstance(raw_cells, list) or not raw_cells:
        raise ValueError('joint evidence must contain at least one cell')
    cells = [decode_joint_cell(raw) for raw in raw_cells]
    if cells[0].lower != lower or cells[-1].upper != upper:
        raise ValueError('joint evidence cells do not tile the window')
    for previous, current in zip(cells, cells[1:]):
        if previous.upper != current.lower or current.lower > current.upper:
            raise ValueError('joint evidence cells must be ordered and touching')
    for left, right in zip(cells, cells[1:]):
        if left.totals_at(left.upper) != right.totals_at(right.lower):
            raise ValueError('joint evidence knot totals are inconsistent')
    return JointEvidence(lower, upper, tuple(cells))


def _json(payload: dict) -> str:
    return json.dumps(payload, sort_keys=True, separators=(',', ':'))


def _unique_fields(pairs: list) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f'duplicate joint field: {key}')
        result[key] = value
    return result


def encode_joint_piece(piece: JointPiece) -> str:
    return _json({
        'version': 2,
        'piece_id': piece.piece_id,
        'sources': [source_payload(source) for source in piece.sources],
        'lag_window_seconds': [format_rational(piece.lower), format_rational(piece.upper)],
        'evidence': encode_joint_evidence(piece.evidence),
    })


def decode_joint_piece(encoded: str) -> JointPiece:
    if not isinstance(encoded, str):
        raise ValueError('joint piece must be JSON text')
    payload = json.loads(encoded, object_pairs_hook=_unique_fields)
    if not isinstance(payload, dict) \
            or set(payload) != {'version', 'piece_id', 'sources', 'lag_window_seconds', 'evidence'}:
        raise ValueError('invalid joint piece envelope')
    if type(payload['version']) is not int or payload['version'] != 2:
        raise ValueError('unsupported joint piece version')
    piece_id = payload['piece_id']
    require_serial(piece_id, 'piece number')
    raw_sources = payload['sources']
    if not isinstance(raw_sources, list) or len(raw_sources) != 2:
        raise ValueError('joint piece requires two sources')
    sources = (decode_source(raw_sources[0]), decode_source(raw_sources[1]))
    validate_pair_sources(sources[0], sources[1])
    lower, upper = _parse_window(payload['lag_window_seconds'])
    evidence = decode_joint_evidence(payload['evidence'], lower, upper)
    return JointPiece(piece_id, sources, lower, upper, evidence)
