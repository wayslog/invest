# invest

个人美股量化研究框架：**因子挖掘 → 信号 → 策略 → 回测 → 选股与动作**。
直接复用 Qlib 和 Alphalens，使用 Python 3.12、uv、typed Parquet/Zstandard 与 Decimal 账户核算。
IBKR 提供券商事实与执行行情；Alpaca SIP 历史数据用于明确标记范围的离线研究与回测。
研究统一按 USD 计算；测试和演示使用明确标记的合成行情。

## 三个主入口

| 命令 | 用途 | 核心结果 |
| --- | --- | --- |
| `invest mine` | 有预算地产生、诊断、淘汰候选并冻结因子池 | 全部试验、Alphalens 诊断、因子池 |
| `invest backtest` | 用统一策略和共享现金回放冻结信号 | 动作、模拟成交、净值、独立对账、成本及参考组合 |
| `invest decide` | 用相同规则处理指定截点的只读账户状态 | 股票排名、因子贡献、买入/加仓/减仓/卖出/持有/等待建议 |

三个命令均使用 `--config` 和 `--output`；`decide` 必须另给 `--as-of YYYY-MM-DD`。
每次运行使用新目录，正式表保存为 Parquet，中文 `report.html` 展示结果和限制。
建议包含股数、止损止盈参考、最长持有会话数、下一会话生效与到期时刻。
它们不会改写持续账户、提交订单或自动恢复风险暂停状态。

## 完整离线演示

```bash
uv sync --locked --python 3.12 --group research
make quant-demo P4_DEMO_DIR=reports/my-new-quant-demo
```

演示完成因子挖掘、四情景成本回测、同日账户状态下的当前决策、逐行动作比较和只读重放。
打开以下报告：

- `reports/my-new-quant-demo/research/mining/study/report.html`：候选与因子池。
- `reports/my-new-quant-demo/research/backtest/report.html`：成本后收益、回撤、胜负、R、对账。
- `reports/my-new-quant-demo/decision/report.html`：排名、因子贡献与动作。

重新决策、只读重放和输入契约见 [P4 输出与清理](docs/research/p4-output.md)。
账户资金从调用方提供的 Decimal 快照读取，不从 Qlib 浮点缓存重建。
工程演示通过不代表策略赚钱；真实数据准入和独立策略评价仍需相应证据。
IBKR 历史采集导入、企业行动回执和观察状态只读导出见
[IBKR 输入接入](docs/research/p5-ibkr-input-contracts.md)。获准的 Alpaca 历史研究使用
`invest import-alpaca` 接入，SPY/XLF 的真实数据结果见
[P5 历史研究闭环](docs/research/p5-alpaca-pipeline.md)。无因子通过筛选时保留拒绝结果，
生成现金回测和 WAIT 建议，不强行挑选因子或修改原研究门槛。

## 保留历史与兼容入口

旧 M1、M2/R1 研究从默认主入口移到 `invest legacy …`，例如：

```bash
uv run --locked invest legacy --help
make demo DEMO_ACCOUNT=reports/my-new-paper-demo
make research-demo M2_DEMO_DIR=reports/my-new-legacy-study
```

旧趋势/轮动逻辑只服务兼容和回归，新研究统一使用 `strategies.decide` 与 `backtest`。
`forward-*`、独立 `invest-ibkr`、已部署账户和原冻结源码保持各自职责；本次不做部署或账户迁移。
原账户、注册、研究结果、失败记录与来源全部保留，详见 [历史工作流](docs/legacy-workflows.md)。

## 开发与资料

```bash
make check   # Ruff、格式、mypy、离线测试与覆盖率
make build   # wheel 与源码包
```

行情、账户和私有报告位于忽略的 `data/`、`reports/`；库原生缓存仅位于可重建的 `data/cache/`。
依赖版本由 `uv.lock` 锁定。旧账户源码指纹规则保持不变；新研究另记录金融行为版本，展示代码与其分开。

[重构方案](docs/quantitative-research-refactor.md) · [P1 数据](docs/research/p1-data.md) ·
[P2 因子挖掘](docs/research/p2-mining.md) · [P3 策略与回测](docs/research/p3-backtest.md) ·
[P4 输出](docs/research/p4-output.md) · [项目路线图](docs/roadmap.md) · [数据来源](docs/data-sources.md)
