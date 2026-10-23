# M4：IBKR 数据与 Paper 执行

当前实现版本为 `0.7.0`，线上冻结 M3 继续使用 `0.6.1`。M4 的数据采集及执行演练
使用独立运行目录，不改动原 M3 账户、资金、高点、风险状态或观察窗口。

## 安装与只读采集

在仓库根目录运行：

```bash
make install
make ibkr-install
uv run --project integrations/ibkr --locked python integrations/ibkr/run.py capture --config configs/ibkr.toml --output data/ibkr/captures
uv run --project integrations/ibkr --locked python integrations/ibkr/run.py capture --config configs/ibkr.toml --output data/ibkr/minute --bar-size '1 min' --duration '5 D'
```

`integrations/ibkr/uv.lock` 单独锁定 `ib_async==2.1.0` 及其依赖，不降级 M3 的时区数据。
默认连接本机 Gateway Paper `127.0.0.1:4002`，使用 `clientId=72`，与连接诊断的 `71`
分开。网关只有一个受管理账户时自动选择；如果暴露多个账户，在配置中指定目标 Paper。
连接 Live 账户会被拒绝。API 会话、账户查询及采集不会自动提交订单。

云工作区无法直接连接 Gateway 时，可运行：

```bash
gh workflow run deploy.yml --ref main -f operation=ibkr-capture
```

工作流先复用完整 CI，再安装测试过的源码到 `/opt/invest-ibkr/releases/<commit>/`。
使用独立依赖环境，读取现有可用 Python 二进制；不切换 `/opt/invest/current`、
不运行 M3 日结或迁移、不改定时器。日线及分钟线分别保存到
`/var/lib/invest/ibkr/captures/daily/`、`/var/lib/invest/ibkr/captures/minute/`。
完整运行日志留在 `/var/lib/invest/ibkr/logs/`，Actions 只显示去除账户号码的摘要。
缺失权限或字段时，保留不完整批次和质量记录，工作流报告失败。

每个不可覆盖批次均含 Parquet/Zstandard：

- `raw`：SDK 查询参数、解码响应、账户回调和错误事件，明确不是原始 TCP 帧。
- `contracts`、`historical`、`quotes`：合约、OHLCV、报价，以及实际行情类型与时间口径。
- `account_values`、`positions`、`orders`、`executions`、`commissions`：券商账户事实。
- `capture`、`quality`：来源、Paper 环境、协议/SDK/源码版本、完整性、缺口与质量问题。

账户值来自本次订阅的回调并等待下载结束；不把 SDK 的旧缓存当成新的现金回执。
账户、持仓、订单与成交来自多个查询，仍不是券商的原子快照。
数量和金额保留 Decimal，规范化支持 18 位小数；缺失/NaN/未设置的 SDK 值保留缺失，
不转成零。SDK 浮点字段的原始解码表示另存在 `raw`。

## 数据使用边界

- `TRADES` 记为拆股调整价格；`ADJUSTED_LAST` 记为拆股及分红调整价格。
  新表使用 `invest.ibkr.*` 模式，不冒充旧 `invest.bars.v1` 原始价格输入。
- 分红除息日、支付日和完整拆股历史尚未取得；不从 Alpaca 或发行方表补成 IBKR 事件。
  因此本批次不自动取得原会计/研究引擎的准入资格。
- 成交量记为券商报告单位，Gateway 的美股数量设置仍需核查；不擅自乘除 100。
- 报价记录请求类型与实际 `marketDataType` 回调。Ticker 默认的 `1` 不作为实时数据证据。
  `sdk_updated_at` 是 SDK 接收更新的时间；可得时另存交易所成交时间。
- 日线检查交易日、缺失、重复、OHLCV 及过期数据。分钟线检查 UTC、纽约会话日期、
  常规时段和最近完整交易日的尾部；尚未自动证明所有分钟都连续或历史数据具备历史发布时点。
- 延迟/冻结、未完成的 K 线、企业行动及单位缺口写入质量记录，不提供其他来源的自动回退。

## 离线演练

