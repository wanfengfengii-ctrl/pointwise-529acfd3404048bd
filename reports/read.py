import sqlite3

from reports.archive import load_report_snapshot
from reports.issue import ReportSnapshot, decode_report_snapshot
from reports.render import render_report
from reports.trimmed import export_trimmed_report, read_trimmed_report


def read(db: sqlite3.Connection, report_id: int) -> ReportSnapshot:
    return decode_report_snapshot(load_report_snapshot(db, report_id))


def export_report(db: sqlite3.Connection, report_id: int) -> str:
    return render_report(report_id, read(db, report_id))


def read_trimmed(db: sqlite3.Connection, report_id: int) -> dict:
    return read_trimmed_report(db, report_id)


def export_trimmed(db: sqlite3.Connection, report_id: int) -> str:
    return export_trimmed_report(db, report_id)
