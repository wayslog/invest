# SPY 与 QQQ 历史周度成员及可得时间核查

核查日期：2026-10-26。目标区间已确认为 **2025-07-07 至 2026-10-23**。目标是每周使用当时可知的两个 ETF 实际持仓并集，而不是用今天的股票池回看历史，也不是未经说明改用 S&P 500/Nasdaq-100 指数成分。

**目前取得的免费官方资料不足以证明完整历史周度成员。** 发行方当前文件可支持向前持续采集；SEC 能提供带报告期、申报日期的历史公开快照，但本次实际记录是季末且滞后披露。两个商业候选支持历史查询，不过本次均未登录、购买或调用付费数据，严格时点数据资格仍未验证。

## 发行方：当前快照已实证，历史周档尚未取得

| 来源 | 本次实际 GET | 能证明的内容 | 尚缺内容 |
| --- | --- | --- | --- |
| State Street SPY | 官方 XLSX，HTTP 200 | 持仓日期 2026-10-22；505 行，其中 503 行满足现有普通股票解析条件 | 目标区间每周原始文件及其首次公开时间、后续修订 |
| Invesco QQQ | 官方 JSON，HTTP 200 | `effectiveBusinessDate=2026-10-23`、`effectiveDate=2026-10-24`；106 行 | 同期历史快照及版本/发布时间 |

