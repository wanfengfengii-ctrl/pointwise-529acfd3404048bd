from contextlib import closing
import json
from pathlib import Path
import sqlite3
import sys
from tempfile import TemporaryDirectory

from analysis.selection import LagRequest, analyze
from handoff.acceptance import accept
from handoff.freeze import freeze
from handoff.inbox import initialize_inbox
from handoff.issuer import encode_frozen_curve, initialize_issue_register
from ledger.observations import ObservationInput
from ledger.revisions import submit
from ledger.storage import initialize_revision_ledger
from reports.archive import initialize_report_archive
from reports.read import export_report, read
from trial.rationals import format_rational
from trial.registry import initialize_trial_registry, register


EXAMPLES = Path(__file__).resolve().parent / 'examples'


def load_sample(name):
    return json.loads((EXAMPLES / name).read_text(encoding='utf-8'))


def connect(path):
    db = sqlite3.connect(path)
    db.execute('PRAGMA foreign_keys = ON')
    return db


def deliver(source, review, sample):
    initialize_trial_registry(source)
    initialize_revision_ledger(source)
    initialize_issue_register(source)
    a, b = sample['a'], sample['b']
    register(source, sample['trial_id'], a['table_id'], b['table_id'], sample['report_unit'],
             a['unit'], a['factor'], b['unit'], b['factor'])
    parents = []
    for role, table in (('A', a), ('B', b)):
        rows = [ObservationInput(*row, table['unit']) for row in table['rows']]
        revision = submit(source, sample['trial_id'], table['table_id'], None, rows)
        piece = accept(review, encode_frozen_curve(freeze(source, revision)))
        parents.append({'piece_id': piece, 'revision_id': revision, 'role': role, 'table_id': table['table_id']})
    return parents


def report_result(report):
    score = report.minimum_mse
    return {
        'status': 'empty' if score is None else 'ok',
        'minimum_mse': None if score is None else format_rational(score),
        'intervals': [[format_rational(start), format_rational(end)] for start, end in report.intervals],
    }


def main():
    sample = load_sample('shift-input.json')
    expected = load_sample('shift-expected.json')
    with TemporaryDirectory() as directory:
        root = Path(directory)
        review_path = root / 'review.sqlite'
        with closing(connect(review_path)) as review:
            initialize_inbox(review)
            initialize_report_archive(review)
            with closing(connect(root / 'source.sqlite')) as source:
                parents = deliver(source, review, sample)
            request = LagRequest(parents[0]['piece_id'], parents[1]['piece_id'],
                                 *sample['lag_window_seconds'], sample['min_common_seconds'])
            report_id = analyze(review, request)
            actual = report_result(read(review, report_id))
        with closing(connect(review_path)) as reopened:
            exported = json.loads(export_report(reopened, report_id))

    if actual != expected['result']:
        print('LAG_RANGE_MISMATCH ' + json.dumps({'expected': expected['result'], 'actual': actual}), file=sys.stderr)
        return 1
    downstream_expected = {
        'report_id': report_id,
        'trial_id': sample['trial_id'],
        'report_unit': sample['report_unit'],
        'parents': parents,
        'result': expected['result'],
    }
    downstream_actual = {
        'report_id': exported['report_id'],
        'trial_id': exported['trial_id'],
        'report_unit': exported['report_unit'],
        'parents': [
            {'piece_id': row['piece_id'], 'revision_id': row['source']['revision_id'],
             'role': row['source']['role'], 'table_id': row['source']['table_id']}
            for row in exported['parents']
        ],
        'result': exported['result'],
    }
    if downstream_actual != downstream_expected:
        print('LAG_REPORT_READBACK_MISMATCH ' + json.dumps(downstream_actual), file=sys.stderr)
        return 1
    print(json.dumps(exported, ensure_ascii=False, indent=2))
    print('POINTWISE_SCENARIO ' + json.dumps({
        'case_id': expected['case_id'], 'input': sample,
        'expected': expected['result'], 'actual': actual,
        'downstream_expected': downstream_expected, 'downstream_actual': downstream_actual,
        'code_paths': ['ledger/revisions.py', 'handoff/freeze.py', 'handoff/acceptance.py',
                       'analysis/lag_set.py', 'reports/issue.py', 'reports/read.py'],
        'oracle': expected['oracle'],
    }, ensure_ascii=False, separators=(',', ':')))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