```bash
make ibkr-demo M4_DEMO_DIR=reports/m4-demo
invest-ibkr status --journal reports/m4-demo/journal
```

演练完全不联网，来源明确为 `synthetic`：模拟已接受委托但确认丢失，重试只查询；
随后部分成交、费用迟到、撤销余单，逐项核对现金和持仓。再次运行保留原登记与日志。
代码变更后使用新的合成演练目录；真实执行日志不可通过新建目录来冒充接续。

## Paper 手工执行流程

以下命令在 Gateway 所在主机执行，均使用隔离运行器
`python integrations/ibkr/run.py`；源码路径采用实际 `/opt/invest-ibkr/releases/<commit>/`。
首次保持网关 Read-Only API，只做采集。进入 Paper 订单联调后才需要关闭网关只读开关。

1. `init --config configs/ibkr.toml --journal <独立执行日志目录>`：保存券商现金、持仓和已有
   执行的基线。它不是注入本金，不产生新的 5,000 美元 NAV 账户。已有登记不会被重置。
2. 在一个交易日收盘后、下一交易日开盘前运行
   `intent --journal <目录> --capture <批次> --intent-id <唯一标识> --symbol SPY --side BUY --quantity 1 --limit-price <限价>`。
   默认使用最近完整 XNYS 决策日，固定下一常规交易日的有效窗口；不提供真实交易的回填时钟。
   限价按捕获的合约 `minTick` 检查，完整市场价格档位规则仍以券商回执为准。
3. 在该有效窗口内运行 `submit --config configs/ibkr.toml --journal <目录> --intent-id <标识>`。
   支持整股、USD 股票/ETF、SMART、DAY 限价单及常规时段，不自动生成策略订单。
4. 用 `reconcile` 查询核对，或用 `cancel --intent-id <标识>` 撤销。重新启动后继续使用原目录、
   原账户和相同客户端 ID；相同意图不会再次发送。`status` 为本地状态，`reconcile` 才查询券商。
5. `export --journal <目录> --output <新报告目录>` 生成订单、确认成交、费用、持仓增量、
   现金差额和检查表。原始回执与日志保持追加，不覆盖旧事实。

默认单笔限价预算最多 1,000 美元、总持仓成本与未成交买入预留最多 5,000 美元。
买入还要求美元已结算现金足额；卖出仅限本日志确认取得且未被其他卖单占用的持仓。
这些是工程演练上限，不会把 IBKR Paper 的初始余额替换为项目资金。
持仓成本的按比例释放使用 18 位小数和半偶舍入，现金增量按确认成交及费用计算，不随成本分摊舍入。
现金对账允许 0.01 美元的报告精度差，报告保留实际差额，不把差额改写为零。

## 恢复与未支持事项

发单前先追加持久化 dispatch 记录。进程中断、超时、查询无结果均不允许直接再次发单，
必须以账户/客户端/委托 ID、合约和经济条款关联到正面回执。`orderRef` 只作关联，
不假设 IBKR 会替我们去重。状态不明、待撤单、缺费用或现金/持仓差异时停止新增风险。
撤单超时后，只有新查询明确显示原委托仍然开放，才可重试针对同一委托的撤单。

重复成交只入账一次，执行更正按 `execId` 修订替代旧版本，原记录仍保留。
后到费用及费用更正追加处理；取消确认不能掩盖缺失的成交明细。
API 的订单/成交查询历史有限，“查询不到”不作为从未发送或从未成交的证明。

执行登记绑定源码版本。版本变化时仍可查询和撤单，但新风险被阻止；已登记日志继续使用
保留的原运行版本，不隐式重建资金或清空风险。M4 执行日志的跨版本迁移尚未实现。
当前只核对美元执行增量；手工交易、出入金、非美元费用、分红、拆股及成交撤销会产生
待解释差异并暂停新增风险，尚不提供完整券商总净值会计或自动资金账本切换。

实际 Paper 委托/撤单/成交联调和模拟撮合的边界需另行记录。离线测试、零交易基线核对及
短期 Paper 收益均不能证明策略有效性或实盘成交质量，正式策略仍需要独立取得资格。
