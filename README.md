# 澄溪计量试验室双表滞后复核 V1

需要 Python 3.11 和其标准库。项目使用两个独立 SQLite 库。

```text
python3 -B check_project.py
python3 -B demo.py
```

核验入口 `check_project.py` 由控制台物化时提供，运行 `tests` 包中的完整 unittest 套件。演示使用 `examples/shift-input.json` 中的试验单和原序记录。它在临时目录建库，关闭站内库后签发报告，重开复核库并通过报告号核对输出。手算预期在 `examples/shift-expected.json` 中。输出包括报告号、输入、结果及父件出处。

## 一天的工作

1. 班长按试验单登记批号、甲乙表号、两表原单位、换算倍率及共同报告单位。
2. 计量员按采集器记录顺序提交恒值段，领到首个修订号。
3. 计量员核对原序、原值、换算及有效时长。更正提交该版完整选段并注明父号，旧版仍可查。
4. 白班选定两个修订，分别冻结并交付 V1 件。
5. 夜班用独立库收件，按件号核对来源及曲线后关闭站内库。
6. 夜班指定有序甲乙件、闭滞后窗及最低共同有效时长，核定最优区间或明确空结果。
7. 报告和出处一并提交后返回报告号。提交失败时该请求可重试。
8. 复测员按号领取原报告，采用区间并核对当时的两个父件。

## Python 接口

调用方持有连接并负责关闭连接。写操作管理自身事务，使用无外层事务的连接。连接后可执行 `PRAGMA foreign_keys = ON`，以启用库内引用约束。源库依次调用 `trial.registry.initialize_trial_registry`、`ledger.storage.initialize_revision_ledger`、`handoff.issuer.initialize_issue_register`。复核库依次调用 `handoff.inbox.initialize_inbox`、`reports.archive.initialize_report_archive`。重复初始化只补建结构。

| 函数 | 调用与返回 |
| --- | --- |
| `trial.registry.register` | `register(db, trial_id, a_table, b_table, report_unit, a_unit, a_factor, b_unit, b_factor)` 返回 `TrialRegistration`。相同登记可重领，异参拒绝。 |
| `ledger.revisions.submit` | `submit(db, trial_id, table_id, parent_id, records)` 返回数值修订号。每条记录为 `ledger.observations.ObservationInput(start, end, value, unit)`。首版父号为 `None`，更正父号须为该表任一已存修订。 |
| `ledger.time_account.account` | `account(db, revision_id)` 返回 `TimeAccount`。`revision` 含父号、固定绑定和原序 `observations`，`covered_seconds` 为精确有效时长。 |
| `handoff.freeze.freeze` | `freeze(db, revision_id)` 返回带件号的 `FrozenCurve`。用 `handoff.issuer.encode_frozen_curve` 导出 V1 JSON 文本。 |
| `handoff.acceptance.accept` | `accept(review_db, encoded)` 返回已接纳件号。`read_accepted` 可按号领回该件，`handoff.evidence.iter_effective_spans` 给出时序有效段。 |
| `analysis.selection.analyze` | `analyze(review_db, LagRequest(a_piece_id, b_piece_id, lower, upper, min_seconds))` 提交并返回报告号。`LagRequest` 与 `analyze` 在同一模块。 |
| `reports.read.read` | `read(review_db, report_id)` 返回固定 `ReportSnapshot`。同模块的 `export_report` 给出带报告号、单位、两个有序父件、请求和结果的 JSON 文本。 |

精确输入接受 `int`、`Fraction`、十进制文本和分数文本。整数值的分母在输出中省略。倍率为正，换算值等于原值乘以倍率。原单位必须等于登记口径。有效区间为 `[start,end)`，允许相接。`account` 的秒数为各有效段长度之和。空记录集合法。批号、表号和单位为非空文本，修订号、件号及报告号为正 SQLite 整数。交班件号由本站发行库分配，复核库在自己的件号域内核验重收。

V1 外层字段为 `version`、`piece_id`、`source` 和 `evidence`。`source` 带批号、表号、角色、源修订号、统一单位和登记的两表号，角色须与登记表号相符。`evidence` 经曲线编解码器处理，对接者通过有效段接口兑现读值。V1 接纳比较规范化内容，JSON 空白、字段顺序与等值有理文本的拼写不改变件内容。来源一致性以件内字段及已收件内容为依据。

复核时乙表整体加滞后，`D` 为双方同时有效的时长，`E` 为该时域上的读值差平方积分。有效零参与，缺测无贡献。`D` 达到门槛时比较精确的 `E/D`，其单位为报告读值单位的平方。闭窗可只有一个点。并列范围以升序闭区间给出，相接分量合并，孤点的两端相同。明确空结果在 JSON 中表示为 `status: empty`、`minimum_mse: null`、`intervals: []`。

未知批号、修订号、件号、报告号使用 `LookupError`。非法登记、单位、区间、父号归属、件内容或复核参数使用 `ValueError`。SQLite 操作错误传播给调用方，未提交的写入回滚。按报告号领取和导出直接使用签发快照，后续更正不影响历史结果。
