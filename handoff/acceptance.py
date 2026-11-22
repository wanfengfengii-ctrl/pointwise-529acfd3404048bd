import sqlite3

from handoff.inbox import load_accepted, store_accepted
from handoff.issuer import FrozenCurve, decode_frozen_curve, encode_frozen_curve


def accept(db: sqlite3.Connection, encoded: str) -> int:
    curve = decode_frozen_curve(encoded)
    return store_accepted(db, curve.piece_id, encode_frozen_curve(curve))


def read_accepted(db: sqlite3.Connection, piece_id: int) -> FrozenCurve:
    curve = decode_frozen_curve(load_accepted(db, piece_id))
    if curve.piece_id != piece_id:
        raise ValueError('accepted piece number does not match its content')
    return curve
