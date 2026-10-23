# IBKR 行情费用核查

核查日期：2026-10-22（北京时间）。依据 IBKR 官方 API 文档、公开价目表及 Paper
行情共享说明；尚未连接用户网关，以下不代表已确认本账户订阅或实际账单。
当前项目已选定 [IBKR 为唯一可信外部来源](../data-sources.md)，
按实际需要选择并记录订阅成本，全免费不是选型前提。

**结论：IBKR 不提供所有行情的免费 API 调用。** 主要收费方式是按交易所和数据级别
订阅，通常按月收费；标准订阅内请求不另收逐次使用费，按次收费的快照另算。
能在 TWS 看见免费报价、账户已入金或能登录 Paper，都不能证明全部 API 行情免费。
实际用户关于月费、历史权限及“免费成功”个例的讨论，另见[社区使用经验核查](ibkr-community.md)。

## 免费与收费的边界

| 数据 | 免费范围或收费条件 | 对本项目的影响 |
| --- | --- | --- |
| 延迟报价 | API 支持免费延迟报价，通常延迟 15–20 分钟，限有此服务的市场 | 可检验连接；必须记录实际数据类型，不能当作实时行情 |
| 美股/ETF 非综合实时报价 | 价目表列出 Cboe One/IEX 的免费非综合行情；API 文档另行说明平台内免费不保证 API 免费 | 不能据宣传页认定可免费取得 API 综合报价、全市场成交量或历史 K 线；需实际试读 |
| 美股综合一级实时报价 | 通常需对应 Network A/B/C 订阅；非专业用户各 1.50 美元/月 | SPY/XLF 所在的 ARCA 对应 Network B，优先核查这一项 |
| 股票/ETF 历史日线、分钟线 | 官方历史 API 说明要求相应一级实时行情权限；不因请求旧日期或等待收盘就自动免费 | 免费延迟报价不能直接替代历史 K 线授权；标准订阅后无额外逐根 K 线费用 |
| 历史逐笔、市场深度、期权、期货、指数 | 按品种及一级/二级行情分别授权，可能需额外付费 | 不能由美股 ETF 权限推广到其他产品；期权行情不自动包含其标的指数 |
| 外汇、加密货币 | 官方通用 API 说明明确：这两类不要求额外市场行情订阅 | 是订阅要求的例外，不代表交易费或所有地区、所有品种均免费 |
| Paper 账户 | 可共享一个对应实盘用户的市场行情订阅 | 可避免重复订阅，不会把原本收费的数据变成免费 |

延迟服务由 `reqMarketDataType(3)` 配合 `reqMktData` 请求；它不是将
`reqHistoricalData` 变为免费延迟历史接口的开关。普通冻结报价也不是免费路径：
官方说明 frozen 数据仍需与实时流相同的订阅。

## 当前美股费用示例

下表为 **Non-Professional（非专业市场数据用户）**公开月费，美元计价。
它与账户产品 **IBKR Pro** 是两种分类；拥有 Pro 账户不等于按专业市场数据用户收费。
实际资格、地区、税费及最终收费以账户订阅页为准。

| 服务 | 非专业用户月费 | 范围 |
| --- | --- | --- |
| NYSE American, BATS, ARCA, IEX and Regional Exchanges / Network B（L1） | 1.50 美元 | 目标 SPY/XLF 对应的 ARCA 上市证券一级行情 |
| NYSE / Network A（L1） | 1.50 美元 | NYSE 上市证券一级行情 |
| NASDAQ / Network C（L1） | 1.50 美元 | NASDAQ 上市证券一级行情 |
| 上述 A+B+C 单独订阅合计 | 4.50 美元 | 三个美股网络的一级行情，不含期权或深度 |
| OPRA（L1） | 1.50 美元 | 美股期权一级行情，不自动包含标的或指数 |
| NASDAQ TotalView-OpenView（L1/L2） | 16.50 美元 | 该服务覆盖的深度行情，不是全市场免费深度 |

