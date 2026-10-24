# P3：统一策略与成本回测

日期：2026-10-24。P3 将 P2 冻结因子池接到共享决策与现金引擎，输出历史选股动作、
模拟成交和独立账务评价。所有结果仍为研究用途，`account_eligible=false`；
工程通过不表示策略赚钱，也不表示已经部署或验证真实 IBKR 执行。
状态：P3 本地离线验收通过。

## 运行

```bash
make quant-backtest-demo P3_DEMO_DIR=reports/my-new-p3-demo
uv run --locked --group research invest backtest \
  --config reports/my-new-p3-demo/backtest.toml --output reports/my-new-backtest
uv run --locked --group research invest verify-backtest --study reports/my-new-backtest
```

演示先运行 P2 的 18 个合成候选搜索，再使用冻结因子池在后续区间运行策略、现金、
同风险规则的等权参考组合和双倍成本情景，最后只读重放。目录必须不存在；重复实验使用新目录。
示例配置在演示目录生成，包含 `snapshot`、`factor_pool`、`start/end`、`known_through`、
`initial_cash`、`[execution]` 的稳定证券 ID 到原始行情路径映射，以及 `[policy]`。
日期使用 TOML 日期；金额、比率使用 Decimal 字符串；路径相对配置文件。

`factor_pool` 必须与原挖掘目录中的登记、完成记录、配置及产物摘要一致。
首个决策会话不能早于因子选择截止；回测开始前必须有一个完整决策会话。
记录中的已知历史截止取本次声明、原挖掘声明和选择截止的最大值。涉及已知区间时标记
`known_history`；其他区间仅标记 `declared_unseen_evaluated`，不自动获得样本外资格。
本次使用区间另存为 `consumed_through`，后续实验必须把已经查看的结果纳入 `known_through`。
不会通过回写原因子池或原挖掘登记来改变其历史状态。
推断另冻结截至回测末日的 `inference/` 快照；其准入只检查实际历史输入，完整原快照的
范围和缺口保存在 `source_scope/source_limitations`。回测结束后的缺口不改变本次排名或准入。

## 一套决策与账务

`strategies.decide(SignalFrame, AccountSnapshot, StrategyState, Policy)` 是纯函数，返回
`DecisionPlan`，不读取行情、不写账户、不发送券商订单。`backtest.simulate_signals` 在每个
收盘调用同一函数，再在后续会话模拟成交。保存的 `decision_contexts.parquet` 可以通过
`decision_io.read_decision_contexts` 恢复，重新决策必须与历史动作逐行相同。

| 模块 | 职责 |
| --- | --- |
| `signals.py` | 一次计算冻结表达式，逐会话独立准入和横截面排名，不使用未来标签 |
| `contracts.py`、`decision_io.py` | 信号、账户、持仓、待处理订单、持久策略状态、动作及精确状态快照 |
| `strategies.py`、`risk.py` | 排名选股、等权目标、预算、退出、风险锁定、冷却和调仓周期 |
| `backtest.py` | 单/多标的共享现金、成交时钟、成交量限制与保护性退出；复用原 Account 的 Decimal 会计 |
| `portfolio_audit.py` | 共用独立重建器，验证现金、持仓、分红、价格、费用与触发规则，按完整持仓周期计胜负 |
| `backtest_config.py`、`backtest_study.py` | 配置、输入冻结、情景比较、结果保存和只读重放 |

旧 `paper`、M2 和 forward 入口继续作为兼容与回归路径。P3 新主线不调用其中的旧选股决策，
也不把新策略参数套入原持续账户。旧趋势和轮动算法保留；重复入口清理与迁移仍属于 P4 及
另行授权的账户流程。

## 金融与时点规则

- 收盘动作仅在下一 XNYS 会话执行，日期和有效期使用真实开闭市时间。计划卖出先于计划买入；
  买入按排名、并列按证券 ID。整股、佣金和不利滑点使用 Decimal，共享现金不足时缩量或拒单。
- 策略支持固定止损、追踪止损、止盈、最大持有会话数、信号/股票池失效、账户回撤和再入场冷却。
  退出优先于选股；部分退出保留退出原因，不能因价格恢复立刻重新加仓。
  账户沿用原 80% 本金警示、50% 本金终止及配置回撤锁定规则，不自动恢复。
