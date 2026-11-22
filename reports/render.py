import json

from reports.issue import ReportSnapshot, encode_report_snapshot
from trial.rationals import require_serial


def render_report(report_id: int, report: ReportSnapshot) -> str:
    require_serial(report_id, 'report number')
    header = {
        'report_id': report_id,
        'trial_id': report.trial_id,
        'report_unit': report.report_unit,
        'mse_unit': f'{report.report_unit}^2',
    }
    return json.dumps({**header, **json.loads(encode_report_snapshot(report))}, ensure_ascii=False, indent=2)
