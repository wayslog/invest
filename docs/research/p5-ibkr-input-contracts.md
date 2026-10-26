# P5：IBKR 真实输入契约

核查日期：2026-10-24。调研范围：公开官方文档、`ib_async` 源码与当前采集实现。后文另记本轮只读现场检查与离线验收；没有变更订阅或发送订单。以下区分可实现的转换规则与仍需真实回执验证的输入条件。

2026-10-26 用户确认研究仅覆盖美股并统一按 USD 计算：供应方缺少币种字段不构成研究或回测准入阻塞，规范化研究表按[固定 USD 约定](../data.md#研究币种固定-usd)记录。原始回执及历史账户记录不改写。

随后用户授权接入 Alpaca 历史研究数据；该独立研究路径的实现与验收见
[P5 Alpaca 闭环](p5-alpaca-pipeline.md)。下文继续保留 IBKR 路径当时的限制和失败证据，
不将 Alpaca 研究输入改标为 IBKR，也不据此声明券商账户动作已经验收。

## 结论

现有 IBKR capture 不能直接标为可执行的 `raw` 历史行情。TWS `TRADES` 已做拆股复权，`ADJUSTED_LAST` 同时做拆股和分红复权；公开参数未提供股票未复权日线选项。可实现的最小历史入口是：保存原始回执，取得明确覆盖范围的拆股、现金分红和成交量口径证据，再生成新的 Parquet 快照与执行数据。只增加拒绝检查或通过合成测试，不等于已完成真实输入接入。[历史日线定义](https://www.interactivebrokers.com/docs/tws-api/doc/md/historical-bars)

账户侧可以只读导出既有权威状态；券商事实与策略状态必须分别取自各自来源。现有 USD 5,000 M3 现金观察是独立观察账户，不能因为行情来源是 IBKR，就将其本金映射为整个 IBKR Paper 账户的现金。是否能核对通过取决于实际账户绑定、资金范围和完整历史，不得重置本金或风险状态。

## 行情与成交量

| 项目 | 已核实事实 | 接入规则 |
| --- | --- | --- |
| `TRADES` | OHLC 按拆股调整，不按现金分红调整 | 保留 `split_adjusted`；没有完整逆复权证据时不得改为 `raw` |
| `ADJUSTED_LAST` | 同时按拆股、分红调整 | 不用作现金成交价；最小版本不从它反推现金分红事件 |
| 历史成交量 | 历史数据会过滤部分交易，与实时汇总不同 | 记录 `volume_filter=ibkr_historical`，不能声称包含全市场每笔成交 |
| 接收时点 | 官方说明不同请求时间可能返回不同历史数据 | 保留请求、接收时间和独立快照；后来的修订不覆盖旧快照 |

前三种行情定义见[历史日线](https://www.interactivebrokers.com/docs/tws-api/doc/md/historical-bars)，过滤和修订见[行情限制](https://www.interactivebrokers.com/docs/tws-api/doc/md/introduction)。本次查阅的日线文档未给出足够明确的逐历史区间成交量拆股还原规则。不能仅因字段名是 `volume`，或 SDK 将其解析为数值，就证明它是当日原始股数。`ib_async` 是 TWS socket 协议客户端，也没有自动补足事件和数据覆盖的能力。[客户端源码](https://ib-api-reloaded.github.io/ib_async/_modules/ib_async/client.html)

建议转换契约单独记录 `volume_unit`、`volume_adjustment`、SDK/TWS 版本、对应配置或提供方确认的 `source_ref`。单位为 lot 时，必须有对应证券和时段的实际换算因子，禁止无证据统一乘 100。即使证实单位为 shares，仍需确认它是拆股调整后的股数还是交易当日股数。

在明确采用后向拆股调整、且全部事件可核对的前提下，令 `R(t)` 为交易日 `t` 之后、直到采集复权基准时点的所有 `new_shares / old_shares` 之积，则建议转换公式为 `raw_price(t) = adjusted_price(t) * R(t)`。只有证实 volume 同步按该因子调整时，才用 `raw_volume(t) = adjusted_volume(t) / R(t)`；原始成交量不做该除法。这是转换约定，必须由真实样本及提供方口径验证，不能当作已验证的 IBKR 行为。

覆盖范围须延伸到复权基准时点，不能仅覆盖回测终点。逆复权只解决价格尺度，不恢复当时的数据版本、可知时间或股票池。

`reqHistoricalTicks` 可返回与 TWS Time & Sales 相同的历史成交信息，但当前文档限制为近三年，且没有明确承诺股票拆股前的未复权语义。因此本次不把逐笔数据聚合列作已证明的替代路径。[历史逐笔](https://www.interactivebrokers.com/docs/tws-api/doc/md/historical-ticks)

## 公司行动的可用来源

| 入口 | 可以得到什么 | 不能据此声称什么 |
| --- | --- | --- |
| TWS `reqWshMetaData` / `reqWshEventData` | 按证券请求的公司事件，可覆盖未持有证券；事件类型包括分红、拆股 | 不能从接口存在推断当前订阅、任意历史范围或完整事件覆盖已可用 |
| Client Portal / Flex Corporate Actions | 账户相关公司行动、合约标识、日期、数量、类型和交易标识 | 空账户报表不能证明某只未持有证券没有拆股或分红 |
| Flex Change in Dividend Accruals | 账户应计股息变动、ex/pay dates、每股金额、税费及冲销 | 不能当作全部历史股票池的公司行动库 |
| 行情股息字段 | 最近或预期年度汇总、下一次事件等指标 | 不能从汇总金额反推完整逐次现金股息和支付日 |

WSH 的当前接口见[对象定义](https://www.interactivebrokers.com/docs/tws-api/doc/wall-street-horizon/event-data/wsh-event-data-object)；账户事件字段见[Corporate Actions](https://www.ibkrguides.com/reportingreference/reportguide/corporate%20actionsfq.htm)、[Dividend Accruals](https://www.ibkrguides.com/reportingreference/reportguide/changeindividendaccruals_realized.htm)；行情字段见[Web API Streaming Data](https://www.interactivebrokers.com/docs/web-api/ws/streaming-data)。

WSH 是最值得进行真实只读探测的事件入口。官方字段说明给出 `wshe_div` 的公告时间、除息日、支付日、金额、币种、批准状态，以及 `wshe_splits` 的比例、除权日、生效日和状态；比例定义为新股数比原股数。应保留 `source=ibkr` 和 `upstream_provider=wall_street_horizon`，不能隐藏上游来源。[WSH 字段说明，2022-12-23](https://www.interactivebrokers.com/campus/wp-content/uploads/sites/2/2023/09/WSHEclassesandfieldsforIBAPI2022-12-23.pdf)

当前文档规定：`conId/startDate/endDate` 与 `filter` 两种方式不可混用；每请求只支持一个事件类型；`totalLimit` 最大 100。旧版页面曾描述不同过滤行为，实际实现须以当前回执和元数据为准。分别请求事件类型并检查截断；小于上限也不自动证明证券或时间范围完整。[当前 WSH 请求对象](https://www.interactivebrokers.com/docs/tws-api/doc/wall-street-horizon/event-data/wsh-event-data-object)

最小规范化输入建议分为事件表和覆盖表：事件记录稳定证券标识、类型、有效日、公告及接收时间、比例或金额、币种、pay date、修订/取消状态和来源；覆盖表明确证券、起止日、事件类型、提供方声明的范围、缺口和对应回执。没有事件记录与没有事件是不同状态。无法证明覆盖、未知事件、缺支付日、取消或修订未处理时，保留缺口并禁止以 `corporate_actions=complete` 进入正式执行回测。

## 历史时点和股票池

IBKR 明确不提供已经停止交易证券的历史行情，迁所前的历史也可能缺失。这意味着按当前可查询合约组成历史股票池会遗漏退市或迁所样本。当前合约查询与行情历史不是历史成分库。[历史数据限制](https://www.interactivebrokers.com/docs/tws-api/doc/md/introduction)

建议保留 `observed_at`、`available_at`、成员有效区间及其证据。今天回填的历史行情和当前名单只可按其真实可知时间入库；需要旧时点做研究时保留明确的探索范围，不回填虚构的旧 `available_at`，不重新取得未见样本资格。完整正式研究需要当时归档的 IBKR 快照与成员记录，或明确支持历史时点的提供方证据；公开接口说明不能替代这些数据。

## 账户导出与资金范围

Flex Cash Report 包含期初、期末现金、期末已结算现金、入出金、转账、佣金、股息与利息，并区分币种及账户分部，可用于现金变动核对。Paper 账户也支持 Activity 与 Trade Confirmation Flex Queries。[现金报表](https://www.ibkrguides.com/reportingreference/reportguide/cash%20reportfq.htm)、[Paper 报表](https://www.ibkrguides.com/clientportal/accountmanagementforpapertradingaccount.htm)

券商持仓、订单、成交、现金和费用可核对当前财务事实；策略初始资本、持仓峰值、组合高水位、上次退出、再平衡进度及 `risk_status` 是本框架的状态。公开账户/Flex 字段未定义本框架的这些策略语义，不能从最新 NAV 或平均成本自动补出。只读导出应复制既有权威状态并记录账户 ID、策略及引擎版本、历史 head 和导出来源，财务差异由核对结果明确拒绝。

对于独立 M3 观察，导出后仍是该观察的状态，不是 IBKR 全账户状态。若以后要将一个策略映射到券商子资金，须先定义并持久保存资金划拨、交易归属、费用归属和同步规则；不能以缩放券商余额、忽略其他持仓或新建 USD 5,000 余额替代这个映射。

## 最小交付和真实验收依赖

可以立即开发：有严格输入契约的 Parquet 转换器、公司行动/覆盖校验、独立账户状态只读导出、冻结来源与重放、坏数据和历史不变回归测试。

真实闭环仍需以下证据，不能由代码自动推断：

1. 当前 Paper 用户的历史行情权限、成功完成的日线回执、实际 TWS/SDK 版本和成交量口径。
2. 同一证券范围内的拆股、现金分红及完整覆盖证明；若使用 WSH，需要有效订阅、实际返回字段、历史范围与截断行为。
3. 真实的历史成员和可知时间，或明确接受探索性回填范围；不得删除缺失证券制造完整股票池。
4. 同一权威账户的已保存策略状态、券商绑定及资金范围。独立观察不能冒充券商账户。

取得上述输入后，才可验收真实 `mine -> backtest -> decide`：核对一个已知拆股和分红样本、对比原始回执与规范化价格/股数、核对现金与待单，再从冻结输入重放选股动作。数据不足时报告具体缺口；不得用空事件、伪造历史时点、合成账户或仅有拒绝测试替代真实通过记录。

## 本轮实现与使用

本轮完成下列前置入口，**尚未完成 P5 的真实研究与动作闭环**。
原价/原始股数转换、完整企业行动覆盖、历史成分与可知时间证据、券商账户的持久策略状态仍未具备。
不通过手填 `complete`、倒填时点或重新登记本金绕过这些缺口。

| 入口 | 实现与结果边界 |
| --- | --- |
| `invest-ibkr market-import` | 复用 P1 采集转换，输出统一研究 Parquet 快照；当前历史采集须显式 `--allow-exploratory`，不改变复权价、未知量纲、当前样本或未知历史可知时间 |
| `invest-ibkr events-capture` | 独立客户端 74 只读查询 WSH 元数据、逐证券分别查询分红和拆股；冻结请求回执、合约来源、失败和上游来源；没有下单接口调用 |
| `invest-ibkr observation-export` | 从原现金观察的已提交前缀只读导出身份、本金、高水位、注册引擎、观察窗口、完成/遗漏计数与历史头；不取得原账户写锁；并发推进时拒绝混合快照 |

```bash
# 行情导入、观察导出使用项目主环境，不给独立 IBKR SDK 添加研究或报表依赖。
uv run --locked invest-ibkr market-import \
  --capture data/ibkr/captures/daily/example \
  --output data/research/ibkr-example --allow-exploratory
uv run --locked invest-ibkr observation-export \
  --account reports/existing-observation --output reports/new-observation-export

# 仅企业行动联网请求需要独立 SDK 和已登录的 Paper Gateway。
uv run --project integrations/ibkr --locked python integrations/ibkr/run.py events-capture \
  --config configs/ibkr.toml --client-id 74 \
  --capture data/ibkr/captures/daily/example --output data/ibkr/events/new-capture
```

所有输出使用新目录。部署账户的导出在部署主机上运行并留存，不转存到本地，也不改变
`/opt/invest/current`、定时器、原注册、账户 journal 或备份策略。

企业行动输出的 `raw.parquet` 保留原始解码回执，`requests.parquet` 保存逐请求状态，
`capture.parquet` 记录源码/SDK 和上游，`market_capture/` 冻结证券来源，`artifacts.parquet`
用于内容复查。事件请求失败时保留证据并返回退出码 1；输入错误返回失败。
该版本查询的是服务返回的事件窗口，未提供历史范围或分页承诺。
即使响应为空、条数不足 100 或请求均成功，`coverage_status` 仍为 `unverified`，
`corporate_actions_complete=false`；不能直接作为 `backtest` 的执行行情。

观察导出保存 `observation_state.parquet` 和 `source_account/` 的原始已提交前缀，
标记 `context_kind=observation_state`、`capital_scope=project_cash_observation`、
`broker_context_eligible=false`。它保留原观察事实，不能作为 P4 的 `account_state`。
本仓库当前没有与该券商全账户绑定的完整策略状态；导出器不会伪造入场时间、冷却历史、
策略/因子池绑定或资金划拨。此缺口不由一次 Gateway 登录解决。

## 2026-10-24 现场事实

- `megalog` 运行版本仍为 `75d17686787c0afc89ef5abd01b5dc0cee859057`，账户注册引擎匹配。
  日结和健康检查服务失败，定时器仍启用；最近两次采集记录均为 `ConnectionRefusedError`。
  本次 TCP 检查确认 `127.0.0.1:4002` 拒绝连接，Java Gateway 进程缺失。
- 用户随后明确授权启动既有 Gateway。已在现有 `:99` 显示器启动
  `/root/Jts/ibgateway/1050/ibgateway`，确认 Java 进程存在；端口仍未开放。
  用户表示暂时无法完成登录，因此停止真实 API 验证，没有反复重启、重试日结或改动账户。
- 独立工具源码位于 VPS 临时目录，没有切换运行版本。使用 2026-10-23 保存的真实采集，
  成功导入 502 条日线、2 个标的；快照范围为 `exploratory`，保留五项限制。
  原现金观察导出为 0/60、遗漏 0，不映射券商余额。47 个原始采集/账户文件内容未变。
- 私有结果仅在 VPS 的 `/var/lib/invest/p5-inputs-20261024-a082707b9ab6/`，
  其中 `acceptance.parquet` 记录导入、导出与原文件检查；不作为完整 P5 验收。
  首次使用独立 SDK 环境导出因缺少 `matplotlib` 失败，随后改用已有项目主环境成功，
  没有向 SDK 环境增加依赖。

恢复后先验证 Paper 登录及 WSH 权限、取得并核对真实事件和覆盖，再决定原价/量纲转换。
账户侧仍需明确券商资金与持久策略状态的权威来源；不得把观察账户升级为券商账户。

## 本地检查

本轮源码摘要为 `a082707b9ab6e77424bf211d7b9d572a6b30aed9405fbf039e1c4ce73212e2b7`；
证据位于忽略目录 `reports/p5-inputs-validation-20261024/`。

| 检查 | 结果 |
| --- | --- |
| `make check` | Ruff、161 个文件格式、106 个文件类型检查通过；549 项测试通过，含新增 15 项回归，耗时 888.49 秒；覆盖率 88%；见 `check.log` |
| 行为回归 | 空/失败 WSH 响应不产生完整覆盖；逐证券单事件请求、独立客户端、来源拒绝、历史目录保护；观察身份/资金/窗口/遗漏保留、并发推进拒绝、禁止作为券商上下文 |
| `make demo` | 全新合成目录 `reports/p5-input-paper-20261024/`，旧 CLI 与 Decimal 账户演示通过；见 `paper-demo.log` |
| `make build` | wheel、sdist 构建通过；65 个源码文件与包内容一致，独立 SDK 虚拟环境未打入源码包 |
| 历史保护 | 开始前登记的本地 11,471 个历史文件内容全部未变；见 `history-before.parquet`、`history-verification.parquet` |

`build.log` 保留沙箱无法解析 PyPI 索引的失败；`build-retry.log` 是正常网络下的成功构建。
上述检查证明前置工具的行为与兼容性，不替代真实公司行动权限、原价转换或券商策略状态验收。

## 2026-10-26 登录恢复后的重跑

用户完成 Paper 登录后，在 `megalog` 使用同一版前置工具重新采集，行情客户端为 75，
WSH 客户端为 74。没有部署新版、手动重跑日结、发送订单或修改订阅。

| 步骤 | 现场结果 |
| --- | --- |
| Paper API 与账户采集 | 通过；`127.0.0.1:4002` 可连接，server version 178、`ib_async` 2.1.0；账户快照完整，持仓、委托、成交均为 0 |
| 日线采集 | SPY、XLF 共 502 条，覆盖 2025-10-24 至 2026-10-23 的 251 个会话；报价类型为 3（延迟行情） |
| Parquet 导入 | 新快照读取校验通过；保留 `exploratory` 及原有五项限制，没有将复权行情改标为原价 |
| WSH 公司行动 | 元数据请求返回 `10276: News feed is not allowed.`；四项分红/拆股请求保持 `not_requested`，覆盖仍未验证 |
| 观察账户导出 | 保留原账户身份与状态，完成 0/60、遗漏 0；仍为 `observation_state`，不能作为券商策略状态 |
| 历史与产物核验 | 登记的 1,020 个既有 Parquet 文件内容均未变；事件、观察导出及本轮产物清单验证通过 |

IBKR 官方将 10276 定义为当前 API 客户端没有接收 WSH 数据的权限；仅凭该错误不能
区分未订阅、Paper 权限未生效或其他授权配置问题，需要先核实登录用户的 WSH 权限。
[官方错误码](https://www.interactivebrokers.com/docs/tws-api/doc/error-handling/error-codes)

新证据保存在 VPS 的 `/var/lib/invest/p5-inputs-20261026-retry-01/`：
`captures/` 为真实原始采集，`market/` 为研究快照，`events/` 保留失败回执，
`observation/` 为只读导出，`acceptance.parquet` 保存 14 项结果，
`preservation.parquet` 保存逐文件历史核验。此前失败目录保持不变，私有产物未转存到本地。

本次已解除登录阻塞，但完整 `mine -> backtest -> decide` 尚未运行通过：
公司行动覆盖、原价及成交量口径仍缺证据；在部署账户与 operations 目录中也没有找到
`context_kind=account_state` 的持久策略状态导出。现有两个 ETF 的探索快照不能代替
完整历史股票池。不能将本次采集成功视为正式回测、选股动作或获利能力的验收。

## WSH 订阅前的适用范围核查

用户选择先核实适用范围。2026-10-26 的[专项核查](../access/ibkr-wsh-coverage.md)
确认零售 API 版公开价为每月 49 美元，独立于免费 WSH 服务；当前公开资料没有明确证明
该订阅包括 SPY/XLF 的完整历史公司行动、历史修订版本或 WSH 在 Paper 用户上的共享权益。
WSH 独立 ETF Calendar 的能力不能自动视为 IBKR API 订阅内容。

因此暂不将购买 WSH 作为解决 P5 缺口的确定方案。先按专项记录中的四个问题确认产品覆盖
和 Paper 权限，再决定试用或购买；本次仅记录咨询问题，没有开通服务或联系供应商。
此结论表示证据尚不足，不表示供应商已经确认不支持。
