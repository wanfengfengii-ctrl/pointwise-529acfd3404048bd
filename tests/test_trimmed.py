import json
import sqlite3
from contextlib import closing
from fractions import Fraction as F

from analysis.selection import analyze_trimmed
from handoff.acceptance import accept, accept_trimmed, read_accepted_trimmed
from handoff.freeze import freeze, freeze_trimmed
from handoff.inbox import initialize_inbox
from handoff.issuer import encode_frozen_curve, initialize_issue_register
from handoff.joint import decode_joint_piece
from ledger.observations import ObservationInput
from ledger.revisions import submit
from ledger.storage import initialize_revision_ledger
from reports.archive import initialize_report_archive
from reports.read import export_trimmed, read_trimmed
from trial.registry import initialize_trial_registry, register
from tests.fixtures import LabCase, count, observations


class TrimmedLabCase(LabCase):
    def build_pair(self, a_rows, b_rows, trial_id='T1'):
        self.trial(trial_id)
        a = self.submit('meter-a', observations(*a_rows), trial_id=trial_id)
        b = self.submit('meter-b', observations(*b_rows), trial_id=trial_id)
        return a, b

    def issue(self, a, b, lower, upper):
        return accept_trimmed(self.review, freeze_trimmed(self.source, a, b, lower, upper))


class JointPieceTests(TrimmedLabCase):
    def test_envelope_and_evidence_fields(self):
        a, b = self.build_pair(((0, 2, 0),), ((0, 1, 0), (1, 2, 5)))
        encoded = freeze_trimmed(self.source, a, b, 0, 1)
        envelope = json.loads(encoded)
        self.assertEqual(set(envelope), {'version', 'piece_id', 'sources',
                                         'lag_window_seconds', 'evidence'})
        self.assertEqual(envelope['version'], 2)
        self.assertEqual(envelope['lag_window_seconds'], ['0', '1'])
        self.assertEqual([source['role'] for source in envelope['sources']], ['A', 'B'])
        evidence = envelope['evidence']
        self.assertEqual(set(evidence), {'lag_window_seconds', 'cells'})
        self.assertTrue(evidence['cells'])
        for cell in evidence['cells']:
            self.assertEqual(set(cell), {'lag_window_seconds', 'rows'})
            for row in cell['rows']:
                slope, intercept, squared_error = row
                self.assertIn(slope, {'-1', '0', '1'})
                self.assertGreaterEqual(F(squared_error), 0)
        self.assertEqual(accept_trimmed(self.review, encoded), envelope['piece_id'])

    def test_equivalent_repost_keeps_first_acceptance(self):
        a, b = self.build_pair(((0, 2, 0),), ((0, 1, 0), (1, 2, 5)))
        encoded = freeze_trimmed(self.source, a, b, 0, 1)
        piece_id = accept_trimmed(self.review, encoded)
        envelope = json.loads(encoded)
        respelled = json.dumps(dict(envelope, lag_window_seconds=['0.0', '2/2']), indent=2)
        self.assertEqual(accept_trimmed(self.review, respelled), piece_id)
        self.assertEqual(count(self.review, 'review_inbox'), 1)

    def test_same_piece_conflict_is_rejected(self):
        a, b = self.build_pair(((0, 2, 0),), ((0, 1, 0), (1, 2, 5)))
        encoded = freeze_trimmed(self.source, a, b, 0, 1)
        piece_id = accept_trimmed(self.review, encoded)
        alt = self.submit('meter-b', observations((0, 2, 9)), parent=b)
        conflicting = freeze_trimmed(self.source, a, alt, 0, 1)
        envelope = json.loads(conflicting)
        envelope['piece_id'] = piece_id
        with self.assertRaisesRegex(ValueError, 'conflicting contents'):
            accept_trimmed(self.review, json.dumps(envelope))
        self.assertEqual(read_accepted_trimmed(self.review, piece_id),
                         decode_joint_piece(encoded))

    def test_v1_piece_rejected_from_trimmed_inbox_and_reverse(self):
        a, b = self.build_pair(((0, 2, 1),), ((0, 1, 1), (1, 2, 3)))
        v1_text = encode_frozen_curve(freeze(self.source, a))
        with self.assertRaises(ValueError):
            accept_trimmed(self.review, v1_text)
        v2_text = freeze_trimmed(self.source, a, b, 0, 1)
        with self.assertRaises(ValueError):
            accept(self.review, v2_text)

    def test_reject_wrong_role_order_and_cross_trial(self):
        a, b = self.build_pair(((0, 2, 0),), ((0, 1, 0), (1, 2, 5)))
        with self.assertRaises(ValueError):
            freeze_trimmed(self.source, b, a, 0, 1)
        self.trial('T2')
        foreign = self.submit('meter-b', observations((0, 1, 1)), trial_id='T2')
        with self.assertRaises(ValueError):
            freeze_trimmed(self.source, a, foreign, 0, 1)

    def test_bad_evidence_rejected_without_storage(self):
        a, b = self.build_pair(((0, 2, 0),), ((0, 1, 0), (1, 2, 5)))
        encoded = freeze_trimmed(self.source, a, b, 0, 1)
        envelope = json.loads(encoded)
        before = count(self.review, 'review_inbox')
        broken = dict(envelope, evidence=None)
        with self.assertRaises(ValueError):
            accept_trimmed(self.review, json.dumps(broken))
        bad_cells = json.loads(json.dumps(envelope))
        bad_cells['evidence']['cells'][0]['rows'][0][2] = '-1'
        with self.assertRaises(ValueError):
            accept_trimmed(self.review, json.dumps(bad_cells))
        self.assertEqual(count(self.review, 'review_inbox'), before)

    def test_piece_numbers_share_the_issue_domain(self):
        a, b = self.build_pair(((0, 2, 0),), ((0, 1, 0), (1, 2, 5)))
        first_v1 = accept(self.review, encode_frozen_curve(freeze(self.source, a)))
        joint_id = accept_trimmed(self.review, freeze_trimmed(self.source, a, b, 0, 1))
        self.assertGreater(joint_id, first_v1)
        self.assertEqual(
            self.source.execute('SELECT COUNT(*) FROM trimmed_issues').fetchone()[0], 1)


