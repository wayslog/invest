# M2 策略与组合研究

新的研究建设方案见[量化研究框架重构方案](../quantitative-research-refactor.md)，
明确直接复用 Qlib、Alphalens 并将因子挖掘纳入首版。以下命令和规则继续用于冻结的
M2/R1 历史流程；新方案不改写其登记、数据来源、研究结果或样本外状态。

当前版本：`0.6.1`；M2 首轮版本 `0.4.1`，R1 已有结果冻结于 `0.5.1`。
参数和选择规则见 [预登记方案](m2-protocol.md)，
结果与局限见 [M2 验收记录](../milestones/m2.md)。这里只运行本地历史研究账户。

项目新主线采用 [IBKR 唯一可信来源](../data-sources.md)。以下 Alpaca 命令及发行方核对
属于已实现的旧来源流程；冻结研究保留原输入、来源、引擎和登记，不追认为 IBKR 验证。
使用 IBKR 的新研究须先完成数据接入与规范化，另行登记，不能覆盖原未来窗口或历史结果。

## 离线运行

```bash
make research-demo
```

该命令生成三个明确标记 `synthetic` 的 ETF 数据集，登记 `configs/m2.toml`，运行完整研究，
并重新计算核对所有账本。输出在 `reports/m2-demo/study/`，打开 `report.html`。
人工价格只用于工程演示，不能成为投资证据；即使指标达标也不会取得 M3 研究资格。
输出不可覆盖，重复演示使用 `make research-demo M2_DEMO_DIR=reports/m2-demo-2`。

## 真实研究

在下载和查看新区间收益之前登记方案。v3 登记内嵌 TOML 原文、配置 SHA-256、
UTC 时间和引擎源码 SHA-256；运行前必须与当前引擎匹配，否则在计算任何结果前拒绝。
运行只读取并保存同一份登记字节，之后修改原 TOML 不会改变已登记研究或报告。
改变配置或代码必须另行登记，已看过的留出区间不能重新变成独立验证集。
探索已知历史时，登记须加 `--known-history`。v3 将这一暴露声明与配置一起冻结，
结果范围为 `known_history_research_only`，即使收益检查全过也不能授予正式资格。
例子见 [R1 方案](r1-long-horizon.md) 与 [实际结果](r1-long-horizon-results.md)。
失败原因与下一方案见 [R1 复盘](r1-postmortem.md) 和
[固定风险预算预登记](r1-capital-budget.md)。新配置可显式指定 `candidate_kinds`，
默认仍为 trend/rotation 两类；新方案只固定 rotation-120，避免额外搜索。
`research-propose` 同时冻结假设原文、已知截止日、未来窗口、源码与依赖锁。
未来窗口未结束时不运行不完整的 holdout；登记不会自动授予策略资格或创建资金账户。
固定风险预算的未来方案仍绑定已登记的 0.6.0 源码和依赖锁；0.6.1 的 CLI 修复不会
改写该登记、窗口或指纹。后续验证须使用其归档源码/原锁文件，不能用新指纹覆盖旧登记。

```bash
uv run --locked invest research-register \
  --config configs/m2.toml --output reports/research/new-registration.parquet

# 对预先声明的每个标的分别采集，不能按收益临时更换研究池。
uv run --locked invest fetch --symbol SPY \
  --start 2021-01-04 --end 2026-06-30 --feed sip --output data/alpaca
uv run --locked invest fetch --symbol XLF \
  --start 2021-01-04 --end 2026-06-30 --feed sip --output data/alpaca
uv run --locked invest fetch --symbol XLK \
  --start 2021-01-04 --end 2026-06-30 --feed sip --output data/alpaca
uv run --locked invest capture-dividends --output data/m2-issuer-source.parquet

# 将批次目录替换为 fetch 的实际输出；隔离批次也必须提供以保留排除证据。
uv run --locked invest research \
  --registration reports/research/new-registration.parquet \
  --input SPY=data/alpaca/SPY批次 --input XLF=data/alpaca/XLF批次 \
  --input XLK=data/alpaca/XLK批次 --issuer-source data/m2-issuer-source.parquet \
  --output reports/research/new-study
uv run --locked invest verify-study --study reports/research/new-study
```

首次真实研究使用了既有发行方捕获，可按验收记录复现，无须重复请求外部数据。
研究运行和复核全程离线。所有已登记标的都须提供；按质量排除后至少保留两个标的，
且包含市场基准 SPY，否则整个研究失败。首轮 XLK 因 due-bill 行动隔离，未补换标的。
提供旧批次不会伪造时间：对每个准入标的，从已核验的 `raw.parquet` 读取所有行情页的
接收时间，最早值存为 `first_bar_received_at`。该时间必须严格晚于登记；
缺失、相等或更早均使研究资格检查失败。批次的最终 `observed_at` 仍保留作来源证据，
但较晚的企业行动响应或后续行情页不能使较早行情变成登记后才获取的数据。
这项保守检查覆盖整个输入历史，不证明使用者未在外部看过数据或收益。