这里的 A+B+C 合计不是价目表中的 `US Equity and Options Add-On Streaming Bundle`：
后者虽然列价也是 4.50 美元，但依赖 10 美元的基础包，不能只算附加包费用。
订阅按自然月计费，不按使用天数折算；佣金减免需满足相应条件，不能预先按零成本记录。

## 快照额度不能当作免费行情接口

公开价目表说明美股/ETF 快照为每次 0.01 美元，账户每月有 1 美元快照费用减免；
这对应最多约 100 次这类快照，不是不限量流式报价或历史下载。
**100 条默认行情线路**则是并发容量，与快照次数、免费数据权限分别计算。

本次还发现官方页面的范围差异：一般价目表把 ETF 列入快照产品，而 API 的
`Regulatory Snapshots` 页面明确只支持普通美国股票，不支持 ETF。
因此不能向 SPY/XLF 直接承诺 API 的免费快照额度，也不能未经核实就把
`snapshot=True`、`regulatorySnapshot=True` 和历史 K 线视为同一种请求。

## 对当前路线的影响

1. M4 统一接入 IBKR 行情、账户、订单、成交和费用，先以 Paper 验证；
   原始及规范化数据均以 IBKR 输入为依据，不按“全部免费”预算。
2. 先只读核查实际订阅及 SPY/XLF 的历史、实时、延迟请求，保存权限错误、数据类型、
   数据时间和接收时间。订阅费取自账户确认，不能从请求成功推导账单。
3. 若是非专业用户且尚无相应订阅，可评估 Network B 的 1.50 美元/月方案；已订阅的
   实盘数据先核查能否共享给 Paper，无须为了测试两只 ETF 先选大礼包。
4. Alpaca 旧数据保留作历史复现和参考，当前冻结 M3 继续记录原来源下的运维证据。
   IBKR 的价格调整、分红、拆股及成交量口径在接入时验证；不从其他供应商静默补齐，
   不改写原观察记录或冻结研究输入，也不将其追认为 IBKR 数据。

## 官方依据与归档

- [市场行情价目表](https://www.interactivebrokers.com/en/pricing/market-data-pricing.php)：免费非综合报价、快照费用、Network A/B/C 及其他月费。
- [API 行情订阅总则](https://www.interactivebrokers.com/docs/general/market-data-subscriptions/introduction)：多数证券要求 L1 订阅，外汇/加密货币例外。
- [TWS 与 API 数据区别](https://www.interactivebrokers.com/docs/general/market-data-subscriptions/tws-data-vs-api-data)：平台内免费数据与 API 权限不同。
- [延迟报价](https://www.interactivebrokers.com/docs/tws-api/doc/md/delayed-data)：15–20 分钟延迟及 frozen 权限。
- [历史市场数据（旧版官方说明）](https://interactivebrokers.github.io/tws-api/historical_data.html)：历史 API 与一级实时订阅的关系；旧版页面与现行通用权限说明合并参考，账户情况仍须实测。
- [当前行情 API 及历史限制](https://www.interactivebrokers.com/docs/tws-api/doc/md/introduction)：历史覆盖、请求节流、默认过滤与修订限制。
- [API 快照](https://www.interactivebrokers.com/docs/general/market-data-subscriptions/regulatory-snapshots)：按次费用与普通美国股票范围。
- [订阅计费](https://www.interactivebrokers.com/docs/general/market-data-subscriptions/market-data-costs-and-fees)：按月、不按比例折算、标准订阅后无额外使用费。
- [常用订阅](https://www.interactivebrokers.com/docs/general/market-data-subscriptions/popular-market-data-subscriptions/introduction)：SPY 的 Network B 归属及附加包依赖。
- [Paper 行情共享](https://www.interactivebrokers.com/docs/general/market-data-subscriptions/market-data-users/market-data-sharing)：共享现有订阅，不扩大权限。

逐页 HTTP 响应、实际获取时间和类型明确的价格提取保存在忽略目录
`reports/access/ibkr-market-data-costs-2026-10-22/`，采用 Parquet/Zstandard。
一次共享说明请求返回 503，后续成功响应单独保留；返回应用外壳的 FAQ 页面和 404
不作为费用或账户权限依据。本次只查询公开资料，没有订阅或修改付费服务。
