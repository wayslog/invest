# P2：因子挖掘与冻结信号

日期：2026-10-24。基于 P1 的 Parquet 快照、Qlib 0.9.7 和 Alphalens Reloaded 0.5.0。
状态：P2 本地离线验收通过，尚未部署。
本阶段提供有预算的因子搜索、开发段诊断、去冗余、冻结因子池和股票排名。
`selected` 表示通过本次开发筛选；所有产物均为 `research_only`、`account_eligible=false`。
成本后组合回测、仓位、止损止盈和买卖动作由 P3 接续；P2 不宣称盈利或样本外有效。

## 使用

```bash
uv sync --locked --python 3.12 --group research
make quant-mine-demo P2_DEMO_DIR=reports/p2-mining-example
```

演示构造 12 个 `SYNTH` 标的，覆盖六类模板、三个窗口，共 18 个候选。
它只使用合成数据和本地库。目录必须尚不存在；改变参数或重复实验使用新目录。
高 IC 来自构造的样本，不能作为真实选股依据。

自己的数据先按 [P1 接入说明](p1-data.md)生成权威快照，再复制并修改
[`configs/quant-mine.toml`](../../configs/quant-mine.toml)：

```bash
uv run --locked --group research invest mine \
  --config configs/quant-mine.toml --output reports/my-new-study
```

`snapshot` 相对于配置文件解析；日期必须是 TOML 日期和 XNYS 会话边界。
训练、验证、测试区间依次排列且不能重叠。`known_through` 必须如实登记已知历史。
stdout 是 JSON 摘要，库的诊断信息写入 stderr；退出码 0 表示有入选候选，1 表示全部淘汰，
2 表示输入或文件错误。全部淘汰仍保存完整研究结果，不应自动放宽门槛重试。

## 研究规则

1. 冻结配置原文、来源快照 ID、源码摘要、依赖版本、已知历史、测试区间和全部候选清单。
   配置未填写的参数使用当前源码中的默认值；复现时必须使用登记的源码与依赖。
   保存的配置保持原文，相对路径仍以原配置目录为基准；搬移配置时需显式修正快照路径，
   重新登记实验，不能覆盖旧目录。
2. 用固定种子排列模板与窗口的组合，最多尝试 `candidate_budget` 个候选。
   支持趋势、反转、收益波动、成交量变化、区间位置、量价相关；限制窗口集合、AST 深度和
   节点数，并复用 P1 的因果表达式校验。超出复杂度的候选也占预算并记录拒绝原因。
3. 只将截至验证结束的行情及对应历史成员区间复制为新的开发快照。
   原快照校验完整性；质量准入和结果范围按开发快照重新判定，测试段的未知可用时间
   不影响开发选择。登记、完成记录和冻结池另存原快照的 `source_scope`、
   `source_limitations`，不修改原记录。不把测试段行情送入 Qlib 或标签计算。Qlib 缓存仍位于
   `data/cache/qlib/`，由开发快照及库版本隔离；不成为第二套权威数据。
4. 标签是 t 收盘后，t+1 开盘至 t+1+H 开盘的价格收益比例。
   每段尾部 H+1 个决策会话剔除，保证标签入场、退出都落在该段。
   入场和退出价格的 `available_at` 都不得晚于本段末实际收盘；训练段使用训练截止时间，
   验证段使用验证截止时间。事件发生时间不能替代价格可用时间。晚到标签保留空值，
   未知时点只有显式探索模式才能使用。Qlib、Alphalens、组合增量筛选共用准入后的标签。
   边界剔除、因子时点拒绝、标签时点拒绝及其他丢样分别记录；标签表保留两段截止时间。
5. Alphalens 输出逐日 RankIC、分组 H 会话价格收益及标准误、相邻会话分组换手与排名
   自相关。跨缺失日不直接计算“一日”滞后。年度 IC 和筛选均使用从段首锚定、每 H 会话
   取一次的非重叠标签样本；这些样本仍可能相关，不宣称统计独立或显著性。
6. 训练段平均 IC 确定方向；验证段不能重新翻转方向。训练绝对 IC、按训练方向解释的
   验证 IC、有效会话数量与清洗后覆盖率必须达标。
7. 依固定生成顺序贪心纳入候选：训练段截面排名的绝对相关系数达到门槛则去重；验证段
   在同一批完整观测上比较原等权组合与加入候选后的 RankIC，增量不足则拒绝。
   首个候选相对于零 IC 基线比较；超过池容量仍记录后续候选的结果。
8. 冻结入选因子的定义、训练方向和等权权重，并在验证结束日生成一次研究排名。
   筛选会使用验证反馈，因此该排名是开发截点的研究产物，不是当时已发布的交易建议。

