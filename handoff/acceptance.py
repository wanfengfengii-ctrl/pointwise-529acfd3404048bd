import sqlite3

from handoff.inbox import load_accepted, store_accepted
from handoff.issuer import FrozenCurve, decode_frozen_curve, encode_frozen_curve
from handoff.joint import JointPiece, decode_joint_piece, encode_joint_piece


def accept(db: sqlite3.Connection, encoded: str) -> int:
    curve = decode_frozen_curve(encoded)
    return store_accepted(db, curve.piece_id, encode_frozen_curve(curve))


def read_accepted(db: sqlite3.Connection, piece_id: int) -> FrozenCurve:
    curve = decode_frozen_curve(load_accepted(db, piece_id))
    if curve.piece_id != piece_id:
        raise ValueError('accepted piece number does not match its content')
    return curve


def accept_trimmed(db: sqlite3.Connection, encoded: str) -> int:
    piece = decode_joint_piece(encoded)
    return store_accepted(db, piece.piece_id, encode_joint_piece(piece))


def read_accepted_trimmed(db: sqlite3.Connection, piece_id: int) -> JointPiece:
    piece = decode_joint_piece(load_accepted(db, piece_id))
    if piece.piece_id != piece_id:
        raise ValueError('accepted piece number does not match its content')
    return piece
