from collections.abc import Iterable
import sqlite3

from ledger.coverage import validate_disjoint_coverage
from ledger.observations import ObservationInput, bind_observations
from ledger.storage import RevisionSnapshot, has_series_revisions, insert_revision, load_revision
from trial.eligibility import require_eligible_table


def require_parent_revision(
    db: sqlite3.Connection, trial_id: str, table_id: str, parent_id: int | None
) -> RevisionSnapshot | None:
    if parent_id is None:
        if has_series_revisions(db, trial_id, table_id):
            raise ValueError('a correction must specify its parent revision')
        return None
    parent = load_revision(db, parent_id)
    if (parent.trial_id, parent.table_id) != (trial_id, table_id):
        raise ValueError('parent revision is outside the submitted trial and table')
    return parent


def submit(
    db: sqlite3.Connection,
    trial_id: str,
    table_id: str,
    parent_id: int | None,
    records: Iterable[ObservationInput],
) -> int:
    db.execute('BEGIN IMMEDIATE')
    with db:
        _, role, binding = require_eligible_table(db, trial_id, table_id)
        require_parent_revision(db, trial_id, table_id, parent_id)
        observations = bind_observations(records, binding)
        validate_disjoint_coverage(observations)
        return insert_revision(db, trial_id, table_id, role, parent_id, binding, observations)


def read_revision(db: sqlite3.Connection, revision_id: int) -> RevisionSnapshot:
    return load_revision(db, revision_id)
