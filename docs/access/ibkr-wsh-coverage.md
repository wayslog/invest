# WSH 经 IBKR API 的适用范围核查

核查日期：2026-10-26。范围为官方公开资料与本仓库保存的现场记录；未购买订阅、开通试用、联系供应商或操作账户。目标是判断 WSH 能否补齐 SPY、XLF 在 2025-10-24 至 2026-10-26 的现金分红、拆股及覆盖证据。

**结论：WSH 仍是候选入口，但现有证据不足以确认它适合这次历史 ETF 回测，不建议现在为解除 10276 而直接付费。** API 订阅价格和股票事件字段已有官方依据；ETF 权益、指定历史区间、完整修订历史及 Paper 共享仍待确认。“尚未确认”不等于“不支持”。

## 产品与价格

| 产品 | 当前公开说明 | 对本项目的含义 |
| --- | --- | --- |
| WSH 零售 API 版 | 49 美元/月 | 对应程序化访问候选；税费及账户资格以订阅页为准 |
| WSH 机构 API 版 | 149 美元/月 | 不是零售版的历史覆盖升级承诺 |
| Corporate Event Data Feeds | 免费，单独列出 | 不能把免费服务视为已取得 API 权限 |

以上为 [IBKR 当前研究服务价目表](https://www.interactivebrokers.com/en/pricing/research-news-services.php)的独立条目。[WSH 的 IBKR 专页](https://www.wallstreethorizon.com/interactive-brokers)也列出 API 价格及一个月免费试用入口，但没有保证本账户符合试用条件，本次未开通。

旧官方 API 页使用 `Enchilada Pro` 名称，并明确标记文档已废弃；当前 API 文档要求启用 WSH 企业事件研究订阅。因此应核对当前名称中含 `(API)` 的服务，不能凭旧名称或旧价格判断权限。[旧文档](https://interactivebrokers.github.io/tws-api/fundamentals.html)、[当前 API 说明](https://www.interactivebrokers.com/docs/tws-api/doc/wall-street-horizon/introduction)

## ETF 与历史数据

WSH 的 IBKR 专页明确描述的是上市公司、20 多类事件，未明确列出 SPY、XLF 或 ETF 分配款的 API 覆盖。其独立 ETF Calendar 产品确实列出已公告分配款、资本利得构成、拆股日期和比例，以及前一年的已公告分配和拆股。**该产品能力不能自动视为 IBKR API 订阅包含的权益。** 公开页面也没有把这两个 ETF 的逐证券覆盖与 IBKR 合约 ID 对应起来。[IBKR 专页](https://www.wallstreethorizon.com/interactive-brokers)、[ETF Calendar](https://www.wallstreethorizon.com/etf-calendar)

| 本项目需要 | 已找到的官方依据 | 尚缺的确认 |
| --- | --- | --- |
| 除息日、支付日、现金金额和币种 | `wshe_div` 列出相关字段；区分美元金额与原币金额，并有混合现金/股票分红标记 | SPY、XLF 的实际回执是否包含这些字段，分配款构成及金额是否适合现金账本 |
| 拆股比例、除权日和生效日 | `wshe_splits` 定义比例为新股数对原股数，并列出日期 | 两个 ETF 的覆盖、特殊拆并股及实际字段完整性 |
| 取消和修订 | 分红有批准、待批准、取消状态；拆股状态表只列批准、待批准 | 拆股取消、旧版本、修订时间、稳定事件标识及完整变更链；分红相对上次支付的增减字段不等于事件修订历史 |

字段依据为 IBKR 当前文档链接的 [2022-12-23 字段表，第 2、3、12 页](https://www.interactivebrokers.com/campus/wp-content/uploads/sites/2/2023/09/WSHEclassesandfieldsforIBAPI2022-12-23.pdf)。它证明字段定义存在，不证明当前账户有数据、每条字段非空或历史覆盖完整。

当前请求对象允许日期区间，但没有在该页承诺最早历史日期、指定区间完整返回、历史版本回放或明确的“该区间无事件”证明。日期参数也不是历史时点承诺。对象文档规定 `conId/startDate/endDate` 与 `filter` 不可混用、每次只支持一种事件标签、`totalLimit` 最大 100；尚未找到可据此保证无遗漏遍历的分页说明。[当前请求对象](https://www.interactivebrokers.com/docs/tws-api/doc/wall-street-horizon/event-data/wsh-event-data-object)

因此，当前无法确认 2025-10-24 至 2026-10-26 的完整历史事件可经该订阅取得，也无法把今天回填的事件标为当时已知。公告时间只表示事件公告，不能代替服务在当时提供的版本和可知时间。后续即使解除权限错误，仍需验证覆盖、截断和修订；空响应或不足 100 条都不自动表示“没有遗漏”。这是本项目的验收判断，不是供应商已确认不支持历史数据。

## 现场错误与 Paper 权限

本次失败发生于无事件筛选参数的 `getWshMetaData()`：返回 `10276: News feed is not allowed.`；具体分红、拆股查询没有发出。因此它证明本次 API 客户端未获 WSH 数据权限，不能证明 SPY、XLF 不受支持，也不能归因于日期或分页参数。回执和原始失败保存在 VPS，详见[重跑记录](../research/p5-ibkr-input-contracts.md#2026-10-26-登录恢复后的重跑)。[官方错误码](https://www.interactivebrokers.com/docs/tws-api/doc/error-handling/error-codes)

IBKR 官方允许实盘用户与一个 Paper 账户共享市场行情；Paper 设置页写明可共享实时行情。本次查阅的页面没有明确承诺 WSH 研究/API 订阅同样共享，不能仅因实时行情共享已开启就判断 WSH 权限成立。[市场行情共享](https://www.interactivebrokers.com/docs/general/market-data-subscriptions/market-data-users/market-data-sharing)、[Paper 设置](https://www.ibkrguides.com/clientportal/papertradingaccount.htm)

用户可在实盘 Client Portal 的 `Settings > Trading Platform > Research Subscriptions` 只读查看当前订阅，核对是否已有名称含 `(API)` 的 WSH 项目，以及生效状态；无需提交订阅更改。Paper 关联设置位于 `Settings > Account Configuration > Paper Trading Account`。[研究订阅入口](https://www.ibkrguides.com/clientportal/usersettings/researchsubscriptions.htm)、[Paper 设置入口](https://www.ibkrguides.com/clientportal/papertradingaccount.htm)

收到覆盖确认后再决定是否试用或购买；权限恢复后仍需真实回执验收。权威采集继续经 IBKR，注明 `upstream_provider=wall_street_horizon`，保留原账户、研究记录和探索范围。

## 购买前需确认的四个问题

以下可供后续咨询使用，本次没有发送。产品覆盖问题应由 WSH 确认；登录用户权限与 Paper 共享应由 IBKR 确认。WSH 的 [IBKR 专页](https://www.wallstreethorizon.com/interactive-brokers)提供专门的 API 联系入口。

1. 零售 API 订阅是否包含 SPY、XLF 的现金分配款和拆股，能否经 IBKR TWS API 按这两个合约查询，而不是另购 ETF Calendar 或直接接 WSH？
2. 能否完整返回 2025-10-24 至 2026-10-26 的事件，包含除息日、支付日、原币金额及币种、比例和取消状态？如何证明空区间已覆盖、识别截断并取得剩余记录？
3. 能否返回稳定事件 ID、修订/取消历史及当时可知版本？若只能取得最新状态，历史回看和保留期限分别是什么？
4. 已开通的具体 API 订阅是否能被当前关联 Paper 用户使用，是否支持 IB Gateway，需什么授权设置？当前无筛选元数据请求返回 10276 应如何核查？
