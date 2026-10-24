# 因子筛选与 IBKR 只读账户上下文

日期：2026-10-24。补齐 P2 的多重检验处理、成本后筛选，以及 P4 的账户适配。
仍使用 `mine → backtest → decide` 三个入口；不迁移持续账户，不发出券商订单。

## 1. 因子搜索的统计门槛

新增的挖掘配置默认启用以下统计检验：

```toml
test_alpha = 0.05
test_block_size = 2
test_resamples = 19999
test_family_size = 0
```

- 方向只由训练段确定。验证段仍使用 H 会话间隔的非重叠 RankIC；先按原始时间网格
  分块，再调用 SciPy 单侧符号置换检验。块大小单位为非重叠 IC 样本数，默认覆盖约 2H 会话。
  缺失样本不压缩时间，也不改变块边界。
- 小样本枚举全部符号组合；较大样本使用固定种子的 Monte Carlo，采用 SciPy 的加一
  计数规则，不输出随机抽样得到的零 p 值。块不足或非正证据返回 p=1。
- Bonferroni 校正使用预先声明的完整搜索族，不以通过 IC、相关性或成本门槛的数量作分母。
  `test_family_size=0` 表示使用 `candidate_budget`；也可预先声明更大的相关研究总预算。
  复杂度失败、弱因子与冗余候选不会缩小预算。校正后 p 值超过 `test_alpha` 即淘汰。
- 所有检验依赖零假设下块符号对称、块间可独立翻转的假设；分块不证明真实市场独立。
  本方法不自动校正未登记的跨实验搜索，也不为验证段反复选择的最终组合授予样本外资格。

`trials.parquet/` 保存原始与校正 p 值、块数、搜索族大小及拒绝原因。
失败与未通过计算的候选继续保留；不会重写以前的试验。

## 2. 成本后组合筛选

在原挖掘 TOML 追加：

```toml
[cost_screen]
initial_cash = "5000"
min_return = 0.0
min_excess_return = 0.0
max_drawdown = 0.15
min_fills = 2

[cost_screen.execution]
IBKR123 = "execution/IBKR123.parquet"
IBKR456 = "execution/IBKR456.parquet"

[cost_screen.policy]
top_k = 2
allocation = "0.8"
position_cap = "0.4"
commission = "1"
slippage_bps = "5"
```

股票 ID 和文件路径替换成已核验的输入。`policy` 支持与正式回测相同的退出、冷却、
结算和参与率配置；挖掘和成本筛选必须使用相同的探索准入设置。

筛选发生在统计、相关性及预测增量检查之后。每次检查“已选因子 + 当前候选”的等权组合，
复用 `simulate_signals` 和独立审计，使用整股、共享现金、次会话成交、费用、滑点、
分红、拆股和相同退出规则。只将验证段及其前一个决策会话的成交数据交给组合引擎，信号回看使用开发快照。
这属于开发选择；封存测试段不会参与筛选。

每个候选组合运行策略、完整可用股票池的等权参考、双倍费用及滑点三个情景。
策略与成本压力情景均须有足够成交、净收益严格大于 `min_return`、回撤不超过上限，
正常成本下相对等权超额须不低于 `min_excess_return`。全部不合格时返回空池。
任一情景的独立审计出现 `error` 时，先保存该情景的成交、净值和审计表，再终止研究，
记录当前试验错误，不生成已选池或完成记录；收益达标不能覆盖审计失败。

冻结池绑定筛选策略和初始实验资金，后续 `backtest` 必须使用同一组参数和本金。
改变策略或资金规模需要重新做开发筛选；不能沿用旧成本通过结论。

执行数据复用 P3 准入：真实 IBKR 输入必须有原价、整股成交量和完整企业行动来源。
不从 Qlib 缓存反推账目，不替真实采集补零分红。未提供 `cost_screen` 时仍可做因子诊断，
但结果明确保留 `cost_and_portfolio_validation_pending`，池中 `cost_screen=not_evaluated`。

`execution/` 冻结实际使用的验证段输入；`cost_screen/trial_NNNN/` 保存候选池、信号、
三个情景的动作、订单、成交、净值、持仓、事件、完整交易、独立检查和指标。
正式表均为 typed Parquet/Zstandard，HTML 同时展示校正 p 值、成本状态和净收益。
`make quant-demo P4_DEMO_DIR=reports/<new-name>` 已包含统计与成本筛选，行情始终标记为合成。

## 3. IBKR 只读账户适配

`decide.toml` 增加可选的 `broker_capture`：

