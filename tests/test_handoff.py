from fractions import Fraction as F
import json

from handoff.acceptance import accept, read_accepted
from handoff.evidence import iter_effective_spans
from handoff.freeze import freeze
from handoff.issuer import encode_frozen_curve
from tests.fixtures import LabCase, count, legal_piece, observations


def curve_rows(curve):
    return tuple((span.start, span.end, span.value) for span in iter_effective_spans(curve.evidence))


class HandoffTests(LabCase):
    def test_revision_binding(self):
        self.trial()
        old = self.submit('meter-b', observations((3, 4, 0), (1, 2, 3), (0, 1, 1)))
        newer = self.submit('meter-b', observations((0, 1, 1), (1, 2, 5), (2, 3, 6), (3, 4, 0)), parent=old)
        old_id, new_id = self.deliver(old), self.deliver(newer)
        self.source.close()
        self.review.close()
        self.review = self.open_review()
        saved = read_accepted(self.review, old_id)
        self.assertEqual(saved.source.revision_id, old)
        self.assertEqual((saved.source.trial_id, saved.source.table_id, saved.source.role.value),
                         ('T1', 'meter-b', 'B'))
        self.assertEqual(curve_rows(saved), ((0, 1, 1), (1, 2, 3), (3, 4, 0)))
        changed = read_accepted(self.review, new_id)
        self.assertEqual(changed.source.revision_id, newer)
        self.assertEqual(curve_rows(changed), ((0, 1, 1), (1, 2, 5), (2, 3, 6), (3, 4, 0)))

    def test_distinct_switch(self):
        self.trial()
        switched = self.submit('meter-b', observations((0, 1, 1), (1, 2, 3), (3, 4, 0)))
        constant = self.submit('meter-b', observations((0, 2, 2), (3, 4, 0)), parent=switched)
        ids = tuple(self.deliver(revision) for revision in (switched, constant))
        self.source.close()
        left, right = (curve_rows(read_accepted(self.review, piece)) for piece in ids)
        self.assertEqual(left, ((0, 1, 1), (1, 2, 3), (3, 4, 0)))
        self.assertEqual(right, ((0, 2, 2), (3, 4, 0)))
        for curve, expected in ((left, 3), (right, 2)):
            self.assertEqual([value for start, end, value in curve if start <= F(3, 2) < end], [expected])
            self.assertEqual([value for start, end, value in curve if start <= F(5, 2) < end], [])
            self.assertEqual([value for start, end, value in curve if start <= F(7, 2) < end], [0])

    def test_missing_revision(self):
        self.trial()
        revision = self.submit('meter-a', observations((0, 1, 0)))
        freeze(self.source, revision)
        with self.assertRaises(LookupError):
            freeze(self.source, revision + 1)
        self.assertEqual(count(self.source, 'source_issues'), 1)

    def test_frozen_reading_uses_report_unit(self):
        self.trial(factor=2)
        revision = self.submit('meter-a', observations((0, 1, '1/3'), (1, 2, '1/3'), (3, 4, 0)))
        piece_id = self.deliver(revision)
        self.source.close()
        curve = read_accepted(self.review, piece_id)
        self.assertEqual(curve.source.report_unit, 'u')
        self.assertEqual(curve_rows(curve), ((0, 2, F(2, 3)), (3, 4, 0)))

    def test_duplicate_and_collision(self):
        self.trial()
        revision = self.submit('meter-a', observations((0, 2, 1)))
        original = freeze(self.source, revision)
        encoded = encode_frozen_curve(original)
        self.assertEqual(accept(self.review, encoded), original.piece_id)
        self.assertEqual(accept(self.review, encoded), original.piece_id)
        reordered = json.loads(encoded)
        reordered['evidence']['spans'][0][2] = '4/4'
        self.assertEqual(accept(self.review, json.dumps(reordered, indent=2)), original.piece_id)
        self.assertEqual(count(self.review, 'review_inbox'), 1)
        reordered['evidence']['spans'][0][2] = '2'
        with self.assertRaisesRegex(ValueError, 'conflicting contents'):
            accept(self.review, json.dumps(reordered))
        self.review.close()
        self.review = self.open_review()
        self.assertEqual(read_accepted(self.review, original.piece_id), original)
        self.assertEqual(count(self.review, 'review_inbox'), 1)

    def test_invalid_envelope(self):
        encoded = legal_piece(41, 'outside', 'A', 17, [('0', '1', '4')])
        piece_id = accept(self.review, encoded)
        original = read_accepted(self.review, piece_id)
        missing = json.loads(encoded)
        del missing['source']['revision_id']
        wrong_table = json.loads(encoded)
        wrong_table['source']['role'] = 'B'
        wrong_version = json.loads(encoded)
        wrong_version['version'] = True
        overlapping = json.loads(encoded)
        overlapping['evidence']['spans'].append(['1/2', '2', '4'])
        for payload in (missing, wrong_table, wrong_version, overlapping):
            with self.subTest(payload=payload), self.assertRaises(ValueError):
                accept(self.review, json.dumps(payload))
        with self.assertRaises(ValueError):
            accept(self.review, encoded[:-1] + ', "version": 1}')
        self.assertEqual(read_accepted(self.review, piece_id), original)
        self.assertEqual(count(self.review, 'review_inbox'), 1)
