from fractions import Fraction as F
import json
import sqlite3

from analysis.loss import measure_at
from analysis.selection import LagRequest, analyze
from handoff.acceptance import accept, read_accepted
from reports.read import export_report, read
from tests.fixtures import LabCase, count, legal_piece, observations


class LagReportTests(LabCase):
    def test_offline_plateau(self):
        revisions, pieces = self.plateau()
        self.source.close()
        report_id = analyze(self.review, LagRequest(*pieces, 0, 2, '1/2'))
        report = read(self.review, report_id)
        self.assertEqual(report.minimum_mse, F(0))
        self.assertEqual(report.intervals, ((F(1), F(3, 2)),))
        self.assertEqual(tuple(parent.piece_id for parent in report.parents), pieces)
        self.assertEqual(tuple(parent.source.revision_id for parent in report.parents), revisions)
        exported = json.loads(export_report(self.review, report_id))
        self.assertEqual(exported['report_id'], report_id)
        self.assertEqual(exported['report_unit'], 'u')
        self.assertEqual(exported['mse_unit'], 'u^2')
        self.assertEqual(exported['result'], {'status': 'ok', 'minimum_mse': '0', 'intervals': [['1', '3/2']]})

    def test_legal_frozen_plateau(self):
        self.source.close()
        a = accept(self.review, legal_piece(41, 'external', 'A', 301, [('0', '2', '1')]))
        b = accept(self.review, legal_piece(42, 'external', 'B', 307, [('0', '1', '1'), ('1', '2', '3')]))
        self.review.close()
        self.review = self.open_review()
        report = read(self.review, analyze(self.review, LagRequest(a, b, 0, 2, '1/2')))
        self.assertEqual((report.minimum_mse, report.intervals), (F(0), ((F(1), F(3, 2)),)))
        self.assertEqual([parent.source.revision_id for parent in report.parents], [301, 307])

    def test_point_window(self):
        _, pieces = self.plateau()
        self.source.close()
        threshold = read(self.review, analyze(self.review, LagRequest(*pieces, '3/2', '3/2', '1/2')))
        self.assertEqual(threshold.minimum_mse, F(0))
        self.assertEqual(threshold.intervals, ((F(3, 2), F(3, 2)),))
        after = read(self.review, analyze(self.review, LagRequest(*pieces, '8/5', '8/5', '1/2')))
        self.assertEqual((after.minimum_mse, after.intervals), (None, ()))

    def _split_curves(self, b_value):
        self.trial()
        a = self.submit('meter-a', observations((0, 1, 0), (3, 4, 0)))
        b = self.submit('meter-b', observations((3, 4, b_value), (0, 1, b_value)))
        pieces = self.deliver(a), self.deliver(b)
        self.source.close()
        return pieces

    def test_support_and_ties(self):
        pieces = self._split_curves(0)
        cases = [
            ('1/2', F(0), ((F(0), F(3, 4)), (F(5, 2), F(3)))),
            (2, F(0), ((F(0), F(0)),)),
            (3, None, ()),
        ]
        for minimum, score, intervals in cases:
            with self.subTest(minimum=minimum):
                report_id = analyze(self.review, LagRequest(*pieces, 0, 3, minimum))
                report = read(self.review, report_id)
                self.assertEqual((report.minimum_mse, report.intervals), (score, intervals))
                if score is None:
                    self.assertEqual(json.loads(export_report(self.review, report_id))['result'],
                                     {'status': 'empty', 'minimum_mse': None, 'intervals': []})
        self.assertEqual(count(self.review, 'review_reports'), 3)

    def test_nonzero_ties(self):
        pieces = self._split_curves(1)
        a, b = (read_accepted(self.review, piece).evidence for piece in pieces)
        for shift, seconds in ((0, 2), (F(3, 4), F(1, 2)), (1, 0), (F(5, 2), F(1, 2)), (3, 1)):
            with self.subTest(shift=shift):
                stats = measure_at(a, b, F(shift))
                self.assertEqual((stats.common_seconds, stats.squared_error_integral), (seconds, seconds))
        report = read(self.review, analyze(self.review, LagRequest(*pieces, 0, 3, '1/2')))
        self.assertEqual(report.minimum_mse, F(1))
        self.assertEqual(report.intervals, ((F(0), F(3, 4)), (F(5, 2), F(3))))

    def test_negative_shift_and_fractional_values(self):
        self.trial(factor=2)
        a = self.submit('meter-a', observations((0, 1, '1/3')))
        b = self.submit('meter-b', observations((1, 2, '1/6')))
        pieces = self.deliver(a), self.deliver(b)
        self.source.close()
        report = read(self.review, analyze(self.review, LagRequest(*pieces, -2, 0, '1/2')))
        self.assertEqual(report.minimum_mse, F(1, 9))
        self.assertEqual(report.intervals, ((F(-3, 2), F(-1, 2)),))

    def test_empty_curve(self):
        a = accept(self.review, legal_piece(41, 'external', 'A', 301, []))
        b = accept(self.review, legal_piece(42, 'external', 'B', 307, [('0', '2', '0')]))
        report = read(self.review, analyze(self.review, LagRequest(a, b, -2, 2, '1/10')))
        self.assertEqual((report.minimum_mse, report.intervals), (None, ()))

    def test_reject_cross_trial(self):
        _, pieces = self.plateau()
        self.trial('T2')
        foreign = self.deliver(self.submit('meter-b', observations((0, 2, 1)), trial_id='T2'))
        self.source.close()
        before_id = analyze(self.review, LagRequest(*pieces, 0, 2, 1))
        before = read(self.review, before_id)
        with self.assertRaisesRegex(ValueError, 'same trial'):
            analyze(self.review, LagRequest(pieces[0], foreign, 0, 2, 1))
        self.assertEqual(count(self.review, 'review_reports'), 1)
        self.assertEqual(read(self.review, before_id), before)

    def test_ordered_roles(self):
        _, (a, b) = self.plateau()
        good_id = analyze(self.review, LagRequest(a, b, 0, 2, 1))
        good = read(self.review, good_id)
        with self.assertRaisesRegex(ValueError, 'ordered A then B'):
            analyze(self.review, LagRequest(b, a, 0, 2, 1))
        self.assertEqual(count(self.review, 'review_reports'), 1)
        self.assertEqual(read(self.review, good_id), good)

    def test_missing_piece(self):
        _, pieces = self.plateau()
        good_id = analyze(self.review, LagRequest(*pieces, 0, 2, 1))
        good = read(self.review, good_id)
        with self.assertRaises(LookupError):
            analyze(self.review, LagRequest(pieces[0], 900, 0, 2, 1))
        self.assertEqual(count(self.review, 'review_reports'), 1)
        self.assertEqual(read(self.review, good_id), good)

    def test_invalid_request(self):
        _, pieces = self.plateau()
        good_id = analyze(self.review, LagRequest(*pieces, 0, 2, 1))
        good = read(self.review, good_id)
        for lower, upper, minimum in ((2, 0, 1), (0, 2, 0), (0, 2, -1), (0, 2, 0.5)):
            with self.subTest(request=(lower, upper, minimum)), self.assertRaises(ValueError):
                analyze(self.review, LagRequest(*pieces, lower, upper, minimum))
        self.assertEqual(count(self.review, 'review_reports'), 1)
        self.assertEqual(read(self.review, good_id), good)

    def test_reject_different_report_units(self):
        a = accept(self.review, legal_piece(41, 'external', 'A', 301, [('0', '2', '0')]))
        b = accept(self.review, legal_piece(42, 'external', 'B', 307, [('0', '2', '0')], unit='other'))
        with self.assertRaisesRegex(ValueError, 'same report unit'):
            analyze(self.review, LagRequest(a, b, 0, 2, 1))
        self.assertEqual(count(self.review, 'review_reports'), 0)

    def test_publish_failure_and_readback(self):
        _, pieces = self.plateau()
        self.source.close()
        request = LagRequest(*pieces, 0, 2, '1/2')
        old_id = analyze(self.review, request)
        old_report = read(self.review, old_id)
        old_pieces = tuple(read_accepted(self.review, piece) for piece in pieces)
        self.review.executescript('''
            CREATE TABLE valid_gate (gate_id INTEGER PRIMARY KEY);
            CREATE TABLE pending_gate (
                gate_id INTEGER REFERENCES valid_gate(gate_id) DEFERRABLE INITIALLY DEFERRED
            );
            CREATE TRIGGER fail_report_commit AFTER INSERT ON review_reports
            BEGIN
                INSERT INTO pending_gate VALUES (1);
            END;
        ''')
        with self.assertRaisesRegex(sqlite3.IntegrityError, 'FOREIGN KEY constraint failed'):
            analyze(self.review, request)
        self.assertFalse(self.review.in_transaction)
        observer = self.open_review()
        self.assertEqual(count(observer, 'review_reports'), 1)
        self.assertEqual(observer.execute('SELECT COUNT(*) FROM pending_gate').fetchone()[0], 0)
        self.assertEqual(read(observer, old_id), old_report)
        self.assertEqual(tuple(read_accepted(observer, piece) for piece in pieces), old_pieces)
        self.review.execute('DROP TRIGGER fail_report_commit')
        new_id = analyze(self.review, request)
        self.assertNotEqual(new_id, old_id)
        self.review.close()
        self.review = self.open_review()
        self.assertEqual(count(self.review, 'review_reports'), 2)
        self.assertEqual((read(self.review, old_id), read(self.review, new_id)), (old_report, old_report))

    def test_review_reopen(self):
        revisions, pieces = self.plateau()
        original_request = LagRequest(*pieces, 0, 2, '1/2')
        original_id = analyze(self.review, original_request)
        original = read(self.review, original_id)
        export_before = export_report(self.review, original_id)
        corrected = self.submit('meter-b', observations((0, 2, 5)), parent=revisions[1])
        corrected_piece = self.deliver(corrected)
        self.source.close()
        new_id = analyze(self.review, LagRequest(pieces[0], corrected_piece, 0, 2, '1/2'))
        still_old_id = analyze(self.review, original_request)
        new = read(self.review, new_id)
        self.assertEqual((new.minimum_mse, new.intervals), (F(16), ((F(0), F(3, 2)),)))
        self.assertEqual(new.parents[1].source.revision_id, corrected)
        self.assertEqual(original.parents[1].source.revision_id, revisions[1])
        self.assertEqual(read(self.review, still_old_id), original)
        self.review.close()
        self.review = self.open_review()
        second_open = self.open_review()
        self.assertEqual(count(second_open, 'review_inbox'), 3)
        self.assertEqual(count(second_open, 'review_reports'), 3)
        attempts = []

        def block_analysis_inputs(action, table, column, database, trigger):
            if action == sqlite3.SQLITE_READ and table == 'review_inbox':
                attempts.append(column)
                return sqlite3.SQLITE_DENY
            return sqlite3.SQLITE_OK

        self.review.set_authorizer(block_analysis_inputs)
        try:
            with self.assertRaises(sqlite3.DatabaseError):
                analyze(self.review, original_request)
            self.assertTrue(attempts)
            attempts.clear()
            self.assertEqual(read(self.review, original_id), original)
            self.assertEqual(export_report(self.review, original_id), export_before)
            self.assertEqual(read(self.review, new_id), new)
            self.assertEqual(attempts, [])
        finally:
            self.review.set_authorizer(None)
        self.assertEqual(count(self.review, 'review_inbox'), 3)
        self.assertEqual(count(self.review, 'review_reports'), 3)

    def test_unknown_report(self):
        _, pieces = self.plateau()
        report_id = analyze(self.review, LagRequest(*pieces, 0, 2, 1))
        before = read(self.review, report_id)
        for operation in (read, export_report):
            with self.assertRaisesRegex(LookupError, 'unknown report'):
                operation(self.review, report_id + 1)
        self.assertEqual(read(self.review, report_id), before)
        self.assertEqual(count(self.review, 'review_reports'), 1)