默认门槛见配置模板。`min_sessions` 是非重叠标签采样后的有效 IC 会话数；
`min_coverage` 是边界剔除后进入 Alphalens 的行中最终保留的比例。
trial 和 diagnostics 的单因子 IC 保持原始表达式方向，结合 `direction` 解释；
`incremental_ic` 使用训练确定的方向。分组收益没有扣除费用，也不是账户收益。

测试段仅登记为 `reserved_unassessed`；若与 `known_through` 重叠，则记为
`known_history_reserved`。两者都不表示已经完成独立验证。更换路径、快照 ID 或重新下载
不能把已知历史变回样本外；用户过去观察过的数据仍须如实登记。

## 输出与接口

所有表为有类型的 Parquet，压缩方式为 Zstandard。主要产物如下：

| 产物 | 内容 |
| --- | --- |
| `config.toml`、`registration.parquet` | 原始配置、搜索登记、来源、版本、已知历史与限制 |
| `candidates.parquet` | 搜索开始前冻结的表达式、族、顺序和复杂度 |
| `development/` | 只含开发数据的不可覆盖快照，保留原来源和价格/成交量口径 |
| `trials.parquet/` | 每次尝试一个不可覆盖分片；状态、拒绝原因、错误、方向、覆盖、IC、相关及增量 |
| `factors.parquet`、`labels.parquet` | 开发因子长表和分别剔除边界后的训练/验证标签 |
| `diagnostics.parquet` | 因子、分段、指标、日期、分组、数值组成的诊断长表 |
| `factor_pool.parquet` | 冻结因子池、权重、选择截点、来源和内容身份 |
| `signals.parquet` | 验证结束日的股票评分、排名、偏好方向、期限和有效期 |
| `run.parquet`、`artifacts.parquet` | 完成状态、限制和产物摘要清单 |

`pyarrow.parquet.read_table(".../trials.parquet")` 可直接读取所有尝试。
预算内全部失败时，完成状态为 `rejected`，因子池与信号表为空；不会回退到固定股票。
有入选因子但信号日没有有效成员时，正常保存有类型、来源和范围元数据的空信号表，
完成记录仍保留因子入选结果；因子入选不保证当天存在可输出的股票。
运行异常保留登记、候选和已开始尝试的错误记录，不写完成记录；不要把残留目录当成成功结果。

公开接口是 `run_mining(config_path, output)`、`load_factor_pool(path)` 和
`generate_signals(pool, snapshot, as_of)`，分别位于 `factor_mining.py` 和 `signals.py`。
`SignalFrame` 在 `contracts.py` 中定义。后续接入新快照生成排名时，不需要未来收益标签：

```python
from pathlib import Path
from invest.research_data import load_snapshot
from invest.signals import generate_signals, load_factor_pool

pool = load_factor_pool(Path("reports/my-new-study/factor_pool.parquet"))
snapshot = load_snapshot(Path("data/research/new-snapshot"))
signals = generate_signals(pool, snapshot, max(snapshot.calendar["date"].to_pylist()))
```

推断数据必须保持来源、价格调整口径、成交量单位和币种一致，不能早于选择截点。
冻结池内容变化会拒绝加载。空池不能生成信号。每个因子在当天可用横截面中将平均秩缩放
到 [-1, 1]，乘训练方向后等权合成；缺少任一入选因子的证券不输出，不填补未知数值。
仅有一个有效因子值时，只将该值的秩置为零，其余缺失值继续保持缺失。
分数并列时按稳定证券 ID 排序。`direction=1` 表示正向偏好，`0` 表示没有正向偏好；
它们不代表买单或卖单。有效期从当天实际收盘至下一会话实际收盘，H 是标签预测期限，
不是订单有效期。缺失数据的股票数量保存在信号表元数据中。

Qlib、Alphalens 与推断共用 P1 收盘准入规则：已知晚于收盘的数据始终剔除；未知时点或
历史参考源需要 `allow_exploratory=true`。接受探索数据后，诊断、尝试、冻结池和信号保留
`input_scope`、`scope` 及原 `source`，不重标原始快照，也不将 Alpaca 记录当成 IBKR。

## 当前边界与验收

P2 使用已有 OHLCV 契约，没有引入行业、基本面或标准风险暴露数据。因此行业稳定性与
风险暴露去重尚不具备证据；当前实现的是表达式约束、数值去冗余与固定组合的预测增量。
没有多重检验校正或成本后收益门槛；搜索预算和全部试验保留，方便 P3 独立验证和复核。
真实数据的历史成员、退市和企业行动缺口继续受 P1 限制，不能因计算成功取得账务资格。

