from dataclasses import dataclass
import json
import sqlite3

from ledger.observations import BoundObservation
from trial.rationals import format_rational, parse_rational, require_serial
from trial.roles import TableRole
from trial.units import UnitBinding, make_unit_binding


@dataclass(frozen=True, slots=True)
class RevisionSnapshot:
    revision_id: int
    trial_id: str
    table_id: str
    role: TableRole
    parent_id: int | None
    binding: UnitBinding
    observations: tuple[BoundObservation, ...]


def initialize_revision_ledger(db: sqlite3.Connection) -> None:
    db.execute('''
        CREATE TABLE IF NOT EXISTS ledger_revisions (
            revision_id INTEGER PRIMARY KEY,
            trial_id TEXT NOT NULL REFERENCES trial_registry(trial_id),
            table_id TEXT NOT NULL,
            role TEXT NOT NULL CHECK (role IN ('A', 'B')),
            parent_id INTEGER REFERENCES ledger_revisions(revision_id),
            input_unit TEXT NOT NULL,
            report_unit TEXT NOT NULL,
            factor TEXT NOT NULL,
            observations TEXT NOT NULL
        )
    ''')
    db.execute('''
        CREATE INDEX IF NOT EXISTS ledger_revisions_by_table
        ON ledger_revisions(trial_id, table_id)
    ''')


def has_series_revisions(db: sqlite3.Connection, trial_id: str, table_id: str) -> bool:
    return db.execute('''
        SELECT 1 FROM ledger_revisions WHERE trial_id = ? AND table_id = ? LIMIT 1
    ''', (trial_id, table_id)).fetchone() is not None


def insert_revision(
    db: sqlite3.Connection,
    trial_id: str,
    table_id: str,
    role: TableRole,
    parent_id: int | None,
    binding: UnitBinding,
    observations: tuple[BoundObservation, ...],
) -> int:
    records = [
        [format_rational(value) for value in (span.start, span.end, span.original_value, span.value)]
        for span in observations
    ]
    cursor = db.execute('''
        INSERT INTO ledger_revisions (
            trial_id, table_id, role, parent_id, input_unit, report_unit, factor, observations
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    ''', (trial_id, table_id, role.value, parent_id, binding.input_unit,
          binding.report_unit, format_rational(binding.factor), json.dumps(records, separators=(',', ':'))))
    return cursor.lastrowid


def load_revision(db: sqlite3.Connection, revision_id: int) -> RevisionSnapshot:
    require_serial(revision_id, 'revision number')
    row = db.execute('''
        SELECT trial_id, table_id, role, parent_id, input_unit, report_unit, factor, observations
        FROM ledger_revisions WHERE revision_id = ?
    ''', (revision_id,)).fetchone()
    if row is None:
        raise LookupError(f'unknown revision: {revision_id}')
    trial_id, table_id, role, parent_id, input_unit, report_unit, factor, payload = row
    binding = make_unit_binding(input_unit, report_unit, factor)
    observations = []
    for ordinal, fields in enumerate(json.loads(payload), start=1):
        start, end, original, converted = map(parse_rational, fields)
        observations.append(BoundObservation(ordinal, start, end, original, binding, converted))
    return RevisionSnapshot(revision_id, trial_id, table_id, TableRole(role), parent_id,
                            binding, tuple(observations))