```toml
strategy = "research/backtest"
snapshot = "research/current-raw-snapshot"
context = "account-export/state.parquet"
broker_capture = "captures/current-batch"
known_through = 2026-10-23
```

`broker_capture` 使用现有独立 IBKR SDK 生成的完整采集目录。`context` 是同一会话的
持久账户和策略状态导出，采用 `decision_io.CONTEXT_SCHEMA`，metadata 必须包含：

- `context_kind=account_state`、`broker_account`、`environment=paper`；
- 冻结策略对应的 `policy_id`、`pool_id`，`price_basis=raw`；
- 指向权威账户历史的非空 `source_ref`。

该状态由账户的权威记录提供，不能将 `proposed_context` 预览或历史回测状态改名后当作
真实账户导出。本适配器核对导出的资金事实并保留策略历史，不创建初始本金、推断持仓
入场时间、重置净值高点、消除冷却或解除风险暂停；券商本身不提供这些策略状态。

适配器读取冻结文件，不连接网络或写入账户。具体核对：

1. 采集 schema、真实/合成来源、Paper 账户身份、完成状态、全部表的来源一致。
   原始请求必须包含完整账户、持仓、全部未完成委托和成交查询，完成时间位于当日收盘至
   下一开盘之间；查询失败、过期以及收盘后改变账户的成交直接拒绝。
2. USD `TotalCashValue`、`SettledCash`、`AccruedDividend` 必须存在并与状态完全相符。
   未结算现金为前两者之差；分红应收不能用净利息 `AccruedCash` 替代。
   不使用保证金购买力；负现金、外币非零余额和缺失证据均拒绝。
3. 用合约 conId 对应稳定 ID `IBKR<conId>`，核对股票类型、币种、代码、整股数量和成本。
   当前只支持美元普通股票/ETF、整股多头；不省略股票池外的持仓或未完成订单。
   IBKR `avgCost` 为浮点均价，与持久成本比较时允许最多每股 `0.000001 USD` 的绝对误差；
   不使用相对容差，不接受非正成本，不按股数扩大容差。账户继续使用原始完整 Decimal
   成本，不将券商浮点均价写回账本；现金、股数和待单核对仍要求精确一致。
4. 待单按尚未成交数量核对。`PendingCancel` 仍保留占用；只有确认终态才不计入待单。
   不明状态、市价单缺少可靠预算、重复或同证券多单等当前契约无法表达的情形明确拒绝。
   先验证订单身份和终态，`Filled` 的剩余数量必须为零；已确认的历史终态订单不要求其
   合约继续出现在当前证券表中。历史订单证据仍整批冻结，未完成订单继续做完整合约核对。
5. 持久状态必须覆盖当天，入场时间、高点、退出原因、风险状态和冷却记录完整。
   原价报价从同来源研究快照读取，随后仍经过 P4 的收盘可用时间准入。

输出保留账户 ID、本金及风险状态。`decide` 冻结原状态和整批券商证据，记录
`broker_capture_id`，在冻结完成及重放时重新核对；不将填写 metadata 当作券商证明。
登记中的账户 ID、来源引用和冻结后的实际输入必须一致；读取期间换入另一份账户导出会失败，
重新封存清单也不能使错误的来源引用通过重放。
`effective_context.parquet` 是已核对的输入视图，`proposed_context.parquet` 仍只是预览。
运行限制保留“券商采集已核对、策略历史来自提供的权威状态”；非原子券商查询不会变成原子快照。

已有现金观察的项目 USD 5,000 不会映射成券商 Paper 默认余额。旧观察、研究登记、
失败结论和样本外窗口不修改。没有相符的真实账户导出与原价快照时，本阶段只证明适配代码
和离线边界，不声称完成外部账户验收。所有结果仍为 `account_eligible=false`。

## 4. 方法依据与验收

