from dataclasses import dataclass
import sqlite3

from trial.rationals import RationalInput, format_rational
from trial.roles import TrialRoles, make_trial_roles, require_label
from trial.units import UnitBinding, make_unit_binding


@dataclass(frozen=True, slots=True)
class TrialRegistration:
    trial_id: str
    roles: TrialRoles
    a_binding: UnitBinding
    b_binding: UnitBinding

    @property
    def report_unit(self) -> str:
        return self.a_binding.report_unit


def initialize_trial_registry(db: sqlite3.Connection) -> None:
    db.execute('''
        CREATE TABLE IF NOT EXISTS trial_registry (
            trial_id TEXT PRIMARY KEY NOT NULL,
            a_table TEXT NOT NULL,
            b_table TEXT NOT NULL,
            report_unit TEXT NOT NULL,
            a_unit TEXT NOT NULL,
            a_factor TEXT NOT NULL,
            b_unit TEXT NOT NULL,
            b_factor TEXT NOT NULL,
            CHECK (a_table <> b_table)
        )
    ''')


def _load(db: sqlite3.Connection, trial_id: str) -> TrialRegistration | None:
    row = db.execute('''
        SELECT a_table, b_table, report_unit, a_unit, a_factor, b_unit, b_factor
        FROM trial_registry WHERE trial_id = ?
    ''', (trial_id,)).fetchone()
    if row is None:
        return None
    a_table, b_table, report_unit, a_unit, a_factor, b_unit, b_factor = row
    return TrialRegistration(
        trial_id, make_trial_roles(a_table, b_table),
        make_unit_binding(a_unit, report_unit, a_factor),
        make_unit_binding(b_unit, report_unit, b_factor),
    )


def load_trial(db: sqlite3.Connection, trial_id: str) -> TrialRegistration:
    trial = _load(db, require_label(trial_id, 'trial identifier'))
    if trial is None:
        raise LookupError(f'unknown trial: {trial_id}')
    return trial


def register(
    db: sqlite3.Connection,
    trial_id: str,
    a_table: str,
    b_table: str,
    report_unit: str,
    a_unit: str,
    a_factor: RationalInput,
    b_unit: str,
    b_factor: RationalInput,
) -> TrialRegistration:
    proposed = TrialRegistration(
        require_label(trial_id, 'trial identifier'), make_trial_roles(a_table, b_table),
        make_unit_binding(a_unit, report_unit, a_factor),
        make_unit_binding(b_unit, report_unit, b_factor),
    )
    db.execute('BEGIN IMMEDIATE')
    with db:
        current = _load(db, trial_id)
        if current is not None:
            if current != proposed:
                raise ValueError(f'conflicting registration for {trial_id}')
            return current
        db.execute('''
            INSERT INTO trial_registry (
                trial_id, a_table, b_table, report_unit, a_unit, a_factor, b_unit, b_factor
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ''', (trial_id, a_table, b_table, report_unit,
              a_unit, format_rational(proposed.a_binding.factor),
              b_unit, format_rational(proposed.b_binding.factor)))
    return proposed
