# P5：Alpaca 历史研究与 SPY/XLF 闭环

日期：2026-10-26。研究统一使用 USD；本次接入获用户授权的 Alpaca 历史数据，保留
IBKR 的券商账户、订单、成交和费用职责。没有部署、下单或更新持续账户。

## 数据和公司行动

SPY/XLF 各有 1,459 根 raw SIP 日线，覆盖 2021-01-04 至 2026-10-23；各 23 笔现金
分红与发行方记录的金额、除息日和支付日一致。全区间 raw/split 四价和成交量一致，
与供应方未返回区间内拆股相符。具体证据见[只读验证](../access/alpaca-readonly-validation-20261026.md)
和[拆股及覆盖核查](../access/alpaca-corporate-action-coverage-20261026.md)。

NVDA 2024-06-10 的真实 10:1 拆股验证了新股/旧股比例和成交量调整方向；它只作验证
样本，不加入 SPY/XLF 策略池。调整价存在美分舍入，反推原价会损失精度，因此直接使用
raw 响应。样本中的 due-bill 及日期差异仍由旧适配器拒绝，不扩大当前支持范围。

公司行动标为 `bounded_research`：全类型请求完成分页、现金分红有发行方独立对账、
拆股因子有行情对照；不将这些证据写为所有事件及历史版本无条件完整。未知行动、缺失
支付日、发行方不一致、原价/股数对照不一致或分页中断均拒绝导入。币种缺失按项目 USD
约定处理，原始响应保持缺失状态。

## 统一接入与冻结

新增离线命令，输入为现有 `invest legacy fetch` 的完整批次、发行方原始表及拆股参考捕获：

```bash
uv run --locked --group research invest import-alpaca \
  --dataset SPY=data/alpaca/spy-batch \
  --dataset XLF=data/alpaca/xlf-batch \
  --issuer data/alpaca/issuer-source.parquet \
  --split-reference data/alpaca/split-reference.parquet \
  --output reports/new-alpaca-inputs --allow-exploratory
```

路径替换为实际捕获位置。`split-reference.parquet` 使用 `invest.alpaca.RAW_SCHEMA`，
保留 `adjustment=split`、`feed=sip` 的实际请求、完整响应字节和分页，`kind=split_reference`。
导入器逐页核验，不能用手填的调整因子或空表替代。

- `snapshot/`：统一 OHLCV、固定样本股票池和日历，可直接交给 Qlib/Alphalens。
- `execution/<symbol>.parquet`：Decimal 原价、原始股数、分红/支付日和已支持的拆股事件。
- `execution/<symbol>.evidence/`：原始批次、发行方表、拆股参考、覆盖表和文件清单。
- `coverage.parquet`：逐证券区间、记录数量和限制。原始及正式数据均为 Parquet/Zstandard。

来源始终为 `alpaca`，快照保持 `exploratory`、`available_at=null`；实际 `captured_at`
取自各行情页。未知历史发布时间不回填成收盘时刻，当前股票池不追认为历史成员库。
研究配置必须显式允许探索范围。既有账户、登记、失败结果和冻结数据均不修改。

成本筛选和回测冻结行情时同时复制 `.evidence/`，重放重新解析原始批次、对账和核验
覆盖；原始绝对路径只用于来源记录。当前决定继续使用同一个因子池、策略与回测状态。
本次上下文为 `backtest_simulation`，独立实验资金为 USD 5,000，不代表 IBKR 账户余额。

## 本次实验和实际结果

输出根目录：`reports/p5-alpaca-pipeline-20261026-0400/`。

| 项目 | 冻结设置或结果 |
| --- | --- |
| 训练 / 验证 | 2021-02-01—2023-12-29 / 2024-01-02—2025-12-31 |
| 回测 | 2026-01-02—2026-10-23，204 个会话 |
| 已知历史截止 | 2026-10-23；保留 `known_history_reserved` / `known_history` |
| 候选 | 6 类量价因子 × 5/10/20 会话窗口，共 18 个；固定种子 19 |
| 诊断 | 5 会话预测期、两个分位；原 IC 门槛、块符号检验与 18 重 Bonferroni 校正 |
| 筛选结果 | 0 个入选；4 个训练期弱、8 个验证期弱、6 个未通过多重检验 |
| 成本设置 | 每笔 1 USD、滑点 5 bps；仅为研究假设，不冒充 IBKR 实际费用 |
| 策略 | 最多选 1 个标的，80% 配置/单标的上限；每 5 会话再平衡 |
| 退出规则 | 8% 止损、12% 跟踪止损、20% 止盈、30 会话最长持有、5 会话冷却、15% 账户回撤限制 |
| 2026-10-23 输出 | SPY、XLF 均为 WAIT，原因 `no_selected_factors` |

