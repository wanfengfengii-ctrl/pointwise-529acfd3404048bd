# 双表尖峰剔除交接

沿用 README.md 的试验登记、单位换算、修订及两个独立 SQLite 库。V1 仍按全共同有效时长核定。新增联合件在白班冻结，剔除额度与保留门槛由夜班关站后申报。新库结构由原初始化入口补建，旧库可重复初始化。

## Python 调用

| 入口 | 输入与结果 |
| --- | --- |
| `handoff.freeze.freeze_trimmed(source_db, a_revision_id, b_revision_id, lower, upper)` | 选取同试验、同报告单位的确切甲乙修订，固定有理闭滞后窗，返回已发行联合件的 JSON 文本。接受单点窗。甲乙修订按登记表位排序，改版后仍可指定旧修订。 |
| `handoff.acceptance.accept_trimmed(review_db, encoded)` | 校验联合件并保存其固定内容，返回正整数接纳号，取件内 `piece_id`。件号沿用同一发行站和复核库原件号域。等价重收保留首次接纳。 |
| `analysis.selection.analyze_trimmed(review_db, piece_id, max_trim_seconds, min_retained_seconds)` | 凭指定接纳号及申报参数核定并提交报告，返回正整数报告号。报告窗口来自该件。 |
| `reports.read.read_trimmed(review_db, report_id)` | 按号返回下述报告字典。 |
| `reports.read.export_trimmed(review_db, report_id)` | 返回报告 JSON 文本，解析值与 `read_trimmed` 一致。 |

数值参数沿用 README.md 的精确有理输入。剔除上限非负，最低保留时长严格为正。非法参数、错配、坏件、同号异文或将 V1 件用于新复核抛 `ValueError`。合法未知修订号、接纳号或报告号抛 `LookupError`。SQLite 写入异常沿用原传播和回滚口径。

## 交班与报告

联合件外层字段为下列五项。

- `version` 为整数 `2`。
- `piece_id` 为发行件号。
- `sources` 为按甲乙顺序排列的两个原来源对象，各自沿用 V1 `source` 的字段和校验口径。
- `lag_window_seconds` 为 `[lower, upper]`，两值以精确有理文本编码。
- `evidence` 为联合残差计量证据的 JSON 对象。实现须随交付说明其字段、值域和接纳时校验的证据不变量。证据须覆盖固定闭窗，含缺测或没有共同有效时间的情形。离线库凭件内信息核验结构、值域、来源一致性和所采用表示的完整性。

证据须支持窗口内任一实数滞后与任一合法的事后申请。原始观测行及任一单表曲线留站。JSON 空白、对象字段顺序及同一表示内的等值有理文本拼写不影响重投等价性。同号内容冲突拒收并保留首件。

滞后加到乙表的时间坐标。双方覆盖的时间才进入可取舍的有效时间。每个滞后允许剔除共同有效时间中的任意可分割部分，核定剔除总时长及实际保留时长。对保留时间求平方差积分并除以实际保留时长，再在这一闭窗内取全局最小值。输出完整最优集合，区间升序、相交或相接则合并，孤点两端相同。已测的零值参与计算，缺测没有权重。零额度使用相同窗口、源修订和时长门槛时，结果与 V1 一致。

报告字典的顶层字段为 `version`（整数 `2`）、`report_id`、`piece_id`、`sources`、`request` 和 `result`。`sources` 沿用实际接纳件中的两个来源。`request` 有 `lag_window_seconds`、`max_trim_seconds`、`min_retained_seconds`。`result` 有 `status`、`minimum_mse` 和 `intervals`。有解时 `status` 为 `ok`。无解时 `status` 为 `empty`、`minimum_mse` 为 `None`（JSON 中是 `null`）、`intervals` 为空列表。区间各为两元素列表。所有有理数按 V1 输出约定化为文本。报告读取及导出直接使用已提交的快照。

## 代表样例

甲表 `[0,2)` 为 0，乙表 `[0,1)` 为 0、`[1,2)` 为 5。在 `[0,1]` 秒窗内用剔除上限 `1/2`、保留门槛 `1`，结果为最低值 `0`、最优区间 `[["1/2","1"]]`。同件零额度只得孤点 `[1,1]`。门槛增至 3 时应签空。使用相同两源的单点窗 `[1/4,1/4]`、剔除上限 `1/2` 和保留门槛 `1`，应签最低值 `5`。

乙表另有修订，分别为 3 与 4，各一秒。两份乙修订在滞后 0 时的 V1 均方差均为 `25/2`。在单点窗 `[0,0]` 各准剔一秒且至少留一秒时，两张联合件分别签 `0` 与 `9`。

缺测样例中，甲表在 `[0,1)`、`[3,4)` 均读 0，乙表在相同位置分别读 5、0。窗口为 `[-3,3]`，剔除上限和保留门槛均为 `1/2`。结果为最低值 `0`，最优域为 `[-3,-5/2]` 及两个孤点 `-1/2`、`1/2`。

## 运行交接

初始 `.pointwise-runtime.json` 保持项目原有 V1 验收。`python3 -B trimmed_scenarios.py v1` 可运行本题样例的原口径对照。V2 接通后在运行清单中沿用版本 1、CLI 类型与空 `setup`，将 `verify` 和 `demo` 接到可执行参数数组。所附 `python3 -B trimmed_scenarios.py verify` 串联完整原回归及新业务核验，断言失败返回非零。`python3 -B trimmed_scenarios.py demo` 输出关站签发、更正及重开后领回的实际报告。核验程序使用上面的业务入口和外部结果。