`verify-study` 先核对完整文件清单，再使用同版引擎重新计算全部运行，逐表比较现金、
持仓、订单、成交、事件、相关检查、利润归因、对账与指标。
引擎变更后只能用 `--hashes-only` 验证保存文件，或恢复归档源码和依赖再回放。
v1 登记没有引擎绑定，`0.4.1` 不接受它启动新研究或完整回放；旧归档仍可运行
`verify-study --hashes-only`。如需重算旧记录，应恢复其归档的旧版引擎。
不能给 v1 补写引擎指纹并保留旧登记时间；新代码需要带新时间戳的登记，
复用旧数据只能作为历史复核，不能追认独立留出资格。
哈希用于发现意外修改，不是第三方时间戳或防篡改签名。
v2 登记继续可读取，仍受原引擎绑定；不会重写成 v3 或补造当时的暴露声明。

## 可复核产物

```text
study/
├── registration.parquet       原始登记、配置正文、时间及绑定的引擎指纹
├── admission.parquet          准入/排除、来源指纹及最早行情页接收时间
├── inputs/<标的>/             完整批次副本（含隔离证据）
├── issuer-source.parquet      发行方捕获，真实研究必需
├── issuer-audits/<标的>.parquet
├── engine-source.parquet      本次引擎源码
├── runtime.parquet            Python 和安装包版本
├── candidates.parquet         全部预登记候选
├── pre-holdout-results.parquet 留出计算前保存的训练/验证全结果
├── holdout-selection.parquet  留出计算前保存的选择及时间
├── walk_<年份>-selection.parquet
├── comparison.parquet         全部比较，包括失败/停用/负收益
├── eligibility.parquet        每条 M3 研究门槛及证据
├── manifest.parquet           版本、指纹、范围、选择和资格
├── runs/<用途>/<候选-成本-压力>/
│   ├── equity.parquet         共享现金、总市值、应收与净值
│   ├── positions.parquet      每日每标的股数、价值、权重与风险组
│   ├── orders.parquet         收盘形成的订单意图（最后一天可能未成交）
│   ├── trades.parquet         次日实际模拟成交及共享现金余额
│   ├── events.parquet         行动、拒单、风险与被动超限
│   ├── correlations.parquet   每次成对筛查及采纳结论
│   ├── reconciliation.parquet 独立逐日重建检查
│   ├── attribution.parquet    已实现/未实现/分红权益利润和成本
│   ├── closed-trades.parquet  含部分卖出的平仓利润
│   ├── metrics.parquet        成本后绩效及敞口
│   └── periods.parquet        有对应市场基准时的年度归因
├── files.parquet              输入、源码、结果与图表的文件清单和哈希
├── validation.png / holdout.png
└── report.html
```

写入在临时目录进行，对账通过后才发布完整目录；相同输出路径拒绝覆盖。
可捕获异常保留 `*.failed-<编号>/failure.parquet` 和已生成证据，不静默重试或丢掉结果。
进程被强制终止时可能留下未发布的 `.tmp` 目录，应保留检查；它不会冒充完整研究。
这是独立历史实验，不能用新建目录清零某个持续运行资金账户的风险状态。

## 计算与适用边界

- 总收益指数只由当天及以前的原始价、分红和拆股递推；不把未来行动提前复权。
  基金公告历史时点未知，因此不宣称严格 point-in-time 或无幸存者偏差。
- 策略接口形成排序和目标，风控决定退出/上限，组合层先卖后买并按字母排序；
  每笔成交继续使用 M1 Decimal、整股、费用、拆股与分红核算。
- 总仓位和单仓上限约束新增买入；已有仓位因价格变动超限时，记录并在下一开盘减仓。
  收盘止损不保证按阈值成交，隔夜跳空可造成更大损失。
- 所有 ETF 归入美国股票组。相关性筛查会减少重叠，但不能代替持仓穿透。
- 每个区间独立从登记本金开始；共同预热不计收益也不预先持仓，首个订单由预热末日
  收盘形成。验证排名只看净收益，同分按名称；停用者仍参与排名，但不能绕过资格门槛。
- 双边换手 = 买卖成交总金额 / 平均每日净值；资金占用 = 股票市值 / 净值。
  收益、波动及 Sharpe 包含首日相对初始本金的收益；按 252 日年化，无风险收益假设为零。
  最长未创新高交易日包含尚未恢复的尾段，另标记期末是否未恢复。
- 未平仓股数及浮盈保留到期末，不虚构清仓；利润含已得但未支付的分红权益。
  平仓利润已计进出佣金，前三正利润平仓占比的分母是全部正平仓利润，不是总净利润。
- 80% 基准是匹配目标总敞口的对照，实际平均敞口可能与策略明显不同；报告同时呈现
  100% SPY 和现金。现金不计利息，未计税、真实盘口冲击、券商拒单或结算规则。

首轮仅 6 个候选，邻域比较直接使用全部窗口结果；不做统计显著性、多重检验校正或
全市场推广结论。首次留出完成后该段已被观察，后续改策略必须重新安排未见数据或前向观察。
