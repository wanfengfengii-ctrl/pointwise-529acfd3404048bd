import sqlite3

from handoff.evidence import CurveEvidence, EffectiveSpan
from handoff.issuer import FrozenCurve, FrozenSource, issue_curve, issue_trimmed
from handoff.joint import JointPiece, build_joint_evidence, encode_joint_piece
from ledger.coverage import validate_disjoint_coverage
from ledger.revisions import read_revision
from ledger.storage import RevisionSnapshot
from trial.eligibility import require_eligible_table
from trial.rationals import parse_rational
from trial.roles import TableRole


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


def _frozen_source_for_revision(db: sqlite3.Connection, revision_id: int, role: TableRole) -> tuple:
    revision = read_revision(db, revision_id)
    trial, actual_role, binding = require_eligible_table(db, revision.trial_id, revision.table_id)
    if actual_role is not role or revision.role is not role or revision.binding != binding:
        raise ValueError('revision source does not match its registered role')
    source = FrozenSource(trial.trial_id, revision.table_id, role, revision.revision_id,
                          binding.report_unit, trial.roles)
    return source, build_revision_evidence(revision)


def freeze_trimmed(
    db: sqlite3.Connection,
    a_revision_id: int,
    b_revision_id: int,
    lower,
    upper,
) -> str:
    lower, upper = parse_rational(lower), parse_rational(upper)
    if lower > upper:
        raise ValueError('lag window must be ordered')
    a_source, a_evidence = _frozen_source_for_revision(db, a_revision_id, TableRole.A)
    b_source, b_evidence = _frozen_source_for_revision(db, b_revision_id, TableRole.B)
    if a_source.trial_id != b_source.trial_id or a_source.roles != b_source.roles:
        raise ValueError('revisions must belong to the same registered trial')
    if a_source.report_unit != b_source.report_unit:
        raise ValueError('revisions must use the same report unit')
    joint_evidence = build_joint_evidence(a_evidence, b_evidence, lower, upper)
    piece_id = issue_trimmed(db, (a_source, b_source), lower, upper, joint_evidence)
    return encode_joint_piece(JointPiece(piece_id, (a_source, b_source), lower, upper, joint_evidence))
