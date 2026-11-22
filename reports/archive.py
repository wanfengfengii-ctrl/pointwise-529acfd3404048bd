import sqlite3

from trial.rationals import require_serial


def initialize_report_archive(db: sqlite3.Connection) -> None:
    db.execute('''
        CREATE TABLE IF NOT EXISTS review_reports (
            report_id INTEGER PRIMARY KEY,
            a_piece_id INTEGER NOT NULL REFERENCES review_inbox(piece_id),
            b_piece_id INTEGER NOT NULL REFERENCES review_inbox(piece_id),
            payload TEXT NOT NULL,
            CHECK (a_piece_id <> b_piece_id)
        )
    ''')
    db.execute('''
        CREATE TABLE IF NOT EXISTS trimmed_reports (
            report_id INTEGER PRIMARY KEY,
            piece_id INTEGER NOT NULL REFERENCES review_inbox(piece_id),
            payload TEXT NOT NULL
        )
    ''')


def append_report(db: sqlite3.Connection, a_piece_id: int, b_piece_id: int, payload: str) -> int:
    db.execute('BEGIN IMMEDIATE')
    with db:
        cursor = db.execute('''
            INSERT INTO review_reports(a_piece_id, b_piece_id, payload) VALUES (?, ?, ?)
        ''', (a_piece_id, b_piece_id, payload))
        return cursor.lastrowid


def load_report_snapshot(db: sqlite3.Connection, report_id: int) -> str:
    require_serial(report_id, 'report number')
    row = db.execute('SELECT payload FROM review_reports WHERE report_id = ?', (report_id,)).fetchone()
    if row is None:
        raise LookupError(f'unknown report: {report_id}')
    return row[0]


def append_trimmed_report(db: sqlite3.Connection, piece_id: int, payload: str) -> int:
    db.execute('BEGIN IMMEDIATE')
    with db:
        cursor = db.execute('''
            INSERT INTO trimmed_reports(piece_id, payload) VALUES (?, ?)
        ''', (piece_id, payload))
        return cursor.lastrowid


def load_trimmed_report(db: sqlite3.Connection, report_id: int) -> str:
    require_serial(report_id, 'report number')
    row = db.execute('SELECT payload FROM trimmed_reports WHERE report_id = ?', (report_id,)).fetchone()
    if row is None:
        raise LookupError(f'unknown report: {report_id}')
    return row[0]
