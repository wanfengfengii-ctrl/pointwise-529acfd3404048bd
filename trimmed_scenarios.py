from contextlib import closing
import json
from pathlib import Path
import sqlite3
import sys
from tempfile import TemporaryDirectory

from analysis.selection import LagRequest, analyze
from check_project import main as check_v1
from demo import report_result
from handoff.acceptance import accept
from handoff.freeze import freeze
from handoff.inbox import initialize_inbox
from handoff.issuer import encode_frozen_curve, initialize_issue_register
from ledger.observations import ObservationInput
from ledger.revisions import submit
from ledger.storage import initialize_revision_ledger
from reports.archive import initialize_report_archive
from reports.read import read
from trial.registry import initialize_trial_registry, register


MAIN_A = ((0, 2, 0),)
MAIN_B = ((0, 1, 0), (1, 2, 5))
ALT_B = ((0, 1, 3), (1, 2, 4))
GAP_A = ((0, 1, 0), (3, 4, 0))
GAP_B = ((0, 1, 5), (3, 4, 0))


def connect(path):
    db = sqlite3.connect(path, cached_statements=0)
    db.execute("PRAGMA foreign_keys=ON")
    return db


def setup(source, review):
    initialize_trial_registry(source)
    initialize_revision_ledger(source)
    initialize_issue_register(source)
    initialize_inbox(review)
    initialize_report_archive(review)


def readings(rows):
    return [ObservationInput(*row, "u") for row in rows]


def revisions(source, trial, a_rows, b_rows):
    register(source, trial, "meter-a", "meter-b", "u", "u", 1, "u", 1)
    a = submit(source, trial, "meter-a", None, readings(a_rows))
    b = submit(source, trial, "meter-b", None, readings(b_rows))
    return a, b


def result(score, *intervals):
    return {"status": "empty" if score is None else "ok", "minimum_mse": score,
            "intervals": [list(pair) for pair in intervals]}


def equal(actual, expected):
    if actual != expected:
        raise AssertionError(f"expected {expected!r}, received {actual!r}")


def reject(error, operation, *args):
    try:
        operation(*args)
    except error:
        return
    raise AssertionError(f"{operation.__name__} should raise {error.__name__}")


def run_v1():
    with closing(connect(":memory:")) as review:
        with closing(connect(":memory:")) as source:
            setup(source, review)
            a, b = revisions(source, "spikes", MAIN_A, MAIN_B)
            alt = submit(source, "spikes", "meter-b", b, readings(ALT_B))
            ap, bp, cp = [accept(review, encode_frozen_curve(freeze(source, r))) for r in (a, b, alt)]
        cases = [(bp, 0, result("25/2", ("0", "0"))),
                 (cp, 0, result("25/2", ("0", "0"))),
                 (bp, 1, result("0", ("1", "1")))]
        actual = []
        for piece, upper, expected in cases:
            report = read(review, analyze(review, LagRequest(ap, piece, 0, upper, 1)))
            actual.append(report_result(report))
            equal(actual[-1], expected)
        return actual


def observed_sign(review, sign):
    writes = set()
    operations = {sqlite3.SQLITE_INSERT: "INSERT", sqlite3.SQLITE_UPDATE: "UPDATE"}

    def observe(action, table, column, database, trigger):
        if action in operations and database == "main" and not table.startswith("sqlite_"):
            writes.add((operations[action], table))
        return sqlite3.SQLITE_OK

    review.set_authorizer(observe)
    try:
        return sign(), writes
    finally:
        review.set_authorizer(None)


def commit_failure(review, path, writes, retry):
    if not writes:
        raise AssertionError("no persistent report write observed")
    review.executescript("""
        CREATE TABLE trim_probe_gate(id INTEGER PRIMARY KEY);
        CREATE TABLE trim_probe_pending(ref INTEGER REFERENCES trim_probe_gate(id)
                                       DEFERRABLE INITIALLY DEFERRED);
    """)
    names = []
    for index, (operation, table) in enumerate(sorted(writes)):
        name = f"trim_probe_{index}"
        quoted = chr(34) + table.replace(chr(34), chr(34) * 2) + chr(34)
        review.execute(f"CREATE TRIGGER {name} AFTER {operation} ON {quoted} "
                       "BEGIN INSERT INTO trim_probe_pending VALUES (1); END")
        names.append(name)
    with closing(connect(path)) as observer:
        before = tuple(observer.iterdump())
        reject(sqlite3.IntegrityError, retry)
        equal(tuple(observer.iterdump()), before)
    equal(review.in_transaction, False)
    for name in names:
        review.execute(f"DROP TRIGGER {name}")
    return retry()