class TrimmedAnalysisTests(TrimmedLabCase):
    def setUp(self):
        super().setUp()
        self.a, self.b = self.build_pair(
            ((0, 2, 0),), ((0, 1, 0), (1, 2, 5)))
        self.piece = self.issue(self.a, self.b, 0, 1)

    def sign(self, piece=None, budget='1/2', minimum=1):
        return analyze_trimmed(self.review, self.piece if piece is None else piece,
                               budget, minimum)

    def test_headline_trimmed_report(self):
        report = read_trimmed(self.review, self.sign())
        self.assertEqual(report['version'], 2)
        self.assertEqual(report['piece_id'], self.piece)
        self.assertEqual(report['request'], {
            'lag_window_seconds': ['0', '1'], 'max_trim_seconds': '1/2',
            'min_retained_seconds': '1'})
        self.assertEqual(report['result'],
                         {'status': 'ok', 'minimum_mse': '0',
                          'intervals': [['1/2', '1']]})

    def test_zero_budget_matches_v1_shape(self):
        report = read_trimmed(self.review, self.sign(budget=0, minimum=1))
        self.assertEqual(report['result'],
                         {'status': 'ok', 'minimum_mse': '0',
                          'intervals': [['1', '1']]})

    def test_empty_result(self):
        report = read_trimmed(self.review, self.sign(budget='1/2', minimum=3))
        self.assertEqual(report['result'],
                         {'status': 'empty', 'minimum_mse': None, 'intervals': []})

    def test_point_window_value_five(self):
        quarter = self.issue(self.a, self.b, '1/4', '1/4')
        report = read_trimmed(
            self.review, analyze_trimmed(self.review, quarter, '1/2', 1))
        self.assertEqual(report['result'],
                         {'status': 'ok', 'minimum_mse': '5',
                          'intervals': [['1/4', '1/4']]})

    def test_alternative_b_revision(self):
        alt = self.submit('meter-b', observations((0, 1, 3), (1, 2, 4)), parent=self.b)
        piece = self.issue(self.a, alt, 0, 0)
        report = read_trimmed(
            self.review, analyze_trimmed(self.review, piece, 1, 1))
        self.assertEqual(report['result']['minimum_mse'], '9')

    def test_gap_trial_three_components(self):
        ga, gb = self.build_pair(
            ((0, 1, 0), (3, 4, 0)), ((0, 1, 5), (3, 4, 0)), trial_id='G')
        piece = self.issue(ga, gb, -3, 3)
        report = read_trimmed(
            self.review, analyze_trimmed(self.review, piece, '1/2', '1/2'))
        self.assertEqual(report['result'], {
            'status': 'ok', 'minimum_mse': '0',
            'intervals': [['-3', '-5/2'], ['-1/2', '-1/2'], ['1/2', '1/2']]})

    def test_invalid_requests_and_unknown_piece(self):
        for budget, minimum in ((-1, 1), ('1/2', 0), ('1/2', -2)):
            with self.subTest(budget=budget, minimum=minimum):
                with self.assertRaises(ValueError):
                    analyze_trimmed(self.review, self.piece, budget, minimum)
        with self.assertRaises(LookupError):
            analyze_trimmed(self.review, 9223372036854775807, 0, 1)
        self.assertEqual(count(self.review, 'trimmed_reports'), 0)

    def test_v1_piece_cannot_drive_trimmed_analysis(self):
        v1_piece = accept(self.review, encode_frozen_curve(freeze(self.source, self.a)))
        with self.assertRaises(ValueError):
            analyze_trimmed(self.review, v1_piece, 0, 1)

    def test_export_roundtrip_and_persistence(self):
        report_id = self.sign()
        exported = json.loads(export_trimmed(self.review, report_id))
        self.assertEqual(exported, read_trimmed(self.review, report_id))
        self.review.close()
        self.review = self.open_review()
        self.assertEqual(json.loads(export_trimmed(self.review, report_id)), exported)
        with self.assertRaises(LookupError):
            read_trimmed(self.review, report_id + 1)

    def test_commit_failure_leaves_no_report_and_retries(self):
        self.review.executescript('''
            CREATE TABLE trim_gate (id INTEGER PRIMARY KEY);
            CREATE TABLE trim_pending (ref INTEGER REFERENCES trim_gate(id)
                                       DEFERRABLE INITIALLY DEFERRED);
            CREATE TRIGGER fail_trimmed AFTER INSERT ON trimmed_reports
            BEGIN
                INSERT INTO trim_pending VALUES (1);
            END;
        ''')
        with self.assertRaises(sqlite3.IntegrityError):
            self.sign()
        self.assertFalse(self.review.in_transaction)
        self.assertEqual(count(self.review, 'trimmed_reports'), 0)
        self.review.execute('DROP TRIGGER fail_trimmed')
        report_id = self.sign()
        self.assertEqual(read_trimmed(self.review, report_id)['result']['minimum_mse'], '0')

    def test_reopen_readback_ignores_later_correction(self):
        import tempfile
        from pathlib import Path
        root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        review_path = root / 'review.sqlite'
        source_path = root / 'source.sqlite'
        with closing(sqlite3.connect(source_path)) as source, \
                closing(sqlite3.connect(review_path)) as review:
            review.execute('PRAGMA foreign_keys=ON')
            initialize_trial_registry(source)
            initialize_revision_ledger(source)
            initialize_issue_register(source)
            initialize_inbox(review)
            initialize_report_archive(review)
            register(source, 'T', 'meter-a', 'meter-b', 'u', 'u', 1, 'u', 1)
            a = submit(source, 'T', 'meter-a', None,
                       [ObservationInput(0, 2, 0, 'u')])
            b = submit(source, 'T', 'meter-b', None,
                       [ObservationInput(0, 1, 0, 'u'), ObservationInput(1, 2, 5, 'u')])
            piece_id = accept_trimmed(review, freeze_trimmed(source, a, b, 0, 1))
            report_id = analyze_trimmed(review, piece_id, '1/2', 1)
            snapshot = read_trimmed(review, report_id)
        # Station closed: a later correction lands in the offline source DB.
        with closing(sqlite3.connect(source_path)) as source:
            submit(source, 'T', 'meter-b', b, [ObservationInput(0, 2, 9, 'u')])
        with closing(sqlite3.connect(review_path)) as reopened:
            self.assertEqual(read_trimmed(reopened, report_id), snapshot)
            self.assertEqual(json.loads(export_trimmed(reopened, report_id)), snapshot)