[SPY 产品页](https://www.ssga.com/us/en/individual/etfs/state-street-spdr-sp-500-etf-trust-spy)把[下载文件](https://www.ssga.com/library-content/products/fund-data/etfs/us/holdings-daily-us-en-spy.xlsx)标为每日持仓。[QQQ 产品页](https://www.invesco.com/us/en/financial-products/etfs/invesco-qqq-trust-series-1.html)和[QQQ 介绍页](https://www.invesco.com/qqq-etf/en/about.html)展示基金持仓与每日披露说明。本次读取这些页面未找到并验证覆盖目标区间的历史周档入口；这不等于证明发行方没有任何其他归档服务。

现有 QQQ 入口是 `https://dng-api.invesco.com/cache/v1/accounts/en_US/shareclasses/QQQ/holdings/fund?idType=ticker&interval=monthly&productType=ETF`。本次响应只有一个快照。请求中出现 `interval=monthly` 不能证明它返回逐月或历史成员，更不能证明周度历史覆盖。

`holdings_as_of` 是持仓所属日期；`captured_at` 是本次下载时间。QQQ 的 `effectiveDate`、HTTP `Last-Modified` 都不能未经发行方说明就替代首次公开时刻。本次 10 月 26 日取到的文件，不可回填成此前每个周末已知的数据。

## SEC：真实历史披露可用，但不能填成每周实际持仓

本次直接 GET 两个官方 submissions JSON 均返回 200：[SPY，CIK 884394](https://data.sec.gov/submissions/CIK0000884394.json)、[QQQ，CIK 1067839](https://data.sec.gov/submissions/CIK0001067839.json)。从响应程序化提取了报告期 2025-03-31 至 2026-10-23 的 12 条 NPORT-P 记录，每只基金 6 条，报告期均为季末。

| 报告持仓日期 | SPY 申报日期 | QQQ 申报日期 |
| --- | --- | --- |
| 2025-03-31 | 2025-05-28 | 2025-05-29 |
| 2025-06-30 | 2025-08-28 | 2025-08-28 |
| 2025-09-30 | 2025-11-26 | 2025-11-19 |
| 2025-12-31 | 2026-02-26 | 2026-02-27 |
| 2026-03-31 | 2026-05-28 | 2026-05-28 |
| 2026-06-30 | 2026-08-28 | 2026-08-28 |

例如，2025-09-30 的 [SPY 申报索引](https://www.sec.gov/Archives/edgar/data/884394/000141036825031962/0001410368-25-031962-index.htm)显示 11 月 26 日接受；[QQQ 申报索引](https://www.sec.gov/Archives/edgar/data/1067839/000106783925000007/0001067839-25-000007-index.htm)显示 11 月 19 日接受。这些索引通过网页工具读取；直接 HTTP 访问本次返回 403，错误正文也已保存。submissions 原始 JSON 成功获取，两种方法不混称。

因此，7 月初做决策时，不能使用后来 8 月才申报的 6 月末记录；也不能把相邻两个季末的相同成员视为证明中间各周没有变化。按“最近已公开季末披露”持有旧名单，是另一种滞后披露策略，不能冒充用户指定的当周基金持仓策略。`acceptanceDateTime` 是接受时刻，保存为 `accepted_at`；没有进一步核验传播规则时，不直接宣称它是发行方或数据商首次向市场公开的时刻。

[SEC N-PORT 数据集说明](https://www.sec.gov/data-research/sec-markets-data/form-n-port-data-sets)明确，打包数据只包含已经公开的申报信息，按季度更新，不能替代原申报及全部元数据。2024 年提高披露频率的修订已被 [2025 年最终规则](https://www.sec.gov/rules-regulations/2025/04/s7-26-22)推迟至 2027/2028 年实施；[2026 年变更](https://www.sec.gov/rules-regulations/2026/02/s7-2026-05)在本次读取的官方页面仍标为提案。不能把提案或表单名称中的 Monthly 当作目标区间逐周即时公开的证明。

## 两个商业候选的实际证据边界

### Massive / ETF Global Constituents

[官方接口](https://massive.com/docs/rest/partners/etf-global/constituents)为 `GET /etf-global/v1/constituents`，支持基金代码与日期过滤，分页使用 `next_url`；文档列明每日更新、历史始于 2017-04-03。字段包含 `effective_date`、`processed_date`，以及可选的 `us_code`、`isin`、`figi`、`sedol`。

必须区分：`effective_date` 表示资料所属日期；`processed_date` 表示 ETF Global 收到并处理的日期。两者都只有日期，没有日内时刻。本次文档的持仓响应未列出首次公开时间、修订版本号或“查询当时版本”参数；因此用 `processed_date <= 决策日` 过滤也不足以自动证明严格 PIT。可选证券标识有助于映射，但不能代替完整的证券更名、退市和继承关系主表；该持仓响应也未列出退市日期或并购对价字段。

[官方伙伴定价页](https://massive.com/partners/etf-global)标示 Constituents 为个人使用 **99 USD/月**；[产品发布说明](https://massive.com/blog/announcing-massive-etf-global-partnership-constituents-fund-flows-analytics-profiles-and-taxonomies-2)把各类 ETF 数据称作独立数据类型的 add-on。**本次公开材料没有明确回答是否还必须另付 Stocks 基础套餐费用**，也未核对税费与账户适用条款，不能将 99 USD 认定为已确认总支出。没有创建账户、登录或购买。

### Finnhub ETFs Holdings

[官方文档](https://finnhub.io/docs/api/etfs-holdings)的 HTTP HTML 内嵌 OpenAPI 已实际取得并解析：`/etf/holdings` 支持 `symbol`、`isin`、`skip`、`date`，`skip` 可查历史，`date` 与 `skip` 互斥；文档明确写 `Premium required.`。返回契约包含 `atDate`，不提供已核验的首次公开时刻或修订版本。

这证明存在付费历史查询能力，不证明 SPY/QQQ 在本区间每周都有完整样本。当前套餐总价、历史频率、证券退出后的保留政策和严格 PIT 语义均未验收；没有调用需凭据的接口。

## 后续授权后应进行的有限样本核验

优先请求 Massive 提供样本或说明；取得用户授权的访问资格后才运行数据查询。下面是具体查询形状，不代表已经成功获取数据，也不包含密钥：

```text
GET https://api.massive.com/etf-global/v1/constituents
  ?composite_ticker=SPY
  &effective_date=2025-07-03
  &limit=5000
  &sort=constituent_ticker.asc
```

对 QQQ 重复，并抽查 `2025-07-03`、`2025-09-19/22`、`2025-12-19/22`、`2026-03-20/23`、`2026-10-23`；这些是起止和季度附近的覆盖探针，不预先断言每个日期都发生了成分调整。再取 `2025-06-30` 与 SEC 同期原申报交叉核对。每个请求必须读完全部分页、保留原始响应，核对返回日期，不接受查询旧日却返回当前名单。

需要供应方回答并用响应证明：

1. 每份基金快照是否完整，有无停更、缺日和退市证券遗漏；某股票消失是基金卖出、公司行动还是源数据缺失。
2. 处理日期的时区、每日首次可用时刻，以及事后更正是否覆盖旧记录；能否取得修订链和当时版本。只有日期的保守滞后方案仍须单独登记，不能声称已消除修订偏差。
3. 可选证券标识的实际覆盖、变更映射和历史代码保留情况；公司行动及交易状态仍需独立数据源核验。
4. 99 USD/月的精确授权范围、是否需要另购基础套餐、API 与本地研究存储权限。

在这些证据不足时，真实历史动态回测应保留缺口并停止正式验收。可以继续开发和验证合成场景，以及从现在开始冻结官方每日快照；这些工作不能补造已经错过的历史数据或改变旧研究的资格。

## 冻结证据和核查结果

新目录：`reports/dynamic-universe-audit-20261026-v1/issuer/`，由 Git 忽略。本次没有读取凭据、修改账户、修改已有报告或发出交易。

- `http-sources.parquet`：10 次公开 GET 的 URL、最终 URL、状态、响应头、UTC 采集时刻、原始响应实体及 SHA256；8 次 HTTP 200，2 次 HTTP 403。二进制 XLSX 不转换为文本业务表。
- `web-sources.parquet`：8 次搜索/网页工具实际返回的完整文本字节、方法、保存时刻、可取得的工具返回时刻及摘要。正文包含工具提取结果，不冒充原始 HTML/PDF，也不是首次公开时间。
- `current-holdings-inspection.parquet`：当前两基金解析日期和数量；`historical_weeks_verified=0`，不是把当前时点重复为历史。
- `filing-observations.parquet`：12 条 SEC 报告日期、接受时刻、申报日期及 accession；原文的 UTC 接受时刻保持不变，未认证首次公开时间。
- `provider-contract-inspection.parquet`：从 Finnhub 原始 HTML 的 OpenAPI 解析出的付费要求、请求参数和返回字段。
- `checks.parquet`、`artifacts.parquet`：来源正文摘要、Parquet/Zstandard、日期先后核查及完整文件清单。

本次只完成数据来源核查，不声称动态选股引擎、公司行动会计或滚动样本外回测已经完成。
