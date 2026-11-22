from dataclasses import dataclass
from enum import Enum


class TableRole(str, Enum):
    A = 'A'
    B = 'B'


def require_label(value: str, label: str) -> str:
    if not isinstance(value, str) or not value.strip() or '\x00' in value:
        raise ValueError(f'{label} must be nonempty text')
    return value


@dataclass(frozen=True, slots=True)
class TrialRoles:
    a_table: str
    b_table: str

    def __post_init__(self):
        require_label(self.a_table, 'A table')
        require_label(self.b_table, 'B table')
        if self.a_table == self.b_table:
            raise ValueError('the two table identifiers must differ')


def make_trial_roles(a_table: str, b_table: str) -> TrialRoles:
    return TrialRoles(a_table, b_table)


def resolve_table_role(roles: TrialRoles, table_id: str) -> TableRole:
    require_label(table_id, 'table identifier')
    if table_id == roles.a_table:
        return TableRole.A
    if table_id == roles.b_table:
        return TableRole.B
    raise ValueError(f'table {table_id!r} is outside the trial')
