# 固定 513 股票长历史验证的数据来源核验

核验日期：2026-10-27。本文件仅记录官方文档及提供商工作人员的公开说明；没有读取凭据、调用市场数据 API 或运行回测。实际账户权限、逐股票覆盖和字段完整性仍以本轮冻结采集证据为准。

建议继续以 **Alpaca 原始 SIP 日线作为主采集源**，尝试取得 2016 年起行情，以 2016 年作为长窗口指标预热期，在覆盖允许时从 2017 年开展冻结规则的历史验证。官方免费计划支持这一行情范围，但尚不能据此断言 513 只股票的全部公司行动也完整覆盖到 2016 年。公司行动与证券身份检查应先于有效收益结论。

## Alpaca 的已确认范围

| 项目 | 官方说明及本轮用途 |
| --- | --- |
| 免费资格与历史长度 | 个人 Trading API 的 Basic 为免费默认计划，覆盖美国股票及 ETF，历史自 2016 年起，历史接口限额 200 次/分钟。SPY、QQQ 属于所述资产类别，逐标的实际可得数据仍需验证。[订阅表](https://docs.alpaca.markets/us/docs/about-market-data-api) |
| SIP 权限 | 免费账户可查询结束时间至少早于当前 15 分钟的 SIP 历史；最近数据与 latest/snapshot 的 SIP 权限不同。显式指定 `feed=sip`，不依赖账户相关的默认 feed。[官方 FAQ](https://docs.alpaca.markets/us/docs/market-data-faq) |
| 分页 | bars 的 `limit` 为 1–10,000，约束整页而非每个股票；结果先按股票、再按时间排序，返回不足 limit 也必须检查 `next_page_token`。[日线接口](https://docs.alpaca.markets/us/reference/stockbars) |
| 原始与复权 | `adjustment=raw` 为原始价格；`split`、`dividend`、`spin-off` 和组合复权含义不同。执行账本使用原始价格与独立公司行动，不用复权序列重建现金或股数。[日线接口](https://docs.alpaca.markets/us/reference/stockbars) |
| 名称映射 | `asof` 确定查询代码对应的实体，默认当前日期，可能把旧代码历史标成新代码；`asof=-` 禁止映射。它不是历史数据库版本时间，不能证明某日已可知；需显式固定并保存实体映射。[日线接口](https://docs.alpaca.markets/us/reference/stockbars) |

当前固定名单可能包含后来的 IPO、分拆后新公司或不同类别股票。自动名称映射可能让两个今天的代码共享一段旧历史。Alpaca 工作人员对 ADEA/XPER 的说明确认了这种行为；因此，不能将自动返回的旧行情直接等同于该证券当时独立上市、可同时持有。[官方人员答复](https://forum.alpaca.markets/t/shared-market-data-between-different-tickers/18302)

## 公司行动是主要覆盖风险

新接口 `GET /v1/corporate-actions` 支持拆股、现金及股票股息、分拆、现金/股票/混合并购、赎回、名称变化、无价值移除、配股、部分赎回、重组和资本利得分配等类型；省略 `types` 查询全部。`start/end` 为闭区间，文档以 `process_date` 描述区间及排序，不能直接当作除权日过滤。`limit` 为 1–1,000，默认 100，按全部记录计数并通过 `next_page_token` 翻页；遇 429 依响应限流头退避。[公司行动接口](https://docs.alpaca.markets/us/reference/corporateactions-1)

该接口当前文档没有承诺统一的最早历史日期，也未写出旧接口那样的 90 日最大查询跨度。2022 年发布说明只承诺**旧 Announcements 数据自 2020 年 4 月起**，而旧接口现已弃用、90 日限制属于旧接口；不能将这两个旧约束直接套到新端点，也不能将“行情自 2016 年起”解释成公司行动同样完整。[旧发布说明](https://alpaca.markets/blog/introducing-corporate-actions-api-announcements/)、[已弃用接口](https://docs.alpaca.markets/us/reference/get-v2-corporate_actions-announcements-1)

新接口不保证事件创建/可用时间；默认 `data_quality=complete` 会过滤部分尚未处理且字段不齐的记录，但已处理事件仍可能缺字段。`data_quality=all` 可用于保留未完成记录，不能因此视为已通过准入。查询无结果只说明该请求未返回事件，不能证明当时没有事件。[公司行动接口](https://docs.alpaca.markets/us/reference/corporateactions-1)

需要特别检查**价格调整因子与真实股数变化是否混淆**。2025 年官方工作人员处理过 APD、CAG、DHR、FMC、HPE、HSIC、IR、MET、VFC 等历史 split 问题，随后新增独立 `spin-off` 价格调整选项。这说明旧 split 条目可能涉及分拆或重组，不能仅凭返回比例就记入真实股数变化；该帖子是历史修复证据，不是今天仍有同样错误的断言。[官方修复说明](https://forum.alpaca.markets/t/incorrect-historical-data-of-stock-split-ratios/17839)

## 免费补充来源的适用边界

| 来源 | 可补充什么 | 不能默认解决什么 |
| --- | --- | --- |
| Tiingo Starter | 官方为 0 美元、30 年以上价格历史，500 个独立代码/月、50 请求/小时、1,000 请求/日、1 GB/月，可用于少量疑点交叉核验。[定价](https://www.tiingo.com/about/pricing) | 单月代码额度不足 513 股票再加基准；EOD 的 `divCash` 对应除息日，`splitFactor` 也可能代表分配调整，不能替代支付日或真实拆股账本。[EOD 字段](https://www.tiingo.com/documentation/end-of-day) |
| Tiingo 独立公司行动 | distributions 文档提供 `paymentDate`、`recordDate`、`declarationDate`，splits 提供 from/to 比例。 | 文档仍标注 Beta-enabled/企业授权；EOD entitlement 不等于已经开通 Beta。日期可能为空；未实测前不声称免费账户能补齐支付日。[分红接口](https://www.tiingo.com/documentation/corporate-actions/dividends)、[拆股接口](https://www.tiingo.com/documentation/corporate-actions/splits) |
| Yahoo Finance | 官方页面可查看历史价格、分红及拆股，适合作疑点人工核对。[历史数据帮助](https://help.yahoo.com/kb/finance/historical-prices-adjusted-close-sln2311.html) | 官方下载目前要求 Gold 订阅；本轮不能把它称作免费批量下载服务。复权收盘价包含拆股和分红调整，不是原始成交价格。[复权定义](https://in.help.yahoo.com/kb/finance/adjusted-close-sln28256.html) |
| Alpha Vantage | 可用作有限的免费 API 研究入口，标准免费额度 25 请求/日。[支持页](https://www.alphavantage.co/support/) | 全长日线复权及 split/dividend 接口 `TIME_SERIES_DAILY_ADJUSTED` 标记为 Premium，不作为本轮免费补齐方案。[接口文档](https://www.alphavantage.co/documentation/) |

本次没有找到 Stooq 对本项目所需的原始价格、支付日、完整公司行动及实体连续性给出的足够官方合同，因此不将其作为执行账本的替代源。发行方公告和 SEC 文件仍可补核具体事件，逐事件证据应与供应商原字段并存，而非覆盖原始响应。

## 本轮采集及验证建议

以下是项目实施建议，不是提供商保证：

1. 冻结原 513 名单、两个候选参数和匹配成本的 QQQ 基准。主批次按原始 SIP 日线采集，保存参数、`asof`、抓取时间、页令牌链及响应证据，正规表归一化到 Parquet；不改变旧快照。
2. 先按股票、年份统计首末行情、交易日缺口、重复行、价格跳变以及已知事件正例。IPO 前无行情不补值；只有确认真实上市后并满足原有指标预热长度才可进入当周评分。名单仍固定 513，逐周可评分数量应单独报告。
3. 对名称变更和重组保留实体映射与生效日期；不把同源旧历史重复算成两个独立可交易证券。优先核对分拆/并购复杂事件，不能把非整数比例或价格调整因子一概记成增减股数。
4. 股息分清除息权益、应收和支付现金；支付日未知时保留未解决状态，不能自动在除息日增加可投资现金。拆股同步处理持股、成本与止损基准；分拆、退市、合并、停牌需要事件证据与明确估值/结算规则。缺失行情不能成为虚构成交或静默删除证券的理由。Alpaca FAQ 也将 OTC、inactive、halt 列为无行情的可能原因。[FAQ](https://docs.alpaca.markets/us/docs/market-data-faq)
5. 先验证公司行动覆盖，再选择可交付的连续验证区间；覆盖不足的股票/年份和受影响持仓路径显式保留。允许如实报告局部覆盖或不完整结果，不以“无返回”补成无事件。
6. 两个候选是在 2025–2026 年表现之后选出的。向 2017 年扩展可检验其他市场阶段，但仍使用后来挑出的策略和当前幸存者名单。滚动窗口只使用窗口前的数据做当时指标；冻结参数的历史滚动检验与真正未见、按时间向前形成的样本外验证必须分开命名，不能借重新划分旧数据消除策略选择偏差。

这项研究只扩展离线数据与验证证据，保持 `source=alpaca`、探索范围和 `trade_eligible=false`；不会替代 IBKR 账户或订单事实，也不会重置任何历史账户或研究记录。

## 补充：DOW、SKYD、NBIS 的证券身份与交易时段

本节于同日根据主流程发现的覆盖异常追加。下列官方事实用于解释缺口和约束准入，不是对供应商响应的自动修正。

### DOW：2019 年分拆后的 Dow Inc.

发行方当前 FAQ 明确 NYSE 代码 `DOW`、CUSIP `260557103`；SEC 留存的 2019-06-30 13F 和 2025 年代理投票记录也将该 CUSIP 对应到 Dow Inc. 普通股，支持其 2019 年独立上市后至 2025 年的证券身份连续性。[Dow FAQ](https://investors.dow.com/en/investor-resources/stockholder-faqs/default.aspx)、[2019 年 SEC 持仓记录](https://www.sec.gov/Archives/edgar/data/883803/000088380319000003/InfoTable-2019-06-30.xml)、[2025 年 SEC 投票记录](https://www.sec.gov/Archives/edgar/data/1469192/000102140825003887/ProxyVotingTable.xml)

Dow 官方确认 **2019-04-01 收盘后完成分拆分配，2019-04-02 开始 DOW 正常交收交易**；每三股 DowDuPont 分配一股 Dow，碎股另付现金。此前从 2019-03-20 开始的是 `DOW WI` 的 when-issued 交易，不能无说明地与正常交易混用。[分拆完成公告](https://investors.dow.com/en/news/news-details/2019/Dow-completes-separation-from-DowDuPont/default.aspx)、[发行生效公告](https://investors.dow.com/en/news/news-details/2019/DowDuPont-Announces-Effectiveness-of-the-Form-10-Registration-Statement-for-New-Dow/default.aspx)

因此，2016–2018 年没有这一新证券的独立普通交易历史是合理的；**2019-04-02 后到 2025 年仍全部无数据，不能解释成尚未上市**。主流程观察到不同 `asof` 请求结果有差异，支持继续调查提供商实体映射，而不是从固定名单删除 DOW。可在记录明确的查询参数、重叠日期对照和身份依据后使用同一 Dow Inc. 的已验证行情；不得把 2017 年前 The Dow Chemical Company 的旧 DOW 或 DowDuPont 的 DWDP 自动拼接为本证券的早期可交易历史。

### SKYD：2025 年首先使用 PSKY，不是 SKYD

发行方确认 Paramount Global 与 Skydance 于 **2025-08-07** 合并完成，新公司 Class B 股票当天以 **PSKY** 在 Nasdaq 开始交易。2026-10-06 发行方公告又确认收购 Warner Bros. Discovery 完成后，Skydance Class B 股票改以 **SKYD** 在 NYSE 交易。[2025 年合并完成公告](https://ir.paramount.com/news-releases/news-release-details/skydance-media-and-paramount-global-complete-merger-creating)、[2026 年收购及代码公告](https://ir.paramount.com/news-releases/news-release-details/paramount-completes-acquisition-warner-bros-discovery-creating)

因此，“2025-06 之前没有当前新公司行情”与新股票时间线相符，但必须保存 `PSKY -> SKYD` 的具体实体/代码映射；**不能将 2025-08-07 称为 SKYD 代码首次交易日，也不能用更早 PARA/PARAA 行情直接代替新公司股票**。2025 年交易包含现金/股票对价选择及按比例分配，旧股持仓转换需要单独事件处理；当前研究如未建模该过程，就不能靠拼接名称让它跨越合并。[交易条款与选择期限公告](https://ir.paramount.com/news-releases/news-release-details/paramount-and-skydance-announce-anticipated-closing-date)

### NBIS/YNDX：长期停牌不能由稠密日线抹去

交易所给出的准确时间为：

| 事件 | 官方日期与含义 |
| --- | --- |
| Nasdaq 停牌 | **2022-02-28 06:38 ET**，当时名称 Yandex N.V.、代码 YNDX，末次成交价 18.94 USD。[Nasdaq 原公告](https://ir.nasdaq.com/node/104671) |
| 更名与代码变更 | 2024-08-20 公告完成更名；**2024-08-21 起 NBIS**，CUSIP 和 ISIN 不变，当时 Class A 股仍在停牌。[发行方更名公告](https://nebius.com/newsroom/nebius-group-n-v-announces-official-name-change-and-new-ticker-symbol) |
| Nasdaq 复牌 | **2024-10-21 09:00 ET**，交易所公告明确承接上述 2022 年停牌。[Nasdaq 复牌公告](https://ir.nasdaq.com/node/108131) |

OTC 不是已核实的替代交易场所。Yandex 的 2022 年 20-F 仅说若最终被 Nasdaq 退市，股票“可能”适合 OTC 交易，且明确不保证券商做市、取得 OTC 代码或美国投资者能够买入；该报告同时说明 Moscow Exchange 在 2022 年 3 月末恢复部分交易，但存在国际结算和投资者限制。[SEC 20-F](https://www.sec.gov/Archives/edgar/data/1513845/000155837023006319/yndx-20221231x20f.htm)

主流程报告当前映射下 NBIS 历史仅缺少约 43 个会话，这与官方 Nasdaq 长停牌事实存在明显冲突。尚无官方证据证明停牌期存在可直接用于本项目的连续美国 OTC 执行行情；不能据日线密度推定可交易，也不能用 MOEX 行情填入美国 USD 账户。应保留原始记录并隔离停牌区间，核对数据身份、场所及价格性质。若停牌前确有持仓，必须保留持仓与风险状态，拒绝在停牌内虚构退出成交；复牌后的指标预热也不能把两年半停牌压缩成无缝连续的交易日。

主流程随后核对原始响应，确认停牌期间有 622 条 `close=18.94`、`volume=0` 的占位记录。这解释了表面稠密的记录数，并不构成可执行成交证据；应同时使用成交量和上述显式停牌区间阻断报价，保留原始占位记录及核验结果。该记录数来自本轮主流程数据核验，不是上述官方网页提供的统计值。

## 补充：EXE/CHK 重组新股与 SMCI 场所缺口

本节仅针对主流程新增的两个身份疑点，不扩大其他股票的研究范围。

### EXE：可继承 2021 年新 CHK，不能继承破产前旧股

Chesapeake 于 **2021-02-09** 完成 Chapter 11 重组；发行方公告明确原有普通股和优先股当天注销。其 2023 年年度报告进一步确认旧股注销时没有任何回收，同时发行继任主体的新普通股。旧 CHK/CHKAQ 与新 CHK 不是可通过拆股比例连续连接的同一股东权益。[重组完成公告](https://investors.expandenergy.com/news-releases/news-release-details/chesapeake-energy-corporation-successfully-emerges-financial)、[2023 年报 Item 5 与注释 12](https://investors.expandenergy.com/static-files/793994a5-5592-4bd4-b800-bf41e22b6217)

**新 CHK 的正常交易起点为 2021-02-10**。2021 年完成公告使用“预计”措辞，但发行方事后的 2022 年 DEF 14A 明确把该日列为破产后普通股在 Nasdaq 重新上市日，因此这里的起点有事后发行方确认。[2022 年代理声明，2021 Performance Highlights](https://www.sec.gov/Archives/edgar/data/895126/000110465922052784/tm2210080d1_def14a.htm)

Chesapeake 与 Southwestern 的合并于 **2024-10-01** 完成，发行方更名为 Expand Energy；当天仍使用 CHK，**2024-10-02 开盘起使用 EXE**。应保存新 CHK 到 EXE 的代码映射和合并事件，不能使用被并购方 SWN 的旧价格替代 EXE 历史。[发行方合并完成公告](https://investors.expandenergy.com/news-releases/news-release-details/chesapeake-energy-and-southwestern-energy-complete-merger-and)

本轮处理建议：保留供应商映射返回的全部原始响应，但 **2021-02-10 前的记录不准入当前 EXE 的行情、指标预热或回测成交**；缺少前段并非需要填补的上市历史。如果另有研究真正持有破产前旧股，应独立结算其注销损失，不能自动转成新股或以名称连续性抹去损失。以上是依据证券身份做出的准入建议；主流程观察的 156 个缺价/零成交量会话属于供应商数据核验结果，不是官方对事件长度的统计。

### SMCI：2018–2020 年为 Nasdaq 至 OTC 的场所切换

| 事件 | 已确认日期与含义 |
| --- | --- |
| Nasdaq 暂停交易 | **2018-08-23 开盘起**；此前最后一个正常 Nasdaq 交易日为 2018-08-22。 |
| OTC 报价 | 发行方 2019 年提交的年度报告明确，自上述 Nasdaq 暂停日起已在 OTC 报价，继续使用 SMCI。 |
| 正式 Nasdaq 退市 | **2019-03-22**；这与 2018 年暂停交易日期不同。 |
| Nasdaq 重新上市 | **2020-01-14**，继续使用 SMCI；2020 年年度报告确认已发生。 |

上述暂停、OTC 和退市时间来自发行方 2019 年 SEC 文件；重新上市由 2020 年 SEC 文件确认。[2019 年提交的年度报告 Item 5](https://www.sec.gov/Archives/edgar/data/1375365/000137536519000039/smci-2017630x10kxa.htm)、[2020 年度报告 Item 5 与 Nasdaq Relisting](https://www.sec.gov/Archives/edgar/data/1375365/000137536520000064/smci-2020630x10k.htm)

因此，**2018-08-23 至 2020-01-13 不能作为正常 Nasdaq/SIP 可执行历史使用，但不能描述成 SMCI 在所有市场完全停止交易**。发行方明确 OTC 报价可能只是交易商间报价，不一定代表实际成交；只验证有 OTC 报价仍不足以补齐本项目的交易价格、流动性和成本。主流程报告的 349 条零成交量记录需保留并隔离，不能按旧价格补出零收益、假成交或平滑指标，也不能把 2020 年重新上市错误建模成新股。若之前已有持仓，应保留该持仓和风险状态，显式报告 OTC 行情及估值覆盖缺口；重新上市后的筛选须重新满足有效行情的指标预热要求。

## 补充：现金分红支付日的免费来源与历史起点

### Alpaca 返回金额不代表支付日已完整

主流程对本轮原始快照的逐年核验发现：2016–2018 年现金分红均无 `payable_date`；2019 年为 70/1,461 条有该字段，2020 年为 1,221/1,456 条，2021 年以后返回记录均有该字段。这是本轮请求的字段覆盖统计，不是对提供商全球历史的保证；字段存在也不等于日期正确。早期部分记录同时缺 CUSIP，证券身份应另行核验，不能由缺失支付日推导为没有分红。

本轮不能仅凭上述统计判定所有早期历史不可用：主流程随后用无凭据公开请求 `GET https://api.nasdaq.com/api/quote/{symbol}/dividends?assetclass=etf|stocks&limit=5000`，取得 QQQ 58 条、最早 2012 年；AAPL 83 条、最早 1988 年；FANG 34 条、最早 2018 年，并保存 `payment-probes.parquet`。这是主流程实测证据，本研究子任务未重复调用该市场接口。它表明免费补齐早期支付日仍有可行路径，**本节不将 2020-07-01 或其他日期宣布为已确定的财务验证起点**。原定 2017 方案的预检失败记录仍应保留；最终区间依据事件覆盖决定，不能依据尚未计算的收益选择。

### Nasdaq 页面与 API 的能力边界

Nasdaq 官方 FAQ 将 Dividend History 描述为 Nasdaq 上市股票的历史分红，明确金额不作拆股复权；其页面还提示可能合并普通和特别分红、混入优先证券记录，OTC/OTCBB 不在该功能覆盖内。本次未找到对上述网页内部 quote API 的十年全覆盖、分页、稳定限额或完整性作出承诺的正式文档。单只股票实际返回超过十年可作为该请求的事实，不能推广成固定 513 股票都必然完整；NYSE 代码是否返回可用内容应保存实测结果，不根据 FAQ 直接否定或直接假设可用。[官方 FAQ](https://www.nasdaq.com/market-activity)、[官方分红页说明](https://www.nasdaq.com/market-activity/stocks/api/dividend-history)

明确承诺长期历史和 `Payment Date` 字段的是另一项 **Nasdaq Daily List** 产品：分红记录可追溯到 1999-05-24，但官方将其列为 Premium，需相应协议与准入，不能与免费网页接口混称。[Daily List 产品说明](https://www.nasdaq.com/products/data/equities/corporate-action-solutions)、[Data Link 字段与付费属性](https://data.nasdaq.com/databases/NDL/documentation?anchor=product-overview)

实施上应逐条按已核验的证券身份、除息日和未复权金额匹配，保留每次原始响应及未匹配、冲突、重复记录。`limit=5000` 请求成功本身不证明没有截断；需要检查返回结构、记录数、最早日期与已知发行方事件。原始金额、拆股调整后的金额和特别分红不能直接混用；支付日只补到一条规范事件，不应因提供商 ID 不同而重复入账。

### Invesco 可以直接裁决 QQQ 的 2022 年重复记录

当前 [Invesco ETF Tax Center](https://www.invesco.com/us/en/accounts/tax-center/etf-tax-center.html) 公开以下年度 1099 数据工作簿，可无凭据下载并批量解析发行方记录。这是官方发布格式；归一化后的项目数据仍应写入 Parquet。

| 年度 | 税务中心实际链接 |
| --- | --- |
| 2020 | [2020 年分配文件](https://www.invesco.com/content/dam/invesco/us/en/documents/tax-document/ce-ici-primary-and-secondary-distribution-file-and-nra-file-ivz-etf-2020.xlsx) |
| 2021 | [2021 年分配文件](https://www.invesco.com/content/dam/invesco/us/en/documents/tax-document/ce-ici-primary-and-secondary-distribution-file-and-nra-file-ivz-etf-2021.xlsx) |
| 2022 | [2022 年分配文件](https://www.invesco.com/content/dam/invesco/us/en/documents/tax-document/ce-ici-primary-and-secondary-distribution-file-and-nra-file-ivz-etf-2022.xlsx) |
| 2023 | [2023 年分配文件](https://www.invesco.com/content/dam/invesco/us/en/documents/tax-document/ce-ici-primary-and-secondary-distribution-file-and-nra-file-ivz-etf-2023.xlsx) |
| 2024 | [2024 年分配文件](https://www.invesco.com/content/dam/invesco/us/en/documents/tax-document/ce-ici-primary-and-secondary-distribution-file-file-ivz-etf-2024-02-10-2025.xlsx) |
| 2025 | [2025 年分配文件](https://www.invesco.com/content/dam/invesco/us/en/documents/tax-documents/ICI-Primary-and-Secondary-and-NRA-File-IVZ-ETF-2025.xlsx) |

本研究直接读取 2022 年文件：`xl/worksheets/sheet1.xml` 第 1786 行为 `Invesco QQQ Trust`、CUSIP `46090E103`、代码 QQQ；登记日 **2022-09-20**、除息日 **2022-09-19**、支付日单元格 `I1786=44865`，按该工作簿 Excel 日期序列对应 **2022-10-31**，每股金额 **0.51856 USD**。因此，本轮 Alpaca 同除息日同金额的两条记录不能双计，`2022-09-23` 支付日与发行方这笔记录不符。保留原始冲突记录，以发行方日期形成有证据的规范事件。同期 SEC 留存的花旗票据也记载该金额于 2022-09-16 宣布、2022-10-31 支付，可作交叉核验，但它不是 QQQ 发行方本身的公告。[同期 SEC 存档](https://www.sec.gov/Archives/edgar/data/831001/000095010322017807/dp182490_424b2-us2207102.htm)

QQQ 的旧 Invesco 产品页搜索索引还可见 2016 年四笔支付日与金额；当前直接访问该旧路径会跳转首页，不能把搜索缓存冒充本次已经保存的完整原始数据。新产品页提供日期区间和 `View since inception`，但本子任务未验证它的全历史批量导出。早于 2020 年的 QQQ 现金日期可继续用 Nasdaq 返回与发行方存档交叉核验，不能仅按“通常次月底支付”推算所有历史日期。[当前产品页](https://www.invesco.com/us/en/financial-products/etfs/invesco-qqq-trust-series-1.html)、[旧产品页索引来源](https://www.invesco.com/us/financial-products/etfs/product-detail?audienceType=investors&msockid=3ce7265f5fab6a520f8b300f5e676b13&productId=QQQ&ticker=QQQ)

### 个股官方来源可补核，但需要逐事件覆盖

例如 Apple 的公开 IR 分红历史可直接读取 2016 年四笔支付日（02-11、05-12、08-11、11-10）及当时未复权金额，适合核验 Nasdaq/Alpaca 匹配；该页没有单独的除息日列，不能把登记日误作除息日。[Apple 官方分红历史](https://investor.apple.com/dividend-history/default.aspx)

SEC 提供无凭据、可批量下载的申报历史和 XBRL 数据，但官方 API 说明并未承诺完整的逐证券现金分红事件表；XBRL 聚合限于标准标签且适用于整个申报实体。它可用于定位发行方公告和解决疑点，不能仅凭 `companyfacts` 返回某个股息指标就认定每次实际支付日均已覆盖。[SEC API 文档](https://www.sec.gov/search-filings/edgar-application-programming-interfaces)

最终现金账户历史边界取决于两套策略与 QQQ 基准所用事件的完整性、实体匹配和冲突裁决。缺失日期保持未解决，不在除息日提前释放现金，也不通过忽略分红来把不完整输入标成财务验证通过。若免费来源仍无法补齐，则保留长区间预检失败与覆盖表，再按数据边界收窄；价格历史仍可保留为指标研究输入，不能混称为已通过完整现金账本验证。

## 后续实采的覆盖裁定

主流程在观察收益之前登记了最终评价区间 **2020-07-06 至 2025-06-30**，以支付日覆盖足够后的第一个完整半年的首个完整交易周开始。原 2017 起点及其预检失败保留；本轮不包含 2020 年初暴跌。此裁定来自本地冻结采集证据，不是提供商对历史完整性的保证。完整规则、固定 513 股票边界及连续账户口径见 [长历史验证说明](../research/long-history-validation.md)。

实际价格覆盖从 2016-01-04 开始，修正证券身份和停牌占位后的快照有 1,173,382 行、514 个有观察值的代码，其中包括 SPY、QQQ；SKYD 仍留在 513 股票名单中，但在评价区间没有可准入历史。261 次周筛选各记录完整 513 行。评价区间的 QQQ 共 21 笔分红已与上述 Invesco 工作簿核对；全股票仍有 42 条已知未完全处理的公司行动，须逐路径核查实际权益和在途订单暴露。零实际暴露不代表供应商事件覆盖完整。