验收包含真实 Qlib/Alphalens 离线回归：标签边界、未来追加不改变过去信号、修改测试段
不改变开发选择、训练方向冻结、全部失败、复杂度预算、未知时点及来源保留、缺失日滞后、
冻结池改动拒绝、收盘后数据拒绝，以及断网 CLI 和运行异常留档。

2026-10-24 本地验收结果：

| 检查 | 结果与证据 |
| --- | --- |
| `make check` | Ruff、格式、mypy 通过；418 项测试通过，覆盖率 87%；`reports/p2-validation-20261024/check-final.log` |
| P1/P2 专项回归 | 55 项通过；`reports/p2-validation-20261024/focused-final.log` |
| `make quant-mine-demo` | 新目录 `reports/p2-demo-final-20261024/`；18 个候选保留 1 个，输出 12 个合成标的排名 |
| 全部尝试 | 8 个因数值相关淘汰，4 个证据不足，3 个无组合 IC 增量，2 个验证 IC 不足；失败记录均保存 |
| 时间隔离与存储 | 因子、标签退出不超过 2022-10-31；测试从 2022-11-01 起保留未评价；31 个产物摘要及 Parquet 压缩验证通过 |
| `make demo` | 使用新账户目录 `reports/p2-paper-20261024/`，离线 paper 演示通过 |
| `make research-demo` | 使用新目录 `reports/p2-legacy-research-20261024/`，原研究的 69 次运行重放一致 |
| `make build` | wheel 和 sdist 构建通过；仍为当前项目版本 0.7.1，不表示发布或部署 |
| 历史保护 | 重构前记录的 `data/`、`reports/` 内 526 个文件摘要均未变化；证据为 `reports/p2-validation-20261024/history-preservation.parquet` |

验收日志集中在 `reports/p2-validation-20261024/`。早先的 `check-verified.log` 因补齐
探索范围元数据而主动中断，不作为通过证据；最终以 `check-final.log` 为准。
旧账户、研究身份、来源、冻结输入、资金与风险历史均保留。没有重置持续账户或改变部署。

## P2 审阅修复（2026-10-24）

本次修复四类缺陷，新增 11 个回归用例；四类缺陷均保留了修复前失败和修复后通过的日志。

| 缺陷 | 修复与回归 |
| --- | --- |
| 单个有效因子值将其他证券的缺失值变成零 | 只对非空的单个有效值置零；八只证券中仅一只完整时，仅输出该证券 |
| 标签事件落在开发段，但价格晚于选择截点才可用 | 同时检查入场、退出价格的实际可用时间；不可用标签保留空值，修改其价格不改变筛选；覆盖截止前、恰好截止、晚一秒及未知时点 |
| 测试段质量影响开发准入 | 复用快照校验器校验开发切片；测试段改为未知时点时开发结果保持一致，原始来源范围和限制单独留档 |
| 信号日没有历史成员时抛出 `KeyError` | 按冻结池声明的因子列构造空视图，保存完整元数据的空信号及完成记录 |

标签列契约保持不变，新的时点准入、截止时间和丢样数量记录在 Parquet 元数据及诊断表中。
新规则用于新建研究运行；既有标签、因子池及其他历史结果不回写、不重新标记。
修复与验证证据放在 `reports/p2-review-fix-20261024/`；`*-red.log` 是有意保留的失败复现，
不作为通过证据。

本次完整验收结果如下，早先的 418 项验收记录仍保留为原始实施证据。

| 检查 | 结果与证据 |
| --- | --- |
| `make check` | Ruff、格式、mypy 通过；429 项测试通过，覆盖率 87%，耗时 740.88 秒；`check.log` |
| 修复回归 | 新增 11 个用例；全套检查包含 31 项 P2 与 35 项 P1 回归；四类失败复现及通过日志均保留 |
| P2 离线演示 | 新目录 `reports/p2-fixed-mining-20261024/`；18 个候选保留 1 个，输出 12 个合成标的排名；`mining-demo.log` |
| 标签与产物 | 两段标签截止时间、来源和 31 个产物摘要及 Zstandard 压缩校验通过；`artifact-verification.parquet` |
| M1 离线演示 | 新目录 `reports/p2-fixed-paper-20261024/`；`paper-demo.log` |
| 构建 | wheel 和 sdist 成功，wheel 中 50 个 Python 源文件与工作区一致，演示引擎摘要一致；`build.log`、`build-verification.parquet` |
| 历史保护 | 修复前记录的 1,452 个数据及研究文件摘要全部不变，包含原账户与此前 P2 研究产物；`history-before.parquet`、`history-preservation.parquet` |

以上日志和校验表均位于本节的验证目录。本次没有操作部署账户或重置资金、风险状态。
