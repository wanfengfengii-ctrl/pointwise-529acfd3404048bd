from dataclasses import dataclass
from fractions import Fraction
import sqlite3

from ledger.coverage import sum_covered_seconds
from ledger.revisions import read_revision
from ledger.storage import RevisionSnapshot


@dataclass(frozen=True, slots=True)
class TimeAccount:
    revision: RevisionSnapshot
    covered_seconds: Fraction


def account(db: sqlite3.Connection, revision_id: int) -> TimeAccount:
    revision = read_revision(db, revision_id)
    return TimeAccount(revision, sum_covered_seconds(revision.observations))
