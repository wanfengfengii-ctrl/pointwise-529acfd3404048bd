import sqlite3

from trial.rationals import require_serial


def initialize_inbox(db: sqlite3.Connection) -> None:
    db.execute('''
        CREATE TABLE IF NOT EXISTS review_inbox (
            piece_id INTEGER PRIMARY KEY,
            payload TEXT NOT NULL
        )
    ''')


def store_accepted(db: sqlite3.Connection, piece_id: int, payload: str) -> int:
    require_serial(piece_id, 'piece number')
    db.execute('BEGIN IMMEDIATE')
    with db:
        current = db.execute('SELECT payload FROM review_inbox WHERE piece_id = ?', (piece_id,)).fetchone()
        if current is None:
            db.execute('INSERT INTO review_inbox(piece_id, payload) VALUES (?, ?)', (piece_id, payload))
        elif current[0] != payload:
            raise ValueError(f'conflicting contents for piece {piece_id}')
    return piece_id


def load_accepted(db: sqlite3.Connection, piece_id: int) -> str:
    require_serial(piece_id, 'piece number')
    row = db.execute('SELECT payload FROM review_inbox WHERE piece_id = ?', (piece_id,)).fetchone()
    if row is None:
        raise LookupError(f'unknown accepted piece: {piece_id}')
    return row[0]