class JointEvidenceInvariantTests(TrimmedLabCase):
    def test_decode_rejects_broken_window_and_knot_totals(self):
        a, b = self.build_pair(
            ((0, 1, 0), (3, 4, 0)), ((0, 1, 5), (3, 4, 0)))
        encoded = freeze_trimmed(self.source, a, b, -3, 3)
        envelope = json.loads(encoded)
        # Drop a cell: window no longer tiled.
        shortened = json.loads(json.dumps(envelope))
        shortened['evidence']['cells'].pop()
        with self.assertRaises(ValueError):
            decode_joint_piece(json.dumps(shortened))
        # Negative duration at a cell end.
        broken = json.loads(json.dumps(envelope))
        first = broken['evidence']['cells'][0]
        first['rows'][0][1] = '-100'
        with self.assertRaises(ValueError):
            decode_joint_piece(json.dumps(broken))

    def test_no_common_time_keeps_empty_cells(self):
        a, b = self.build_pair(((0, 1, 0),), ((5, 6, 1),))
        piece_id = self.issue(a, b, 0, 1)
        piece = read_accepted_trimmed(self.review, piece_id)
        self.assertTrue(all(cell.rows == () for cell in piece.evidence.cells))
        report = read_trimmed(
            self.review, analyze_trimmed(self.review, piece_id, 0, '1/2'))
        self.assertEqual(report['result'],
                         {'status': 'empty', 'minimum_mse': None, 'intervals': []})

    def test_repeated_initialization_is_idempotent_on_old_database(self):
        from handoff.issuer import initialize_issue_register
        from reports.archive import initialize_report_archive
        initialize_issue_register(self.source)
        initialize_report_archive(self.review)
        initialize_issue_register(self.source)
        initialize_report_archive(self.review)
        a, b = self.build_pair(((0, 1, 0),), ((0, 1, 1),))
        piece = self.issue(a, b, 0, 0)
        self.assertIsInstance(piece, int)
