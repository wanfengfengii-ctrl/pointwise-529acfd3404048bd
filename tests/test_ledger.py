from fractions import Fraction as F

from ledger.revisions import read_revision
from ledger.time_account import account
from tests.fixtures import LabCase, count, observations
from trial.registry import load_trial, register
from trial.roles import TableRole


class TrialLedgerTests(LabCase):
    def test_repeat_registration_and_time_account(self):
        trial = self.trial(factor=2)
        for _ in range(2):
            self.source.close()
            self.source = self.open_source()
            self.assertEqual(self.trial(factor='4/2'), trial)
        revision = self.submit('meter-a', observations((0, 1, 0), (2, 4, 3)))
        booked = account(self.source, revision)
        self.assertEqual(count(self.source, 'trial_registry'), 1)
        self.assertEqual(booked.revision.role, TableRole.A)
        self.assertEqual(booked.covered_seconds, F(3))
        self.assertEqual([row.value for row in booked.revision.observations], [F(0), F(6)])
        self.assertEqual([row.original_value for row in booked.revision.observations], [F(0), F(3)])

    def test_registration_conflict(self):
        original = self.trial(factor=2)
        self.source.close()
        self.source = self.open_source()
        with self.assertRaisesRegex(ValueError, 'conflicting registration'):
            self.trial(factor=3)
        self.assertEqual(load_trial(self.source, 'T1'), original)
        self.assertEqual(count(self.source, 'trial_registry'), 1)
        revision = self.submit('meter-a', observations((0, 1, 3)))
        self.assertEqual(account(self.source, revision).revision.observations[0].value, F(6))

    def test_exact_units(self):
        register(self.source, 'T1', 'meter-a', 'meter-b', 'scaled', 'raw', 2, 'scaled', 1)
        revision = self.submit('meter-a', observations(('1/7', '2/7', '1/3'), unit='raw'))
        self.source.close()
        self.source = self.open_source()
        booked = account(self.source, revision)
        span, = booked.revision.observations
        self.assertEqual((span.start, span.end, booked.covered_seconds), (F(1, 7), F(2, 7), F(1, 7)))
        self.assertEqual((span.original_unit, span.original_value, span.value), ('raw', F(1, 3), F(2, 3)))
        self.assertEqual((span.binding.input_unit, span.binding.report_unit, span.binding.factor),
                         ('raw', 'scaled', F(2)))

    def test_source_reopen(self):
        trial = self.trial(factor=2)
        old = self.submit('meter-b', observations((3, 4, 1), (0, 1, 0)))
        new = self.submit('meter-b', observations((0, 4, 3)), parent=old)
        before = [account(self.source, revision) for revision in (old, new)]
        self.assertEqual([item.covered_seconds for item in before], [F(2), F(4)])
        self.source.close()
        self.source = self.open_source()
        reopened = self.open_source()
        self.assertEqual(self.trial(factor=2), trial)
        self.assertEqual([account(reopened, revision) for revision in (old, new)], before)
        self.assertEqual(count(reopened, 'trial_registry'), 1)
        self.assertEqual(count(reopened, 'ledger_revisions'), 2)
        self.assertEqual(count(reopened, 'source_issues'), 0)

    def test_reject_overlapping_correction(self):
        self.trial()
        revision = self.submit('meter-a', observations((0, 2, 1)))
        before = account(self.source, revision)
        with self.assertRaisesRegex(ValueError, 'overlapping records'):
            self.submit('meter-a', observations((0, 2, 5), (1, 3, 6)), parent=revision)
        self.assertEqual(account(self.source, revision), before)
        self.assertEqual(count(self.source, 'ledger_revisions'), 1)

    def test_parent_scope(self):
        self.trial()
        self.trial('T2')
        a = self.submit('meter-a', observations((0, 2, 0)))
        other_a = self.submit('meter-a', observations((0, 2, 0)), trial_id='T2')
        records = observations((0, 2, 1))
        with self.assertRaises(LookupError):
            self.submit('meter-a', records, parent=900)
        with self.assertRaisesRegex(ValueError, 'outside'):
            self.submit('meter-b', records, parent=a)
        with self.assertRaisesRegex(ValueError, 'outside'):
            self.submit('meter-a', records, parent=other_a)
        with self.assertRaisesRegex(ValueError, 'specify its parent'):
            self.submit('meter-a', records)
        self.assertEqual(count(self.source, 'ledger_revisions'), 2)

    def test_permuted_overlap(self):
        self.trial()
        old = self.submit('meter-a', observations((0, 2, 7)))
        with self.assertRaisesRegex(ValueError, 'overlapping records 1 and 3'):
            self.submit('meter-a', observations((0, 2, 1), (4, 5, 2), (1, 3, 3)), parent=old)
        self.source.close()
        self.source = self.open_source()
        self.assertEqual(count(self.source, 'ledger_revisions'), 1)
        self.assertEqual(account(self.source, old).covered_seconds, F(2))
        new = self.submit('meter-a', observations((2, 3, 1), (5, 6, 5), (0, 2, 0)), parent=old)
        booked = account(self.source, new)
        self.assertEqual([(row.ordinal, row.start) for row in booked.revision.observations],
                         [(1, F(2)), (2, F(5)), (3, F(0))])
        self.assertEqual(booked.covered_seconds, F(4))

    def test_new_revision_isolation(self):
        self.trial()
        old = self.submit('meter-b', observations((0, 1, 1), (2, 3, 0)))
        original = account(self.source, old)
        new = self.submit('meter-b', observations((0, 3, 7)), parent=old)
        branch = self.submit('meter-b', observations((0, 1, 2)), parent=old)
        self.assertNotEqual(new, branch)
        self.assertEqual(read_revision(self.source, new).parent_id, old)
        self.assertEqual(read_revision(self.source, branch).parent_id, old)
        self.assertEqual(account(self.source, old), original)
        self.assertEqual(account(self.source, new).covered_seconds, F(3))
        self.assertEqual(count(self.source, 'ledger_revisions'), 3)

    def test_invalid_input_and_empty_account(self):
        with self.assertRaises(ValueError):
            register(self.source, 'T1', 'same', 'same', 'u', 'u', 1, 'u', 1)
        with self.assertRaises(ValueError):
            self.trial(factor=0)
        self.assertEqual(count(self.source, 'trial_registry'), 0)
        self.trial()
        with self.assertRaisesRegex(ValueError, 'outside the trial'):
            self.submit('meter-c', ())
        for records in (observations((1, 1, 7)), observations((0, 1, 0), unit='wrong'),
                        observations((0, 1, 0.1)), observations((0, 1, '1/0'))):
            with self.subTest(records=records), self.assertRaises(ValueError):
                self.submit('meter-a', records)
        self.assertEqual(count(self.source, 'ledger_revisions'), 0)
        revision = self.submit('meter-a', ())
        self.assertEqual(account(self.source, revision).covered_seconds, F(0))
        self.assertEqual(account(self.source, revision).revision.observations, ())
        with self.assertRaises(LookupError):
            account(self.source, revision + 1)