def run_v2(check_commit):
    from analysis.selection import analyze_trimmed
    from handoff.acceptance import accept_trimmed
    from handoff.freeze import freeze_trimmed
    from reports.read import export_trimmed, read_trimmed

    with TemporaryDirectory() as directory:
        root = Path(directory)
        source_path, review_path = root / "source.sqlite", root / "review.sqlite"
        offline_path = root / "offline.sqlite"
        with closing(connect(review_path)) as review:
            with closing(connect(source_path)) as source:
                setup(source, review)
                a, b = revisions(source, "spikes", MAIN_A, MAIN_B)
                alt = submit(source, "spikes", "meter-b", b, readings(ALT_B))
                ga, gb = revisions(source, "gaps", GAP_A, GAP_B)
                old_text = encode_frozen_curve(freeze(source, a))
                old_piece = accept(review, old_text)
                reject(ValueError, accept_trimmed, review, old_text)
                reject(ValueError, freeze_trimmed, source, b, a, 0, 1)
                encoded = freeze_trimmed(source, a, b, 0, 1)
                envelope = json.loads(encoded)
                reject(ValueError, accept_trimmed, review, json.dumps(dict(envelope, evidence=None)))
                full = accept_trimmed(review, encoded)
                equivalent = json.dumps(dict(envelope, lag_window_seconds=["0.0", "2/2"]), indent=2)
                equal(accept_trimmed(review, equivalent), full)
                different = dict(envelope, sources=[envelope["sources"][0],
                                 dict(envelope["sources"][1], revision_id=alt)])
                reject(ValueError, accept_trimmed, review, json.dumps(different))

                def deliver(left, right, lo, hi):
                    return accept_trimmed(review, freeze_trimmed(source, left, right, lo, hi))

                p0, p1 = deliver(a, b, 0, 0), deliver(a, alt, 0, 0)
                quarter = deliver(a, b, "1/4", "1/4")
                gaps = deliver(ga, gb, -3, 3)
            source_path.rename(offline_path)

            def sign(piece, budget, minimum):
                return analyze_trimmed(review, piece, budget, minimum)

            reject(ValueError, sign, old_piece, 0, 1)
            reject(ValueError, sign, full, -1, 1)
            reject(LookupError, sign, 9223372036854775807, 0, 1)
            report_id, writes = observed_sign(review, lambda: sign(full, "1/2", 1))
            before = read_trimmed(review, report_id)
            equal(before, {
                "version": 2, "report_id": report_id, "piece_id": full,
                "sources": envelope["sources"],
                "request": {"lag_window_seconds": ["0", "1"], "max_trim_seconds": "1/2",
                            "min_retained_seconds": "1"},
                "result": result("0", ("1/2", "1")),
            })
            if check_commit:
                cases = [(p0, 1, 1, result("0", ("0", "0"))),
                         (p1, 1, 1, result("9", ("0", "0"))),
                         (full, 0, 1, result("0", ("1", "1"))),
                         (full, "1/2", 3, result(None)),
                         (quarter, "1/2", 1, result("5", ("1/4", "1/4"))),
                         (gaps, "1/2", "1/2", result("0", ("-3", "-5/2"),
                                                  ("-1/2", "-1/2"), ("1/2", "1/2")))]
                for piece, budget, minimum, expected in cases:
                    equal(read_trimmed(review, sign(piece, budget, minimum))["result"], expected)
                retried = commit_failure(review, review_path, writes, lambda: sign(full, "1/3", 1))
                equal(read_trimmed(review, retried)["result"], result("0", ("2/3", "1")))
        with closing(connect(offline_path)) as source:
            submit(source, "spikes", "meter-b", b, readings(((0, 2, 9),)))
        with closing(connect(review_path)) as review:
            equal(read_trimmed(review, report_id), before)
            exported = json.loads(export_trimmed(review, report_id))
            equal(exported, before)
            return exported


def main():
    if len(sys.argv) != 2 or sys.argv[1] not in {"v1", "verify", "demo"}:
        raise SystemExit("usage: trimmed_scenarios.py {v1,verify,demo}")
    mode = sys.argv[1]
    if mode == "verify" and check_v1():
        return 1
    output = run_v1() if mode == "v1" else run_v2(check_commit=mode == "verify")
    print(json.dumps(output, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
