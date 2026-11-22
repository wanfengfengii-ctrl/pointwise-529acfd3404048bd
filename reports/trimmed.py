"""Version 2 trimmed report snapshots."""
import json

from analysis.trimmed import TrimResult
from handoff.acceptance import read_accepted_trimmed
from handoff.joint import JointPiece
from handoff.issuer import decode_source, source_payload
from reports.archive import append_trimmed_report
from trial.rationals import format_rational, parse_rational, require_serial


def result_payload(result: TrimResult) -> dict:
    if result.minimum_mse is None:
        if result.intervals:
            raise ValueError('empty result must not carry intervals')
        return {'status': 'empty', 'minimum_mse': None, 'intervals': []}
    return {
        'status': 'ok',
        'minimum_mse': format_rational(result.minimum_mse),
        'intervals': [[format_rational(start), format_rational(end)]
                      for start, end in result.intervals],
    }


def build_report_payload(
    piece: JointPiece, trim_seconds, minimum_retained, result: TrimResult
) -> dict:
    return {
        'version': 2,
        'piece_id': piece.piece_id,
        'sources': [source_payload(source) for source in piece.sources],
        'request': {
            'lag_window_seconds': [format_rational(piece.lower), format_rational(piece.upper)],
            'max_trim_seconds': format_rational(trim_seconds),
            'min_retained_seconds': format_rational(minimum_retained),
        },
        'result': result_payload(result),
    }


def decode_report_payload(payload: object, piece: JointPiece) -> dict:
    if not isinstance(payload, dict) or set(payload) != \
            {'version', 'piece_id', 'sources', 'request', 'result'}:
        raise ValueError('invalid trimmed report fields')
    if type(payload['version']) is not int or payload['version'] != 2:
        raise ValueError('unsupported trimmed report version')
    if payload['piece_id'] != piece.piece_id:
        raise ValueError('trimmed report piece does not match its archive')
    raw_sources = payload['sources']
    if not isinstance(raw_sources, list) or len(raw_sources) != 2 \
            or tuple(decode_source(raw) for raw in raw_sources) != piece.sources:
        raise ValueError('trimmed report sources differ from the accepted piece')
    request = payload['request']
    if not isinstance(request, dict) or set(request) != \
            {'lag_window_seconds', 'max_trim_seconds', 'min_retained_seconds'}:
        raise ValueError('invalid trimmed report request fields')
    window = request['lag_window_seconds']
    if not isinstance(window, list) or len(window) != 2 \
            or any(type(value) is not str for value in window) \
            or tuple(parse_rational(value) for value in window) != (piece.lower, piece.upper):
        raise ValueError('trimmed report window does not match its piece')
    trim = parse_rational(request['max_trim_seconds'])
    minimum = parse_rational(request['min_retained_seconds'])
    if trim < 0 or minimum <= 0:
        raise ValueError('invalid trimmed report request values')
    result = payload['result']
    if not isinstance(result, dict) or set(result) != {'status', 'minimum_mse', 'intervals'}:
        raise ValueError('invalid trimmed report result fields')
    raw_intervals = result['intervals']
    if not isinstance(raw_intervals, list) or any(
        not isinstance(interval, list) or len(interval) != 2
        or any(type(value) is not str for value in interval)
        for interval in raw_intervals
    ):
        raise ValueError('trimmed report intervals must hold rational text pairs')
    intervals = []
    for raw in raw_intervals:
        start, end = (parse_rational(value) for value in raw)
        if not piece.lower <= start <= end <= piece.upper:
            raise ValueError('trimmed report interval is outside the window')
        if intervals and start <= intervals[-1][1]:
            raise ValueError('trimmed report intervals must be ordered and separated')
        intervals.append((start, end))
    score_text = result['minimum_mse']
    if result['status'] == 'empty':
        if score_text is not None or intervals:
            raise ValueError('empty trimmed report is inconsistent')
        score = None
    elif result['status'] == 'ok':
        if not isinstance(score_text, str) or not intervals:
            raise ValueError('ok trimmed report is inconsistent')
        score = parse_rational(score_text)
        if score < 0:
            raise ValueError('minimum mean squared error must be nonnegative')
    else:
        raise ValueError('unknown trimmed report status')
    return {
        'version': 2,
        'piece_id': piece.piece_id,
        'sources': [source_payload(source) for source in piece.sources],
        'request': {
            'lag_window_seconds': [format_rational(piece.lower), format_rational(piece.upper)],
            'max_trim_seconds': format_rational(trim),
            'min_retained_seconds': format_rational(minimum),
        },
        'result': {
            'status': 'empty' if score is None else 'ok',
            'minimum_mse': None if score is None else format_rational(score),
            'intervals': [[format_rational(start), format_rational(end)] for start, end in intervals],
        },
    }


def issue_trimmed_report(
    db, piece: JointPiece, trim_seconds, minimum_retained, result: TrimResult
) -> int:
    accepted = read_accepted_trimmed(db, piece.piece_id)
    if accepted != piece:
        raise ValueError('report source differs from the accepted piece')
    payload = json.dumps(build_report_payload(piece, trim_seconds, minimum_retained, result),
                         sort_keys=True, separators=(',', ':'))
    return append_trimmed_report(db, piece.piece_id, payload)


def read_trimmed_report(db, report_id: int) -> dict:
    require_serial(report_id, 'report number')
    from reports.archive import load_trimmed_report
    payload = json.loads(load_trimmed_report(db, report_id))
    piece_id = payload['piece_id']
    piece = read_accepted_trimmed(db, piece_id)
    report = decode_report_payload(payload, piece)
    report['report_id'] = report_id
    return {'version': report['version'], 'report_id': report_id, 'piece_id': piece_id,
            'sources': report['sources'], 'request': report['request'], 'result': report['result']}


def export_trimmed_report(db, report_id: int) -> str:
    return json.dumps(read_trimmed_report(db, report_id), ensure_ascii=False, indent=2)