- 待处理买单占用现金和总敞口预算；待处理卖单不预支可用现金。暂停或持仓价格不可用时
  不新增风险。动作中的 `cancel_pending` 和 `exit_reason` 表达待取消与未完成退出需求，
  不把 `WAIT` 当作已经处置风险。暂停不消耗调仓周期。
- `exit_mode="close"` 在收盘确认退出，下一开盘执行；`protective` 先处理隔夜持仓跳空，
  再处理计划买入和日内保护。跳空按实际开盘价；同根日线同时越过止损、止盈时先算止损。
  追踪高点使用此前收盘经济价格，不用当天最高价追抬当天止损。新买入可在当天触发保护。
- `participation` 使用前一会话成交量乘当日拆股比例作流动性代理；同标的当日所有成交共用限额。
  当日成交量为零时不模拟成交，未成交余量取消，后续必须重新决策。该代理不声称真实盘口成交能力。
- `sale_proceeds="same_session"` 允许使用当日卖出净收入；`next_session` 冻结到下一交易会话。
  后者在释放后收盘才把资金纳入新动作，因此下一开盘买入还需再等一个会话；
  这是保守日线结算代理，不是完整券商结算与购买力模型。
- 企业行动在当日所有成交之前处理：正向整数拆股调整持仓和待执行数量；分红在除息日按原持仓
  登记应收，支付日入现金，卖出后应收仍在。退出使用含分红的经济价格；未平仓头寸期末按市价计值。
- `target_quantity` 是预算后的目标整股数，`target_weight` 是该目标按当前原价折算的权重。
  开盘变化仍可能缩量；动作不是成交承诺。动作 ID 绑定账户、截点、来源快照、因子池、参数和条件。

独立重建不调用 Account 或 `decide`。现金、净值、持仓、分红应收与收益归因必须一致，
成交同时核查下一会话、订单、价格、佣金、流动性限额和保护性触发。旧 buy-and-hold 语义下
的成本、分红与拆股轨迹，与原引擎逐项比较。

一次完整交易是从空仓开始，到该标的再次空仓结束，期间加减仓合并计算；收益包括费用和
已获得的分红权益。净收益大于零为胜，小于零为负，零为持平；未平仓不计胜率，但计入净值。
R 的分母为各次买入成交额乘固定止损比例的累计风险预算，禁用固定止损时 R 为空。
这是事前风险尺度，不保证实际止损损失，跳空可能超过 1R。

## 输入与输出

研究快照继续使用 P1 Parquet 契约；执行输入必须另有 `invest.bars.v1` 原始美元 OHLC、
整数股成交量、拆股比例和分红支付信息。原价研究与执行价格必须一致；调整价格研究必须
在执行元数据中显式绑定 `research_snapshot_id`，不能把研究浮点缓存转换成账本。
稳定证券 ID 与原股票代码映射来自快照股票池，冻结文件保留原代码和来源。
执行面板要求整个回测区间及前一个决策会话具有完整、相同的 XNYS 日历；不填补停牌、
退市或上市前缺失价格。不满足共同日历的真实股票池需要先补足有证据的估值与事件支持。

合成数据明确标记 synthetic。IBKR 原始执行输入还需声明 `volume_unit=shares`、
`corporate_actions=complete` 和非空 `source_ref`，这些声明必须由具备来源证据的规范化流程提供；
P3 不负责采集或外部核实这些证据。当前 IBKR 历史采集的复权数据、未知单位和缺少企业行动
不满足这一契约，不能靠补零分红或改 metadata 获得真实回测资格。历史参考源保持原来源，
不能替换 IBKR 执行输入。

| 产物 | 内容 |
| --- | --- |
| `registration.parquet`、`run.parquet` | 开始/完成或失败状态、原挖掘引用、已知历史、来源、依赖与引擎版本、限制 |
| `snapshot/`、`inference/`、`mining/`、`execution/`、`engine/` | 独立冻结完整来源、推断前缀、账务输入和源码；`config.toml`、可用时复制的 `uv.lock` 保存参数与依赖锁 |
| `signals.parquet`、`actions.parquet` | 每日排名及 BUY/ADD/TRIM/SELL/HOLD/WAIT，数量、价格、条件、有效期与原因 |
| `orders.parquet`、`fills.parquet`、`outcomes.parquet` | 市价/保护性意图、实际模拟成交、缩量与取消结果 |
| `positions.parquet`、`equity.parquet`、`events.parquet` | 共享现金、持仓、应收、净值及企业行动和风险事件 |
| `decision_contexts.parquet`、`final_context.parquet` | 每次决策前的账户/状态，以及结束时带待执行动作的状态 |
| `checks.parquet`、`attribution.parquet`、`round_trips.parquet` | 独立对账、收益归因、完整交易胜负及 R |
| `metrics.parquet`、`yearly.parquet` | 成本后收益、回撤、Sharpe、换手、暴露、胜率，以及同风险等权参考和双倍成本比较 |
| 情景前缀的 Parquet 表、`artifacts.parquet` | 各情景独立可审计的轨迹及全部冻结文件摘要 |

