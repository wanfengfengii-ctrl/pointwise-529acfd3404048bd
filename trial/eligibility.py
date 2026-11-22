import sqlite3

from trial.registry import TrialRegistration, load_trial
from trial.roles import TableRole, resolve_table_role
from trial.units import UnitBinding


def require_eligible_table(
    db: sqlite3.Connection, trial_id: str, table_id: str
) -> tuple[TrialRegistration, TableRole, UnitBinding]:
    trial = load_trial(db, trial_id)
    role = resolve_table_role(trial.roles, table_id)
    binding = trial.a_binding if role is TableRole.A else trial.b_binding
    return trial, role, binding
