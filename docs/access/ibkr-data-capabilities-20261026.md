# IBKR 数据能力、延迟与研究缺口

核查日期：2026-10-26（Asia/Shanghai）。面向私人美股股票/ETF 量化研究：当前日频，后续盘中执行。依据本日刷新的一手官方页面及仓库既有现场记录；本次没有登录券商、重试 API、购买订阅、修改来源政策或账户。

**IBKR 可以继续承担账户事实、交易执行行情和有限证券范围的历史采集；完整历史未复权数据、退市股票池与基本面 PIT 不能仅凭现有 IBKR 接口验收。** WSH 有真实公司事件产品，当前权限失败不能推导为平台不支持，但也没有证据证明购买后就能补齐本项目的历史 ETF 公司行动。

## 已验证状态与平台能力

[2026-10-26 现场记录](../research/p5-ibkr-input-contracts.md#2026-10-26-登录恢复后的重跑)确认：Paper 连接成功，`serverVersion=178`、`ib_async=2.1.0`，账户快照完整；SPY/XLF 共 502 根日线，覆盖 2025-10-24 至 2026-10-23 的 251 个会话；报价实际类型为 `3`。WSH 无筛选参数的 `getWshMetaData()` 返回 `10276: News feed is not allowed.`，具体事件请求未发出。**一年、两只 ETF 是这次采集配置，不是 IBKR 的平台历史上限；报价类型 3 也不能证明账户完全没有付费订阅。**

| 能力 | 时间粒度或延迟 | 权限与主要限制 | 项目状态 |
| --- | --- | --- | --- |
| `reqMktData` 成交价、买卖价/量、当日高低与成交量 | 美股通常按 250 毫秒聚合更新；不是逐笔 | 相应 L1 与 API 权限；综合行情和单所行情须区分 | 已收到延迟报价，真实实时流未验收。[官方流式说明](https://www.interactivebrokers.com/docs/tws-api/doc/md/streaming-data) |
| `reqTickByTickData` | `Last`、`AllLast`、`BidAsk`、`MidPoint` 逐笔流 | L1；并发上限为行情线路的 5%，默认约 5 个；同证券请求至少间隔 15 秒 | 尚未实现或验证；`AllLast` 多含部分非普通成交，不等于所有交易所原始消息。[官方逐笔说明](https://www.interactivebrokers.com/docs/tws-api/doc/md/live-ticks) |
| `reqRealTimeBars` | 固定 5 秒 OHLC；`TRADES` 带量、WAP、笔数 | 占 L1 线路；新请求受 60 次/600 秒限制 | 未来盘中入口，未验收。[官方 5 秒线](https://www.interactivebrokers.com/docs/tws-api/doc/md/5-second-bars) |
| `reqHistoricalData` | 秒、分钟、小时、日、周、月；`keepUpToDate` 约 4–6 秒更新未完成线 | 历史权限另核；支持粒度不等于全部证券均有相同回溯长度 | 两 ETF 日线成功；未证明 raw OHLCV。[官方历史线](https://www.interactivebrokers.com/docs/tws-api/doc/md/historical-bars) |
| WSH 公司行动与事件 | 公告、除息/支付、生效日期等事件字段；未发现 API 更新延迟 SLA | 独立研究订阅、覆盖及返回条数限制 | 当前客户端无权限；ETF 历史覆盖未验证。[官方 WSH](https://www.interactivebrokers.com/docs/tws-api/doc/wall-street-horizon/introduction) |
| 账户/Flex 公司行动、股息、费用 | 账户记账及报表时点 | 只代表该账户相关事实，不是全市场事件库 | 账户快照已取得；未取得完整研究事件库。[Flex 公司行动](https://www.ibkrguides.com/reportingreference/reportguide/corporate%20actionsfq.htm) |
| 历史证券身份、退市、历史成分、基本面 PIT | 需要证券有效区间、历史版本及当时可知时间 | 当前合约及当前扫描名单不能证明历史股票池；详见下文 | 本项目仍有实质缺口 |

`marketDataType` 应保存实际回调：`1` 为实时；`2` 为收盘后最后可用的 frozen，仍要求实时订阅；`3` 是延迟报价，官方表格写 15–20 分钟，美股网络介绍写 15 分钟；`4` 为 delayed frozen，盘中可能仍是前一天数据。服务器会依据现有权益返回可提供的最新类型，不能仅凭请求参数贴标签。250 毫秒是聚合节奏，5 秒是 K 线宽度，均不是交易所到本程序的端到端延迟保证；本次没有测得 P50/P95 延迟。[官方类型定义](https://www.interactivebrokers.com/docs/tws-api/doc/md/delayed-data)

## 费用、API 权限与最低订阅

IBKR 当前价目页提供免费 Cboe One/IEX 美股与 ETF 非综合实时行情；它只覆盖部分交易所，**不是 NBBO，也不能据此声称全市场成交量**。完整美股一级最优买卖价由 A/B/C 综合网络提供；按上市网络选订阅，不是每买一个股票就订阅所有交易场所。[当前价目表及 NBBO 定义](https://www.interactivebrokers.com/en/pricing/market-data-pricing.php)

以下为公开非专业用户美元月费，不代表本用户资格、实际订阅或账单：

| 需要 | 候选订阅 | 月费 |
| --- | --- | --- |
| SPY/XLF 等 ARCA 上市 ETF 的综合 L1 | Network B | 1.50 美元 |
| NYSE 上市股票综合 L1 | Network A | 1.50 美元 |
| NASDAQ 上市股票综合 L1 | Network C | 1.50 美元 |
| 覆盖上述三类股票/ETF | A+B+C 分别订阅 | 合计 4.50 美元 |
| 美股期权；本期股票/ETF 非必需 | OPRA L1 | 1.50 美元 |
| 组合包另一方案 | 10 美元基础包 + 4.50 美元 Equity and Options Add-On | 合计 14.50 美元，减免另核 |

价格依据同上；L2 深度不是日频或少量证券 L1 执行的必选项。常规订阅按月计费，不按剩余天数折算；标准订阅后通常没有逐次请求费，按次快照另计。[计费说明](https://www.interactivebrokers.com/docs/general/market-data-subscriptions/market-data-costs-and-fees)

公开文档存在必须保留的范围差异：

- **免费展示不等于 API 权益。** 通用 API 文档要求多数证券具备 L1，TWS 页面明确 API 属于 off-platform，平台内免费包可能不含 API。应核对登录用户的 API Acknowledgement 与实际数据类型，不能一概说“所有 API 必须付费”，也不能保证上述免费 Cboe/IEX 对本用户 API 可用。[订阅总则](https://www.interactivebrokers.com/docs/general/market-data-subscriptions/introduction)、[TWS/API 区别](https://www.interactivebrokers.com/docs/general/market-data-subscriptions/tws-data-vs-api-data)、[API 启用声明](https://www.interactivebrokers.com/docs/general/market-data-subscriptions/compliance-requirements-for-api-market-data/market-data-api-acknowledgement)
- **历史权限不能只引用旧规则。** 已弃用旧页写 API 历史总需实时 L1；当前错误码 `2188` 则专门说明距离当前 15 分钟内的历史请求需要有效订阅。后者不足以反推出所有更旧历史免费，前者也不能抹掉本次成功回执。须按账户、证券、历史截止时刻分别验证；`reqMarketDataType(3)` 不是通用历史免费开关。[旧历史权限说明](https://interactivebrokers.github.io/tws-api/historical_data.html)、[当前 2188](https://www.interactivebrokers.com/docs/tws-api/doc/error-handling/error-codes)
- **快照有两种。** 普通 `snapshot=True` 是已有行情权益下的一次返回；监管快照另收费 0.01 美元/次。通用 API 页把监管快照限制为美国普通股票，排除 ETF；流式页又提及股票及期权，并明确 Paper 不可用。因此不能把宣传的每月免费快照额度作为 SPY/XLF Paper 方案。[监管快照](https://www.interactivebrokers.com/docs/general/market-data-subscriptions/regulatory-snapshots)、[TWS 快照与 Paper 限制](https://www.interactivebrokers.com/docs/tws-api/doc/md/streaming-data#regulatory-snapshots)

一个实盘用户可向一个关联 Paper 账户共享行情订阅；这不增加权益，也未证明 WSH 研究订阅自动共享。实盘/Paper 竞争会话仍可能影响行情。当前 API 前提页列 IBKR Pro、账户资金及 API 启用条件；Pro 账户与专业市场数据用户是不同分类。[Paper 共享](https://www.interactivebrokers.com/docs/general/market-data-subscriptions/market-data-users/market-data-sharing)、[API 前提](https://www.interactivebrokers.com/docs/general/market-data-subscriptions/market-data-requirements)、[竞争会话错误 10197](https://www.interactivebrokers.com/docs/tws-api/doc/error-handling/error-codes)

## 历史质量、容量与股票池

股票/ETF `TRADES` 已按拆股复权，`ADJUSTED_LAST` 同时按拆股和分红复权；当前公开历史参数没有明确的股票 raw 开关。不能把 `TRADES` 当作当日原始现金成交价，也不能用两个价格序列之差构造完整现金分红账本。[价格定义](https://www.interactivebrokers.com/docs/tws-api/doc/md/historical-bars#trades)

历史线过滤部分不在 NBBO 的交易，因此历史量常低于实时汇总，历史数据还可能随请求时点修订。成交量的 shares/lot 单位和拆股调整必须按实际版本、配置及样本核对，不能统一乘 100 或把字段名当口径证据。完整拆股链只能在价格和数量口径均已证实后用于逆复权，不能恢复已过滤成交或当时数据版本。[历史过滤](https://www.interactivebrokers.com/docs/tws-api/doc/md/introduction#historical-data-filtering)

覆盖与批量限制如下：

- 当前官方不提供已停止交易证券的历史；迁所前数据往往缺失。30 秒及以下线仅保留近六个月；历史逐笔仅近三年，每次最多 1,000 点且不跨交易会话，末秒可能多返回。[覆盖限制](https://www.interactivebrokers.com/docs/tws-api/doc/md/introduction#unavailable-historical-data)、[历史逐笔](https://www.interactivebrokers.com/docs/tws-api/doc/md/historical-ticks)
- 日线不能由“一年请求参数”推导总历史上限；应逐合约查询 `reqHeadTimestamp` 并核对连续性。最早时间戳也不是区间无缺口证明。该请求需取消，并遵循小 K 线节流。[最早数据点](https://www.interactivebrokers.com/docs/tws-api/doc/md/earliest-data-point)
- 默认 100 条行情线路由 TWS/API 共用；当前通用发送速率是线路数除以 2，即默认 50 请求/秒，流式回调不逐条计为新请求。小 K 线另有同请求 15 秒、同合约/交易所/类型 2 秒内少于 6 次、10 分钟最多 60 次约束，`BID_ASK` 计两次。[请求速率](https://www.interactivebrokers.com/docs/tws-api/doc/pacing-limitations/introduction)、[历史节流](https://www.interactivebrokers.com/docs/tws-api/doc/md/introduction#pacing-violations-for-small-bars-30-secs-or-less)
- 旧版文档写最多 50 个同时进行的历史请求；当前重构页未重申这一数值，不能把它当作保证吞吐。历史批量采集应小并发、分片、缓存并检查完整性；本次未做吞吐测试，也不把小 K 线限制机械套为所有日线请求的统一上限。[旧版并发说明](https://interactivebrokers.github.io/tws-api/historical_limitations.html)

由这些限制可以推断：今日可查询的合约集合不能还原历史证券身份变化、退市收益或历史指数成分，存在幸存者偏差。**正式全市场历史选股须补充可核验的历史证券主表、成分有效区间与退市数据；本次未找到 IBKR 承诺完整提供这些研究数据的当前公开接口。** 当下开始持续归档能改善未来研究，不能补造过去的可知时间。

## 公司行动与基本面

WSH 当前 IBKR 字段表包含分红原币金额/币种、公告时间、除息日、支付日、批准/取消状态，以及拆股新旧股数比例与生效日期；也有业绩日期、EPS 事件等。它证明接口具有这些字段，不证明每条完整、覆盖全部 ETF 或有完整修订链。[当前文档仍链接的 2022-12-23 字段表](https://www.interactivebrokers.com/campus/wp-content/uploads/sites/2/2023/09/WSHEclassesandfieldsforIBAPI2022-12-23.pdf)

WSH 零售 API 49 美元/月，机构 API 149 美元/月，免费 Corporate Event Data Feeds 是另一条目。独立 ETF Calendar 确有已公告分配、拆股及前一年记录，但不能把它的权益自动归入 IBKR API。日期筛选、每请求一个事件类型及 `totalLimit <= 100` 也不构成任意历史、完整分页或 PIT 的保证。当前 10276 只证明这次客户端未获得 WSH 数据权限，不能区分订阅、Paper 共享或配置原因；没有发出事件请求就无法判断 SPY/XLF 覆盖。[研究价格](https://www.interactivebrokers.com/en/pricing/research-news-services.php)、[ETF Calendar](https://www.wallstreethorizon.com/etf-calendar)、[请求约束](https://www.interactivebrokers.com/docs/tws-api/doc/wall-street-horizon/event-data/wsh-event-data-object)

Flex Corporate Actions 有账户、合约、币种、日期、数量与金额；Dividend Accruals 有除息日、支付日、每股金额、税费和冲销，适合账户对账。它们只反映账户相关记录：未持有证券的空报表不能证明无分红/拆股。行情 generic tick `456` 只有过去/未来 12 个月汇总和下一次股息等，不是逐事件历史。[Flex 公司行动](https://www.ibkrguides.com/reportingreference/reportguide/corporate%20actionsfq.htm)、[股息应计](https://www.ibkrguides.com/reportingreference/reportguide/changeindividendaccruals_realized.htm)、[IB Dividends](https://www.interactivebrokers.com/docs/tws-api/doc/md/streaming-data#ib-dividends)

基本面方面，旧 Reuters `reqFundamentalData` 在官方旧引用中已标为 `Legacy/DEPRECATED`，不能因 SDK 仍保留方法就当成当前受支持方案。Web API 于 2026-01-06 明确废弃股息金额/收益率、除息日、P/E、市值、EPS、Beta 等基本面标签。WSH 财报事件不能替代完整三表、历史修订与当时可知版本；本次没有找到能满足完整基本面 PIT 的 IBKR 当前接口证据，应交由专业研究数据源补足。[旧接口状态](https://interactivebrokers.github.io/tws-api/classIBApi_1_1EClient.html)、[当前 Web API 变更记录](https://www.interactivebrokers.com/docs/web-api/changelog)

## 最低成本验证路线

1. 先只读核对现有实盘用户订阅、非专业资格、API 启用及 Paper 关联，不先购买大礼包。对当前日频继续保留已成功日线；分别核对较早截止时刻的历史权限与实时 L1 权限。只有需要新增实时综合报价且当前未覆盖时，再评估两 ETF 的 Network B 1.50 美元/月，扩展全美股才考虑 A+B+C 4.50 美元/月。
2. 后续获准实测时，在交易时段采集少量证券的实际类型、交易时间、接收时间、交易所及买卖价；记录断线、竞争会话和缺字段。以真实回执验证实时与单所/NBBO范围；普通流的更新时间不能替代逐笔延迟测量。
3. WSH 购买前先确认 SPY/XLF、指定历史区间、金额/币种/支付日、修订/取消与截断、Paper 权益。只在这些范围确认后评估官方提供的试用；本次未开通。[WSH 官方 IBKR 页面](https://www.wallstreethorizon.com/interactive-brokers)
4. 用已知拆股和分红样本验证原价/股数、现金流与历史连续性。若 WSH 不能证明所需覆盖，或目标扩展至全市场退市/PIT研究，就需要专业数据源提供相应历史。此处是能力分工建议；现行 IBKR 唯一权威来源政策保持不变，其他数据只能明确标注研究/参考，不能静默混入 IBKR 记录。

本报告只完成公开能力与既有证据核查；实时权限、事件覆盖、未复权转换和正式研究闭环均没有因此升级为已验收。
