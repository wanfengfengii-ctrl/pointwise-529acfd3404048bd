import sqlite3

from handoff.evidence import CurveEvidence, EffectiveSpan
from handoff.issuer import FrozenCurve, FrozenSource, issue_curve
from ledger.coverage import validate_disjoint_coverage
from ledger.revisions import read_revision
from ledger.storage import RevisionSnapshot
from trial.eligibility import require_eligible_table


def build_revision_evidence(revision: RevisionSnapshot) -> CurveEvidence:
    spans = []
    for observation in validate_disjoint_coverage(revision.observations):
        current = EffectiveSpan(observation.start, observation.end, observation.value)
        if spans and spans[-1].end == current.start and spans[-1].value == current.value:
            previous = spans.pop()
            current = EffectiveSpan(previous.start, current.end, current.value)
        spans.append(current)
    return CurveEvidence(tuple(spans))


def freeze(db: sqlite3.Connection, revision_id: int) -> FrozenCurve:
    revision = read_revision(db, revision_id)
    trial, role, binding = require_eligible_table(db, revision.trial_id, revision.table_id)
    if revision.role is not role or revision.binding != binding:
        raise ValueError('revision source does not match the trial registration')
    source = FrozenSource(trial.trial_id, revision.table_id, role, revision.revision_id,
                          binding.report_unit, trial.roles)
    return issue_curve(db, source, build_revision_evidence(revision))
