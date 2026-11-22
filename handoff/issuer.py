from dataclasses import dataclass
import json
import sqlite3

from handoff.evidence import CurveEvidence, decode_evidence, encode_evidence
from trial.rationals import require_serial
from trial.roles import TableRole, TrialRoles, make_trial_roles, require_label, resolve_table_role


@dataclass(frozen=True, slots=True)
class FrozenSource:
    trial_id: str
    table_id: str
    role: TableRole
    revision_id: int
    report_unit: str
    roles: TrialRoles

    def __post_init__(self):
        require_label(self.trial_id, 'trial identifier')
        require_serial(self.revision_id, 'source revision')
        require_label(self.report_unit, 'report unit')
        if not isinstance(self.roles, TrialRoles):
            raise ValueError('expected the source trial roles')
        if resolve_table_role(self.roles, self.table_id) is not self.role:
            raise ValueError('source table does not occupy its declared role')


@dataclass(frozen=True, slots=True)
class FrozenCurve:
    piece_id: int
    source: FrozenSource
    evidence: CurveEvidence

    def __post_init__(self):
        require_serial(self.piece_id, 'piece number')
        if not isinstance(self.source, FrozenSource) or not isinstance(self.evidence, CurveEvidence):
            raise ValueError('frozen curve requires a source and curve evidence')


def source_payload(source: FrozenSource) -> dict:
    return {
        'trial_id': source.trial_id,
        'table_id': source.table_id,
        'role': source.role.value,
        'revision_id': source.revision_id,
        'report_unit': source.report_unit,
        'a_table': source.roles.a_table,
        'b_table': source.roles.b_table,
    }


def decode_source(payload: object) -> FrozenSource:
    fields = {'trial_id', 'table_id', 'role', 'revision_id', 'report_unit', 'a_table', 'b_table'}
    if not isinstance(payload, dict) or set(payload) != fields:
        raise ValueError('invalid frozen source fields')
    return FrozenSource(
        payload['trial_id'], payload['table_id'], TableRole(payload['role']),
        payload['revision_id'], payload['report_unit'],
        make_trial_roles(payload['a_table'], payload['b_table']),
    )


def validate_pair_sources(a: FrozenSource, b: FrozenSource) -> None:
    if a.role is not TableRole.A or b.role is not TableRole.B:
        raise ValueError('pieces must be ordered A then B')
    if a.trial_id != b.trial_id or a.roles != b.roles:
        raise ValueError('pieces must share the same trial and registered tables')
    if a.report_unit != b.report_unit:
        raise ValueError('pieces must use the same report unit')


def _json(payload: dict) -> str:
    return json.dumps(payload, sort_keys=True, separators=(',', ':'))


def _unique_fields(pairs: list) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f'duplicate frozen field: {key}')
        result[key] = value
    return result


def encode_frozen_curve(curve: FrozenCurve) -> str:
    return _json({
        'version': 1,
        'piece_id': curve.piece_id,
        'source': source_payload(curve.source),
        'evidence': encode_evidence(curve.evidence),
    })


def decode_frozen_curve(encoded: str) -> FrozenCurve:
    if not isinstance(encoded, str):
        raise ValueError('frozen curve must be JSON text')
    payload = json.loads(encoded, object_pairs_hook=_unique_fields)
    if not isinstance(payload, dict) or set(payload) != {'version', 'piece_id', 'source', 'evidence'}:
        raise ValueError('invalid frozen curve envelope')
    if type(payload['version']) is not int or payload['version'] != 1:
        raise ValueError('unsupported frozen curve version')
    return FrozenCurve(payload['piece_id'], decode_source(payload['source']), decode_evidence(payload['evidence']))


def initialize_issue_register(db: sqlite3.Connection) -> None:
    db.execute('''
        CREATE TABLE IF NOT EXISTS source_issues (
            piece_id INTEGER PRIMARY KEY,
            revision_id INTEGER NOT NULL REFERENCES ledger_revisions(revision_id),
            source TEXT NOT NULL,
            evidence TEXT NOT NULL
        )
    ''')
    db.execute('''
        CREATE TABLE IF NOT EXISTS trimmed_issues (
            piece_id INTEGER PRIMARY KEY REFERENCES source_issues(piece_id),
            a_revision_id INTEGER NOT NULL REFERENCES ledger_revisions(revision_id),
            b_revision_id INTEGER NOT NULL REFERENCES ledger_revisions(revision_id),
            payload TEXT NOT NULL
        )
    ''')


def issue_curve(db: sqlite3.Connection, source: FrozenSource, evidence: CurveEvidence) -> FrozenCurve:
    source_text = _json(source_payload(source))
    evidence_text = _json(encode_evidence(evidence))
    db.execute('BEGIN IMMEDIATE')
    with db:
        cursor = db.execute('''
            INSERT INTO source_issues(revision_id, source, evidence) VALUES (?, ?, ?)
        ''', (source.revision_id, source_text, evidence_text))
        return FrozenCurve(cursor.lastrowid, source, evidence)


def issue_trimmed(
    db: sqlite3.Connection,
    sources: tuple[FrozenSource, FrozenSource],
    lower,
    upper,
    joint_evidence,
) -> int:
    from handoff.joint import JointEvidence, encode_joint_piece
    if not isinstance(joint_evidence, JointEvidence):
        raise ValueError('trimmed issue requires joint evidence')
    a, b = sources
    db.execute('BEGIN IMMEDIATE')
    with db:
        cursor = db.execute('''
            INSERT INTO source_issues(revision_id, source, evidence) VALUES (?, ?, ?)
        ''', (a.revision_id, _json(source_payload(a)),
              _json({'trimmed': True, 'b_revision_id': b.revision_id})))
        piece_id = cursor.lastrowid
        from handoff.joint import JointPiece
        piece = JointPiece(piece_id, sources, lower, upper, joint_evidence)
        payload = encode_joint_piece(piece)
        db.execute('''
            INSERT INTO trimmed_issues(piece_id, a_revision_id, b_revision_id, payload)
            VALUES (?, ?, ?, ?)
        ''', (piece_id, a.revision_id, b.revision_id, payload))
        return piece_id
