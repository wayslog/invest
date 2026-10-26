# Tiingo 免费账户适用范围

核查日期：2026-10-26；将用户所说的 `tlingo` 理解为 Tiingo。本次只查官方资料，未获取令牌、调用账户 API、购买服务或修改来源政策。

**判断：Tiingo 免费 EOD 可以作为小规模日频 ETF 因子研究的数据候选；不能仅凭 EOD 数据就宣布精确现金账本回测已具备全部输入。** 它直接提供原始和复权行情，可以减少当前 IBKR 历史行情逆复权的工作，但具体账户权限与 SPY、XLF 的实际覆盖仍需回执验证。

## 免费套餐与普通 EOD

Starter 为 0 美元/月，限每月 500 个不同证券、每小时 50 次请求、每天 1,000 次、每月 1 GB，个人内部使用。按两个 ETF 的日线研究规模，这些配额通常足够；这是规模判断，非已完成采集。[官方价格表](https://www.tiingo.com/account/billing/pricing)

| EOD 已定义的数据 | 能解决什么 | 不能由此推断什么 |
| --- | --- | --- |
| 原始 OHLCV、复权 OHLCV；成交量单位为股 | 价量因子、原价成交模拟；复权价格包含拆股和分红调整 | 历史数据的当时可知版本 |
| `divCash` | 除息日对应的分配金额 | 支付日；文档明确该记录的 `date` 是 `exDate` |
| `splitFactor` | 拆股、合股等调整因子 | 公告时点、取消和完整修订链 |

上述来自 [EOD 文档](https://www.tiingo.com/documentation/end-of-day)。文档同时说明行情会随交易所更正更新；证券清单还包含预留代码，实际支持须用逐证券元数据和行情确认。使用已含分红调整的收益序列时，不能再重复加一次股息；若直接在除息日增加可用现金，只能作为明确标注的简化假设。

## 详细公司行动不能默认免费可用

分红产品页列有免费方案，但分红及拆股接口文档开头要求客户已启用 Beta 或具备企业权限，同时又写明包含于 EOD 权益中；分红段落还保留 2023-08-28 的 Beta 说明。**这些文字不能证明一个刚注册的免费账户无需额外开通即可调用详细接口。** 应以本账户实际准入为准，不能把 EOD 的 `divCash` 当成详细接口权益。[分红产品](https://www.tiingo.com/products/corporate-actions/stock-etf-mutual-fund-dividend-api)、[分红接口](https://www.tiingo.com/documentation/corporate-actions/dividends)、[拆股接口](https://www.tiingo.com/documentation/corporate-actions/splits)

详细分红定义了 `exDate`、`paymentDate`、`recordDate`、`declarationDate` 和金额；产品历史从 1962 年起，但详细数据从 2023 年起。文档允许支付、登记、公告日期为空，仅保证除息日和分配金额非空，因此 2025—2026 年落在产品范围内也不等于逐条字段齐全。[分红产品历史](https://www.tiingo.com/products/corporate-actions/stock-etf-mutual-fund-dividend-api)、[分红字段与空值说明](https://www.tiingo.com/documentation/corporate-actions/dividends)

拆股接口定义 `splitFactor = splitTo / splitFrom`，有有效、取消状态；分红频率码也包含取消。数据随新公告更新，但已查文档没有承诺完整历史修订、任意过去时点版本或空区间覆盖证明。状态字段存在不等于能重建当时所见版本。[拆股状态](https://www.tiingo.com/documentation/corporate-actions/splits)、[分红状态与更新](https://www.tiingo.com/documentation/corporate-actions/dividends)

## 还缺哪些输入

1. **精确现金回测**：本账户详细接口权限、实际非空支付日、分配金额币种及完整拆股/分红覆盖。已查分红字段表未列币种，不能凭美国上市就自动填美元；除息日应计与支付日可用现金须分开。
2. **严格历史时点研究**：事件与行情历史版本、可知时间；若扩展到选股，还需历史股票池与退市覆盖。当前回填数据仍应保留探索性质。
3. **券商动作闭环**：IBKR 的真实持仓、订单、成交、费用，以及绑定同一资金范围的持久策略状态。Tiingo 行情不提供这些账户事实，原 USD 5,000 观察账户也不能代替它们。

建议先验证普通 EOD，开展独立标记来源的探索研究；详细公司行动验收通过后再支持支付日现金记账。现有 [AGENTS.md](../../AGENTS.md) 仍规定 IBKR 为权威外部来源，本次不改变该规则，也不把 Tiingo 数据重标为 IBKR；正式引入研究数据源时再明确调整边界并保留历史记录。
