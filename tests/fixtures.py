from contextlib import closing
import json
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
import unittest

from handoff.acceptance import accept
from handoff.freeze import freeze
from handoff.inbox import initialize_inbox
from handoff.issuer import encode_frozen_curve, initialize_issue_register
from ledger.observations import ObservationInput
from ledger.revisions import submit
from ledger.storage import initialize_revision_ledger
from reports.archive import initialize_report_archive
from trial.registry import initialize_trial_registry, register


def observations(*rows, unit='u'):
    return tuple(ObservationInput(*row, unit) for row in rows)


def count(db, table):
    if table not in {'trial_registry', 'ledger_revisions', 'source_issues', 'review_inbox', 'review_reports'}:
        raise ValueError('unknown fixture table')
    return db.execute(f'SELECT COUNT(*) FROM {table}').fetchone()[0]


def legal_piece(piece_id, trial_id, role, revision_id, spans, unit='u'):
    return json.dumps({
        'version': 1,
        'piece_id': piece_id,
        'source': {
            'trial_id': trial_id, 'role': role, 'table_id': f'meter-{role.lower()}',
            'revision_id': revision_id, 'report_unit': unit, 'a_table': 'meter-a', 'b_table': 'meter-b',
        },
        'evidence': {'spans': [list(span) for span in spans]},
    })


class LabCase(unittest.TestCase):
    def setUp(self):
        root = Path(self.enterContext(TemporaryDirectory()))
        self.source_path = root / 'source.sqlite'
        self.review_path = root / 'review.sqlite'
        self.source = self.open_source()
        self.review = self.open_review()

    def connect(self, path):
        db = self.enterContext(closing(sqlite3.connect(path, cached_statements=0)))
        db.execute('PRAGMA foreign_keys = ON')
        return db

    def open_source(self):
        db = self.connect(self.source_path)
        initialize_trial_registry(db)
        initialize_revision_ledger(db)
        initialize_issue_register(db)
        return db

    def open_review(self):
        db = self.connect(self.review_path)
        initialize_inbox(db)
        initialize_report_archive(db)
        return db

    def trial(self, trial_id='T1', factor=1):
        return register(self.source, trial_id, 'meter-a', 'meter-b', 'u', 'u', factor, 'u', factor)

    def submit(self, table, records, parent=None, trial_id='T1'):
        return submit(self.source, trial_id, table, parent, records)

    def deliver(self, revision):
        return accept(self.review, encode_frozen_curve(freeze(self.source, revision)))

    def plateau(self):
        self.trial()
        a = self.submit('meter-a', observations((0, 2, 1)))
        b = self.submit('meter-b', observations((0, 1, 1), (1, 2, 3)))
        return (a, b), (self.deliver(a), self.deliver(b))