没有候选通过统计筛选，所以没有候选进入成本筛选，也没有获得“成本后通过”的因子池。
原 `mine` 结果保留 `rejected`，命令退出码仍为 1。新的消费路径允许该已完成的空池生成
零分、零买入方向信号，随后跑现金回测并输出 WAIT；失败或未完成的挖掘仍不能使用。
空池沿用截点、来源及探索准入；同分时的代码排序不代表投资优先级。

| 回测情景 | 净收益 | 最大回撤 | 模拟成交 |
| --- | --- | --- | --- |
| 本轮筛选策略 | 0.00% | 0.00% | 0 |
| 相同风控规则的等权参考 | 1.87% | -7.18% | 33 |
| 现金 / 双倍成本策略 | 0.00% / 0.00% | 0.00% / 0.00% | 0 / 0 |

等权参考仍使用再平衡、退出和冷却规则，不是买入持有指数收益。其期末分红应收为
3.777668 USD，未提前记入现金。四个情景共有 10,109 项独立会计检查全部通过。
没有交易的策略胜率和 R 倍数为空，不把现金不亏损解读为发现了盈利策略。

`mining/report.html` 展示全部候选及拒绝原因；`backtest/report.html` 展示净值、费用和
参考情景；`decision/report.html` 展示两只 ETF 的排名和 WAIT 动作。冻结回测与当前动作
均已通过只读重放。完整历史时点版本、全市场退市股票池和真实券商动作仍不在本次验收范围。

冻结源码重放同样通过。重放时按既有约定禁止向冻结目录写 Python 字节码：

```bash
PYTHONDONTWRITEBYTECODE=1 \
PYTHONPATH=reports/p5-alpaca-pipeline-20261026-0400/backtest/engine \
  .venv/bin/python -m invest verify-backtest \
  --study reports/p5-alpaca-pipeline-20261026-0400/backtest
```

## 检查与保全

新增 14 项回归覆盖导入来源、未知时点、证据冻结、缺页、价格/量不一致、发行方差异、
禁止改标 complete，以及空池的现金回测、参考组合和 WAIT 输出。

| 验证 | 结果 |
| --- | --- |
| `make check` | 退出 0；563 项测试全部通过，867.27 秒；总覆盖率 88% |
| lint / 格式 / 类型 | 全部通过；169 个文件格式通过，108 个文件类型检查通过 |
| `make build` | sdist 和 wheel 构建成功 |
| `make demo` | 使用本次独立新目录，演示通过 |
| 当前代码及冻结源码重放 | 回测结果一致；当前动作只读重放一致 |
| 既有数据与研究保全 | 执行前记录的 12,691 个文件逐字节未变 |
| 检查输入保全 | 118 个代码、测试及构建配置文件与检查前摘要一致 |
| 产物清单 | 导入、挖掘、回测、动作和公司行动核查五组清单全部通过 |

`make-check-host.log` 为正常主机权限下的完整运行日志；`preservation.parquet`、
`checked-inputs.parquet` 和 `artifact-validation.parquet` 保存逐文件核验结果。
最终 `acceptance.parquet` 与根目录 `artifacts.parquet` 汇总并封存本次运行证据。

早期空池时点测试的断言修正、沙箱 sysctl 警告导致的 CLI stderr 失败及中断检查均保留。
没有删减该 CLI 断言；正常主机权限下原有三个 CLI 测试已通过。构建首次因沙箱 DNS
受限无法获取 hatchling，联网构建后成功；新目录 M1 演示已通过。
冻结源码首次重放因遗漏上述环境变量生成 34 个额外字节码文件而被清单检查拒绝；
这些文件移到本次运行的诊断目录后，全部原清单成员仍逐字节一致，重放通过。
失败日志、缓存清单和通过日志分别保留，没有重写研究产物或重新封存以绕过检查。
