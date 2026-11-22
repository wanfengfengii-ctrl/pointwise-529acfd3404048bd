import sqlite3

from reports.archive import load_report_snapshot
from reports.issue import ReportSnapshot, decode_report_snapshot
from reports.render import render_report


def read(db: sqlite3.Connection, report_id: int) -> ReportSnapshot:
    return decode_report_snapshot(load_report_snapshot(db, report_id))


def export_report(db: sqlite3.Connection, report_id: int) -> str:
    return render_report(report_id, read(db, report_id))