正式表均为 typed Parquet/Zstandard。账户现金使用六位 Decimal；可能为循环小数的均价、
分红摊薄锚点和高点，在结构化状态列里保留完整 Decimal 字面值，恢复时不经过浮点。
金额及参数的等值 Decimal 在动作 ID 中采用统一编码；`1000` 与 `1000.000000` 不会变成
不同动作。现金、报价和待处理订单参考价超出六位金额精度时直接拒绝，避免存储往返改变决策。
Qlib 原生缓存仍在隔离的 `data/cache/`，可删除重建，不写入历史账户或作为权威业务记录。
`verify-backtest` 校验完整文件集合、内容、配置、源码和依赖版本，然后在内存重跑所有情景。
源码变化后须使用保存的源码与相同依赖重放，不能拿新行为覆盖旧结果。

## 验收

验收日志位于 `reports/p3-validation-20261024/`。

| 检查 | 结果与证据 |
| --- | --- |
| `make check` | Ruff、格式、mypy 通过；449 项测试通过，覆盖率 87%，耗时 759.85 秒；`check-complete.log` |
| P3 核心回归 | 20 个用例覆盖共享决策、预算、退出、缺失报价、暂停、结算代理、部分成交、零成交量、分红拆股、精确持仓状态、Decimal 动作幂等、历史范围隔离与重放；`core-final-identity.log`，并纳入全套检查 |
| P3 全链路 | `reports/p3-accepted-20261024/`；18 个候选保留 1 个因子，516 条排名/动作，16 笔模拟成交、6 个完整周期；`quant-demo-accepted.log` |
| 独立账务及产物 | 四个情景的 7,702 条检查全通过；117 个冻结文件摘要、60 个 Parquet 文件的 Zstandard 压缩和 54 个源码文件校验通过；`artifact-accepted.parquet` |
| 冻结源码重放 | 通过 `PYTHONPATH` 从研究目录中的源码包启动，设置 `PYTHONDONTWRITEBYTECODE=1` 保持目录不变，全部结果重放一致；`frozen-replay-accepted.log` |
| M1 演示 | 新目录 `reports/p3-paper-accepted-20261024/`；`paper-demo-accepted.log` |
| 旧研究重放 | 新目录 `reports/p3-legacy-accepted-20261024/`，69 次运行重放一致；`research-demo-accepted.log` |
| 历史保护 | 重构前记录的 1,525 个数据及研究文件摘要全部不变；`history-before.parquet`、`history-preservation.parquet` |
| `make build` | wheel 和 sdist 构建通过；版本仍为 0.7.1，不表示发布；最终构建及包内源码校验见 `build.log`、`build-verification.parquet` |

早先的 `check.log` 因合成演示发现 R 风险预算精度问题而主动中断，只有 109 项通过，
不作为全套检查证据。`reports/p3-demo-20261024/` 保留失败登记及输入，问题已通过
`risk-precision-red.log` 复现并由 `risk-precision-green.log` 验证修复：完整周期风险预算
在汇总后按金额精度量化，R 使用保存的同一分母。其他 `*-red.log` 与早期专项检查日志
也保留为开发证据，不能当作最终通过结果。
`check-final.log` 同样主动中断，用于补充 Decimal 往返的动作幂等回归；该问题由
`identity-red.log` 复现，修复后的 20 项核心回归见 `core-final-identity.log`。
最终全套检查使用 `check-complete.log`，最终源码摘要见 `validated-source-accepted.parquet`。

新代码当前不接券商，不更新部署，未重置或迁移任何历史账户。
P4 将接续 `invest decide` CLI、选股/动作可读报告和旧研究主入口清理。