- [SciPy 符号置换、精确枚举和随机 p 值](https://docs.scipy.org/doc/scipy/reference/generated/scipy.stats.permutation_test.html)。
- [NIST Bonferroni 多重比较](https://itl.nist.gov/div898/handbook/prc/section4/prc473.htm)。
- [IBKR 账户字段](https://www.interactivebrokers.com/docs/tws-api/doc/account-portfolio-data/account-updates/account-value-keys)。
- [IBKR 持仓回调和浮点均价](https://interactivebrokers.github.io/tws-api/positions.html)。

审阅修复前的实现证据位于 `reports/research-gaps-validation-20261024/`，作为历史验收保留。
该版本业务源码摘要为 `5615b23438b287649e07973fcd85b5c0d89ae08eb6018cd93ad2b2e7a34dab92`，
金融行为摘要为 `05954d64c8eb76c19b37071983de8c002c750f7397da93860783ef8ab470c474`。

| 验收 | 结果与证据 |
| --- | --- |
| 全套检查 | Ruff、格式和 mypy 通过；516 项测试全部通过，含新增 31 项回归，872.34 秒，覆盖率 87%；`check-final.log` |
| 统计与成本闭环 | `research-gaps-final-20261024`：18 个候选保留 1 个，校正 p 值 0.017578125，正常与双倍成本筛选通过；`quant-demo-final.log` |
| 独立对账 | 开发成本筛选三个情景 14,536 项，测试回测四个情景 7,702 项，全部通过；`artifact-accepted.parquet` |
| 当前动作一致性 | 12 条当前动作与同日回测逐字段一致，包含动作 ID；240 个 Parquet 文件均使用 Zstandard |
| 账户桥接 | `research-gaps-broker-final-20261024`：合成 IBKR 采集和持久状态生成 8 条动作，重放通过，12 个输入文件未变；`broker-demo-final.log` |
| 新版冻结源码 | 从最终结果的 `engine/` 加载，回测、当前动作与账户桥接三份结果均重放通过；`frozen-accepted.log` |
| 历史重放 | 使用上一版冻结源码重放原回测和当前决策通过；`previous-frozen-replay.log` |
| 旧引擎兼容 | 全新目录 M1 演示通过；前向演练 106 项对账通过；`paper-demo-final.log`、`forward-demo-final.log` |
| 历史保护 | 本轮变更前登记的 8,478 个历史数据与研究文件摘要未变；`history-before.parquet`、`artifact-accepted.parquet` |
| 包构建 | wheel 与源码包构建通过；63 个包源码及 116 个检查输入和文档逐字节匹配；`build-final.log`、`package-final.parquet` |

`quant-demo.log` 保留原合成样例被拒绝的结果：8 个时间块、18 个候选使最强因子的校正
p 值为 0.0703125，不能达到默认 0.05。新的合成样例把验证段扩展至 2022-06-01 开始，
没有降低门槛或修改真实研究窗口。原拒绝输出保持不变。
`check.log` 是补齐冻结一致性检查前主动中断的早期检查，251 项已通过，不作为最终验收。
最终检查使用 `accepted-inputs.parquet` 中冻结的 112 个源码、测试、示例及检查配置文件；
`check-final.log` 启动后这些输入保持不变。早期成功演示与失败输出均保留。
首次辅助产物核查将 `trials.parquet/` 目录误作单文件，失败日志保留于 `artifact-checks.log`；
修正核查脚本后的结果见 `artifact-checks-final.log`，业务产物没有因此改写。

本地没有进行真实券商联调；合成采集不计为真实账户验收或获利证据。

## 5. 审阅修复

本次修复只涉及成本筛选的审计准入和 IBKR 只读上下文的两处兼容性边界：

- 策略、等权参考或双倍成本任一情景审计失败，保存证据并终止研究；该试验记录为
  `error`，不生成因子池或完成记录。
- 券商浮点均价采用固定每股 `0.000001 USD` 绝对容差核对，保留账本完整 Decimal 成本。
  现金、整股数量、待单、账户身份和风险历史的规则不变。
- 先处理已确认终态的历史订单，再对未完成订单做完整合约准入。股票池之外的旧终态订单
  不再阻断当前决策，剩余数量非零的 `Filled` 和无法核验的活动订单继续拒绝。

新增 18 项行为回归，覆盖三个成本情景、浮点舍入、容差双向边界、非正成本、三种订单终态，
以及未解决的历史订单不能被静默丢弃。证据独立保存在
`reports/research-gaps-review-fixes-20261024/`，原验收目录和历史研究不改写。

本轮 `make check` 全部通过：534 项测试，覆盖率 87%，耗时 883.58 秒，包含上述新增
18 项回归；Ruff、格式和 mypy 均通过，见 `check.log`。新目录离线账户演示通过，见
`paper-demo.log`；wheel 和源码包构建通过，最终文档随包核对见 `package-verification.parquet`。
`preservation.parquet` 确认 11,619 个历史文件和 125 个检查输入摘要未变。

本轮业务源码摘要为 `f5f8f84bd3cf06d69d497a97daa5c727f633e85ff0d98f2557be24094065a17e`，
金融行为摘要为 `53e1cb8d4955e8ab363e8b2ff62cc328d80eedc817466ed213f719e63ebfeda5`。
修复前的失败回归、早期检查名断言与静态检查失败、沙箱内下载构建依赖失败均保留原日志；
最终验收使用固定后的源码和检查输入，不覆盖早期失败证据。
