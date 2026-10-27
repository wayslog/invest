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

SPY 及 SPY/QQQ 合并关注列表使用 `invest funnel-capture` 和 `invest funnel`：官方成分股先经
流动性、趋势与相对强度初筛，再按固定的 0–100 分与风险、相关性规则聚焦最多五只。
逐股给出分项得分、理由及周际变化；关注名单保持非交易资格，详见
[每周两轮选股漏斗](docs/research/weekly-spy-funnel.md)。

少量已选股票可用 `invest trend-backtest` 检验预先登记的趋势规则，输出含成本回测与
独立空仓的模拟动作；`invest verify-trend-backtest` 重放全部结果。该研究不生成合格因子池，
选股后历史不当作样本外证据。详见[选中股票的含成本趋势研究](docs/research/selected-stock-cost-backtest.md)。

完整动态选股回测须逐周重建当时的 SPY/QQQ 成员，并将候选与现有持仓放入连续账户计算，
处理退市和公司行动，再按时间滚动验证。`invest weekly-backtest` 已接入历史成员准入、
逐周漏斗和两种落选策略的连续账户；`invest verify-weekly-backtest` 可重放冻结结果。
真实区间仍缺完整历史名单，稀疏交易历史、复杂公司行动和退市处置仍待实现；
当前仅完成合成行为验证，详见[周度动态回测规范](docs/research/weekly-dynamic-backtest.md)。

用户指定的固定当前 513 只股票实验已另行完成真实历史回放：股票池固定，每周仍重跑漏斗，
比较落选退出与持有至独立退出。该实验含当前名单的幸存者偏差，采用探索性数据口径，
不代表历史 ETF 成分回测或正式交易准入，见[固定当前股票池实验](docs/research/fixed-current-universe-backtest.md)。
扩展对照以 QQQ 买入持有为主基准，覆盖首期名单不调仓、仅进出场，以及 A/B 的每周、双周、
每月和每季度调仓；全部报告扣成本后的 QQQ 超额收益，不用较低回撤替代收益达标。

新研究与实盘统一使用本金阶梯风控和 W-8BEN 税后口径：净值低于 5,000 USD 本金时停止新开个股，
不高于一半本金时清仓终止；分红按 10% 协定税率预扣，价差不扣美国税。旧规则和已冻结结果保持不变，
详见[本金阶梯风控与 W-8BEN 税后口径](docs/research/principal-risk-and-tax.md)。

第 1 步长历史复核（2020-07 至 2025-06，本金阶梯与 10% 分红预扣）中，两个冻结的周度选股候选在两档成本、
四个平移起点下均未跑赢 QQQ，选股本身也低于同池随机抽样中位数；已按预登记门槛停止该个股方案，
见[第 1 步结果](docs/research/step1-principal-ladder-results.md)。

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
