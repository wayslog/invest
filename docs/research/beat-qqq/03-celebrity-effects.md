# 名人效应与跟单交易：能否在扣除成本后跑赢 QQQ（2023—2026-10）

## 1. 研究信息与时效规则

- 研究日期：2026-10-27；价格类数据截至 2026-10-26 收盘。
- 基准：QQQ 买入并持有（分红再投资），不更换基准。金额单位为 USD。
- 账户约束：本金 5,000 USD、IBKR 账户、W-8BEN（美国侧股票资本利得不征税，股息预扣
  10%）、只交易美股和美股 ETF、只用免费数据、净值不高于 2,500 USD 时清仓并终止
  （见 [本金阶梯风控与 W-8BEN 税后口径](../principal-risk-and-tax.md)）。
- 范围：本文只复核文献和公开数据，不改动代码、配置或已冻结的研究记录。

时效与口径规则：

1. 只采用 2023 年以后发表的研究、数据和报道。2023 年以前的研究只在近年被重新检验过，
   或者作为背景时才提及，并注明年份。
2. 每个业绩数字都标明区间和截止日。找不到原始数据的标“二手来源，未核实”。
3. 标“本文自算”的价格类数字使用 Yahoo Finance 免费日线临时计算。收益用复权收盘价，
   包含分红再投资，ETF 收益已扣除管理费，但没有扣佣金、滑点和税。这些数据没有写入项目
   的 Parquet 数据，也不构成正式回测记录。抽查结果：NANC/QQQ 今年以来 +11.99%/+16.33%，
   近一年 +12.12%/+15.95%，与 [stockanalysis.com](https://stockanalysis.com/etf/compare/nanc-vs-qqq/)
   页面一致。
4. “相对 QQQ”一律指同一区间的简单收益差，单位为百分点（pp）。起点不同的数字不能直接比较。
5. 税务影响：QQQ 近 12 个月的分配率约 0.43%（本文自算），10% 预扣带来的拖累约
   0.04 pp/年，不影响结论。OMAH、ACKY 这类高分配产品近 12 个月分配率约 15%–16%，
   预扣影响取决于分配的性质（普通股息还是资本返还），本文未核实。

## 2. 结论摘要

1. **跟随国会交易没有跑赢 QQQ。** 两只真实运作的跟踪 ETF 自 2023-02-07 成立至 2026-10-26：
   NANC（民主党）+103.4%，GOP（原 KRUZ，共和党）+75.9%。同期 QQQ +134.8%，SPY +93.3%。
   NANC 只跑赢标普，落后 QQQ 31.4 pp。学术证据方向一致：Chen & Sacerdote（NBER，2026）
   用 2012—2023 年全体议员数据发现，STOCK Act 之后议员组合跑输或至多持平基准；一篇覆盖
   2020—2024 年的硕士论文（二手来源，未核实）发现，按披露日模仿议员买入得到的 α 为负。
2. **“领导人超额”无法通过披露复制。** Wei & Zhou（NBER，2025-11）发现议员升任领导后，
   比匹配议员每年多赚约 47 pp。但样本只有约 20 人，截至 2021 年；超额来自交易时点
   （例如监管行动前卖出），论文也没有检验按披露跟单能否获利。最长 45 天的披露滞后、
   41% 的逾期申报（2012—2022 样本）以及正在推进的禁止交易立法，使这一信号不可执行。
3. **13F 克隆产品在 2023 年以后全部跑输 QQQ。** 自 2023-01 起：GURU +93.1%、GVIP +133.3%，
   QQQ +173.2%。OMAH（伯克希尔持仓加备兑期权）自 2025-03-05 +15.4%，同期 QQQ +43.1%。
   ACKY（Ackman 持仓加备兑期权）自 2025-09-09 +0.3%，同期 QQQ +23.4%。巴菲特本人的
   BRK-B 同期 +77.6%。13F 持仓可能已有 135 天之久，也看不到空头和期权；2023 年以后
   缺少有效的学术证据。
4. **明星经理只能事后挑出赢家。** ARKK 自 2023-01 +164.2%，落后 QQQ 9.0 pp，最大回撤
   −39.6%，QQQ 为 −22.8%；近五年 ARKK −31.4%，QQQ +93.6%。ARKW（+307.5%）和
   IVES（成立 1.4 年，领先 19.8 pp）事后看跑赢了，但事前无法挑出来。
   Morningstar 曾把 ARKK 列为 2014—2023 年毁灭投资者财富第三多的基金。“反向 Cramer” SJIM
   存续期间亏损约 15%，同期 SPY +27%；SJIM 和正向的 LJIM 都已清盘。
5. **社交媒体和散户羊群行为对跟随者不利。** WallStreetBets 的尽调帖在 GameStop 事件之后
   失去了预测力（RFS，2024）。56% 的财经网红属于“反技能”（2023 年工作论文）。
   Roundhill MEME ETF 自 2025-10-08 −34.8%，同期 QQQ +17.0%。2024-05 “Roaring Kitty”
   回归时，GME 两天上涨 179%，随后六周下跌 49%，同期 QQQ +7.4%。
6. **政治人物的言论能制造极端单日行情，但事前无法交易。** 2025-04-09 特朗普发帖
   “THIS IS A GREAT TIME TO BUY”后宣布暂停关税，QQQ 当日上涨 12.0%；此前 4 月 2—8 日
   QQQ 下跌 12.6%。DJT 自 2024-03-26 上市以来下跌 89.4%，同期 QQQ +62.8%。
   政治主题 ETF MAGA 自 2023-01 +53.5%，同期 QQQ +173.2%。
7. **指数纳入效应在 2024—2025 年以公告后跳空的形式回来了，但普通投资者吃不到，而且纳入
   后会反转。** Greenwood & Sammon（JF，2025）显示，长期来看纳入效应已降到 1% 以下。
   本文自算了 22 只 2024—2025 年 S&P 500 新成分股（相对 QQQ）：公告后的隔夜跳空平均
   +5.8%，这部分无法获得；在公告后首日开盘买入、生效前一日收盘卖出，平均 +1.3%，
   中位数 +0.1%，2025 年为正，2024 年为负；生效后 20 个交易日平均 −4.6%。
8. **对本项目的判断：** 在“免费数据 + 5,000 USD + 只做多美股/ETF”的约束下，没有一个
   名人或跟单信号既可执行、又有稳定证据跑赢 QQQ，因此都不进入主路线。只有 S&P 500
   纳入公告窗口可以列为“预注册 paper 观察”候选（第 4.2 节），即便有效，贡献也很小。

## 3. 证据表

强度分级：**强**表示同行评审论文，或期限至少 3 年、来自真实产品的完整价格事实；
**中**表示工作论文、单一产品或期限较短；**弱**表示商业机构报告、学生论文、二手转述或
个别案例。“结果”一栏除特别说明外均为同区间收益。

### 3.1 国会议员交易（STOCK Act）

| 对象 | 方法 | 样本期 | 相对 QQQ / 标普的结果 | 披露延迟 | 强度 | 链接 |
| --- | --- | --- | --- | --- | --- | --- |
| NANC（民主党议员跟踪 ETF） | 真实运作的 ETF，按民主党议员及家属披露的持仓构建；费率 0.74%（二手来源，未核实）；前两大持仓 NVDA 10.5%、MSFT 7.5%（2026-04，二手来源，未核实） | 2023-02-07—2026-10-26 | +103.4%（年化 21.0%）；QQQ +134.8%（年化 25.8%），SPY +93.3%；**落后 QQQ 31.4 pp**，领先 SPY 10.1 pp；2026 年以来 +12.0%，QQQ +16.3%（本文自算） | 法定最长 45 天，基金只能在披露后调仓 | 中 | [Yahoo NANC](https://finance.yahoo.com/quote/NANC/)；[stockanalysis](https://stockanalysis.com/etf/compare/nanc-vs-qqq/)；[24/7 Wall St](https://finance.yahoo.com/markets/stocks/articles/invested-congressional-trading-etfs-launch-120515368.html) |
| GOP（原 KRUZ，共和党议员跟踪 ETF） | 同上；2025-03 改名；2024-08 起由 Tidal 接管顾问职能；据 2026-08-17 报道，Unusual Whales 已结束合作 | 2023-02-07—2026-10-26 | +75.9%；**落后 QQQ 58.9 pp**，落后 SPY 17.4 pp；2026 年以来 +19.2%，领先 QQQ（本文自算） | 同上 | 中 | [Yahoo GOP](https://finance.yahoo.com/quote/GOP/)；[Crypto Briefing](https://cryptobriefing.com/unusual-whales-subversive-political-etfs-split/) |
| Chen & Sacerdote，NBER w35041（2026-04） | 全体议员及直系亲属的股票交易 | 2012—2023 | STOCK Act 之后，议员组合跑输或至多持平市场基准；持仓跟随专业机构推荐，交易时点跟随散户社交媒体情绪，作者称之为“跟随公开信号” | 按交易日计算，相当于没有滞后时的上限 | 中—强（全样本工作论文，未经同行评审） | [NBER](https://www.nber.org/papers/w35041) |
| Wei & Zhou，NBER w34524（2025-11） | 约 20 名在升任领导前后都有交易的议员，与相似议员匹配，比较买入持有超额收益 | 1995—2021（样本期来自二手来源） | 升任后比匹配议员每年高约 47 pp；本党控制议院时收益更高；会在监管行动前卖出；STOCK Act 没有消除这一优势 | 按交易日计算；**没有检验公众按披露跟单** | 中（样本小，截至 2021 年） | [NBER](https://www.nber.org/papers/w34524)；[哈佛公司治理论坛](https://corpgov.law.harvard.edu/2025/12/10/political-power-personal-portfolios-and-risks-for-corporate-governance/)；[Fortune](https://fortune.com/2025/12/07/congress-stock-market-trades-leadership-outperformance-trading-ban-bill-discharge-petition) |
| Islam，密西西比州立大学博士论文（2025） | 手工收集的公开市场交易 | 2012—2022 | 41.08% 的交易超过法定期限才披露；逾期披露的买入异常收益更高，卖出亏损更小 | 揭示了逾期披露问题 | 中（博士论文） | [MSU](https://scholarsjunction.msstate.edu/td/6652) |
| 哥德堡大学硕士论文 “Trading on the Hill” | 以披露日为事件的事件研究，加上日历时间组合（FF3/FF5） | 2020-01—2024-12，众议院 5,225 个买入事件 | 20 日和 40 日累计异常收益显著为负；扣成本后等权组合的三因子 α 约 −40 bp/月；负值集中在民主党议员（二手来源，未核实：原页面无法访问） | 从披露日起算，即跟随者实际可得的口径 | 弱 | [GUPEA](https://gupea.ub.gu.se/items/0e1aeba3-3354-493e-b192-bee7df3c107c) |
| Unusual Whales 2024 年度报告（据 Fortune 报道） | 用可追踪持仓近似估算 | 2023-12-29—2024-12-30 | 民主党平均约 +31%，共和党约 +26%，标普 +24.9%（QQQ 2024 年 +25.6%）；Pelosi 约 +70.9%（大量期权）；约 100 名活跃交易者中约一半跑赢标普 | 按交易日估值，跟随者拿不到这个收益 | 弱 | [Fortune](https://fortune.com/2025/01/08/congress-stock-trading-pelosi-2024) |
| Unusual Whales 2025 年度报告（据 24/7 Wall St 报道） | 同上 | 2025 年 | Pelosi +20.1%，标普 +16.6%，排名第 28；QQQ 2025 年 +20.8%，与 Pelosi 基本持平。两党平均分别为共和党 17.3%、民主党 14.4%（二手来源，未核实） | 同上 | 弱 | [24/7 Wall St](https://247wallst.com/investing/2026/07/06/trump-vs-pelosi-who-made-more-money-in-the-stock-market-last-year/) |
| Lambda Finance 2025 年跟踪 | 311 个按议员回测的组合 | 2025 年 | 32.2% 跑赢标普，2024 年为 42.5%（二手来源，未核实） | 未说明 | 弱 | [Lambda Finance](https://www.lambdafin.com/articles/congressional-stock-trading) |

### 3.2 13F 跟单与克隆产品

| 对象 | 方法 | 样本期 | 相对 QQQ / 标普的结果 | 披露延迟 | 强度 | 链接 |
| --- | --- | --- | --- | --- | --- | --- |
| GURU（Global X Guru，费率 0.75%） | Solactive Guru 指数：从持仓集中、换手率低的对冲基金 13F 中选取头部持仓，等权，每季度再平衡 | 2023-01—2026-10-26 | +93.1%；QQQ +173.2%，SPY +109.8%；**落后 QQQ 80.1 pp**；近五年 +30.1%，QQQ +93.6%（本文自算） | 季末后最多 45 天；持仓最长可能已有约 135 天 | 中—强 | [Global X](https://www.globalxetfs.com/funds/guru/)；[说明书](https://wp.globalxetfs.com/content/files/GURU-factsheet.pdf) |
| GVIP（高盛 Hedge Industry VIP） | 基本面对冲基金前十大持仓中出现最频繁的约 50 只股票 | 2023-01—2026-10-26 | +133.3%，**落后 QQQ 39.9 pp**；分年：2023 年 +39.1%（QQQ +54.9%），2024 年 +29.8%（+25.6%），2025 年 +25.3%（+20.8%），2026 年以来 +3.1%（+16.3%）（本文自算）。领先的年份不稳定 | 同上 | 中—强 | [Yahoo GVIP](https://finance.yahoo.com/quote/GVIP/) |
| 高盛 VIP 研究篮子（不可直接投资） | 同上 | 2001—2025-08 | 2025 年截至 8 月 +16%，标普约 +10%；自 2001 年起年均约 15%，标普 11%；未扣交易成本（二手来源，未核实） | 同上 | 弱 | [Benzinga](https://www.benzinga.com/markets/equities/25/08/47406673/top-hedge-fund-picks-from-goldman-sachs-outperform-sp-500-powering-16-gains-in-2025) |
| OMAH（VistaShares 伯克希尔精选收益，费率 0.95%） | BRK.B 加伯克希尔前 20 大公开持仓，叠加期权收入策略，按月分配 | 2025-03-05—2026-10-26 | +15.4%；QQQ +43.1%，SPY +33.9%；**落后 QQQ 27.7 pp**（本文自算） | 13F 滞后 | 中（期限短，且包含备兑期权的拖累） | [ETF Central](https://www.etfcentral.com/fund/OMAH) |
| ACKY（VistaShares 跟踪 Ackman，费率 0.95%） | Pershing Square 的 13F 持仓加备兑期权 | 2025-09-09—2026-10-26 | +0.3%；QQQ +23.4%；**落后 23.1 pp**（本文自算） | 13F 滞后 | 弱—中（期限短） | [stockanalysis](https://stockanalysis.com/etf/acky)；[MarketScreener](https://ca.marketscreener.com/news/vistashares-launches-etf-tracking-stock-bets-of-hedge-fund-activist-bill-ackman-ce7d59dfde8ef624) |
| BRK-B（直接持有巴菲特的公司） | 价格事实 | 2023-01—2026-10-26 | +77.6%，**落后 QQQ 95.6 pp**（本文自算） | 无 | 强 | [Yahoo BRK-B](https://finance.yahoo.com/quote/BRK-B/) |
| Pershing Square Holdings（Ackman 本人管理的基金，伦敦上市，不在本项目可交易范围内） | 官方事实表，NAV 口径 | 截至 2025-12-31 | 2025 年 NAV +20.9%，标普 +17.9%（QQQ +20.8%）；3 年年化 NAV +18.9%，标普 +22.9%（QQQ 3 年年化 +32.9%，本文自算）；股价相对 NAV 折价 24.1% | 不适用（这是基金本身，不是克隆） | 中 | [PSH 2025-12 事实表](https://pershingsquareholdings.com/wp-content/uploads/2026/01/PSH-Fact-Sheet-December-2025-Website.pdf) |
| Schroeder & Posch（2024-03）论文 | 在 13F 申报日收盘时更新克隆组合，覆盖 3,643 只基金 | 2013—2023 | 结论在付费墙后，**未能读取** | 按申报日调仓 | 未核实 | [CXO Advisory 摘要](https://www.cxoadvisory.com/miscellaneous/form-13f-clone-portfolio-performance/) |
| 伯克希尔 13F 披露后追涨案例（本文自算） | 13F 公布后次日收盘买入，持有至今 | CB：2024-05；UNH：2025-08 | 披露次日超额：CB +4.9 pp，UNH +12.4 pp；之后至 2026-10-26：CB 相对 QQQ −21.5 pp，UNH +15.5 pp。正反例都有，两例不构成证据 | 13F | 弱（事件日期根据公开报道整理，并以次日跳涨佐证） | [Yahoo CB](https://finance.yahoo.com/quote/CB/)；[Yahoo UNH](https://finance.yahoo.com/quote/UNH/) |
| 背景：Martin & Puthenpurackal（1976—2006）、Cohen-Polk-Silli “Best Ideas”（1991—2005） | 2023 年以前的研究，近年没有找到正式的复核 | — | 当年发现披露后模仿可获得正超额；只能作为背景 | — | 不计入 | [Quantpedia](https://quantpedia.com/strategies/alpha-cloning-following-13f-fillings) |

补充说明：AlphaClone 系列 ETF 在 Yahoo 上已没有行情（ALFA 返回 404），推测已经清盘
（未核实）。GFGF（Guru Favorite Stocks）在 Yahoo 上只有 43 个零散交易日，流动性极差，
因此没有列入比较。

### 3.3 明星基金经理与主题基金

| 对象 | 方法 | 样本期 | 相对 QQQ / 标普的结果 | 披露延迟 | 强度 | 链接 |
| --- | --- | --- | --- | --- | --- | --- |
| ARKK（Cathie Wood） | 价格事实 | 2023-01—2026-10-26 | +164.2%，落后 QQQ 9.0 pp；最大回撤 −39.6%，QQQ −22.8%。如果从 2023-02-07 起算只有 +92.0%，说明结果对起点非常敏感。分年：2023 年 +69.0%，2024 年 +8.4%，2025 年 +35.5%，2026 年以来 +6.4%。近五年 −31.4%，QQQ +93.6%；从 2021-02-12 高点起 −46.9%（本文自算） | ARK 每天披露持仓，没有滞后，但照样落后，说明问题不只是滞后 | 强 | [Yahoo ARKK](https://finance.yahoo.com/quote/ARKK/) |
| ARKW | 价格事实 | 2023-01—2026-10-26 | +307.5%，领先 QQQ 134.3 pp（有加密资产敞口）；这是事后选出的赢家，2026 年以来 +4.7%（本文自算） | 同上 | 强（事实），但不能当作信号 | [Yahoo ARKW](https://finance.yahoo.com/quote/ARKW/) |
| ARK 资金流与 Morningstar 评价 | 媒体转述 | 2023—2026 | 截至 2023 年 7 月的 12 个月，ARKK 净流出约 7.17 亿 USD；2024 年截至 4 月，6 只主动型 ARK ETF 净流出约 22 亿 USD，资产 111 亿 USD，峰值为 590 亿；截至 2026-06-11 的 12 个月，ARKK 净流出约 2.94 亿 USD（以上均为二手来源，未核实）。Morningstar 2024-02 把 ARKK 列为 2014—2023 年毁灭财富第三多的基金，ARK 基金家族约 143 亿 USD（家族数字为二手来源）。Morningstar 2026-01 又把 ARKK 列为 2025 年表现第五好的 ETF | 不适用 | 中 | [Wikipedia: Ark Invest](https://en.wikipedia.org/wiki/Ark_Invest)；[Investing.com](https://investing.com/news/stock-market-news/ark-investments-tops-morningstar-list-of-wealthdestroying-etf-issuers-report-3293277)；[InvestmentNews](https://investmentnews.com/etfs/cathie-woods-ark-funds-are-leaking-billions-of-dollars/252578) |
| SJIM（反向 Cramer）/ LJIM（正向 Cramer） | 真实运作的 ETF | SJIM：2023-03 至 2024-02-13 最后交易日；LJIM：2023 年 8—9 月清盘 | SJIM 存续期总回报约 −15%，资产约 240 万 USD；同期（2023-03-01—2024-02-13）SPY +27.1%，QQQ +48.2%（本文自算）。LJIM 资产约 130 万 USD，回报约 +2.2% | 不适用 | 中 | [WealthManagement](https://www.wealthmanagement.com/etfs/jim-cramer-etfs-are-history-closure-struggling-short-fund)；[Cointelegraph](https://cointelegraph.com/news/jim-cramer-inverse-etf-shuts-down-10-months-after-launch) |
| IVES（Dan Ives AI ETF） | 价格事实 | 2025-06-04—2026-10-26 | +55.4%，QQQ +35.6%，领先 19.8 pp；最大回撤 −22.6%（本文自算）；存续仅约 1.4 年 | 不适用 | 弱（期限短，属事后挑选） | [Yahoo IVES](https://finance.yahoo.com/quote/IVES/) |
| GRNY（Tom Lee 的 Fundstrat Granny Shots） | 价格事实 | 2024-11-07—2026-10-26 | +34.8%，QQQ +40.1%，落后 5.3 pp（本文自算） | 不适用 | 弱—中 | [Yahoo GRNY](https://finance.yahoo.com/quote/GRNY/) |

### 3.4 社交媒体、散户羊群与政治人物

| 对象 | 方法 | 样本期 | 相对 QQQ / 标普的结果 | 披露延迟 | 强度 | 链接 |
| --- | --- | --- | --- | --- | --- | --- |
| Bradley, Hanousek, Jame, Xiao，RFS 37(5)（2024） | WallStreetBets 尽调（DD）帖与收益、现金流新闻、散户成交的关系 | 覆盖 GameStop 事件前后 | 事件前 DD 能显著预测收益；**事件后预测力消失**，帖子转向制造价格压力和吸引关注，跟随 DD 交易的散户也不再有信息优势 | 发帖后通常几小时到几天就被定价 | 强 | [IDEAS/RePEc](https://ideas.repec.org/a/oup/rfinst/v37y2024i5p1409-1459..html)；[RFS](https://academic.oup.com/rfs/article/37/5/1409/7457987) |
| Kakhbod, Kazempour, Livdan, Schürhoff，“Finfluencers”，SFI WP 23-30（2023-04） | 社交平台上逐条推文的荐股准确度 | 未能核实具体样本期 | 28% 有技能（约 +2.6%/月），16% 无技能，56% 反技能（约 −2.3%/月）；反技能者粉丝更多；反向交易样本外约 +1.2%/月 | 无 | 中（工作论文） | [SFI](https://www.sfi.ch/en/publications/n-23-30-finfluencers) |
| MEME（Roundhill Meme Stock ETF，Yahoo 记录的首个交易日为 2025-10-08） | 价格事实 | 2025-10-08—2026-10-26 | −34.8%，QQQ +17.0%，**落后 51.8 pp**；最大回撤 −50.1%（本文自算） | 无 | 中 | [Yahoo MEME](https://finance.yahoo.com/quote/MEME/) |
| BUZZ（VanEck 社交情绪 ETF） | 价格事实 | 自 2021-03-04 成立；以及 2023-01 起 | 成立以来 +47.7%，QQQ +142.2%；自 2023-01 +184.8%，领先 11.6 pp；但从 2023-02-07 起算落后 6.8 pp；近 12 个月 −9.2%，QQQ +16.0%；最大回撤 −56.9%（本文自算） | 无 | 中（结论随起点反转） | [Yahoo BUZZ](https://finance.yahoo.com/quote/BUZZ/) |
| GME，2024-05 “Roaring Kitty” 回归 | 价格事实 | 2024-05-10—2024-06-28 | 两个交易日 +179.2%（5-10→5-14）；在 5-14 收盘追入，到 6-28 −49.4%，同期 QQQ +7.4%；6-07 直播当天 −39.4%（本文自算） | 无 | 弱（单一案例） | [Yahoo GME](https://finance.yahoo.com/quote/GME/) |
| OPEN / KSS，2025-07 散户集中买入的“meme”行情 | 价格事实 | 2025-07—2026-10-26 | OPEN：7-11→7-21 +312%，7-21 之后至今 −39.9%（QQQ +26.2%），期间 9 月高点在 10.52 USD。KSS：7-22 单日 +37.6%，之后至今 +64.9%（QQQ +26.9%）。方向不一，像彩票（本文自算） | 无 | 弱 | [Yahoo OPEN](https://finance.yahoo.com/quote/OPEN/)；[Yahoo KSS](https://finance.yahoo.com/quote/KSS/) |
| 特朗普 2025-04-09 帖子与关税暂停 | 指数单日表现 | 2025-04-02—2025-04-09 | 4-02→4-08 QQQ −12.6%；4-09 当天 QQQ +12.0%、SPY +10.5%（本文自算）；当天标普 +9.52%、纳指 +12.16%；有议员要求调查内幕交易，但未见违法证据 | 帖子发布约 2—4 小时后才宣布政策，来源说法不一 | 强（事实），但不可交易 | [Wikipedia: 2025 stock market crash](https://en.wikipedia.org/wiki/2025_stock_market_crash) |
| DJT（Trump Media）与 MAGA ETF（现名 Truth Social America First） | 价格事实 | DJT 自 2024-03-26 上市；MAGA 自 2023-01 | DJT −89.4%，QQQ +62.8%；从 2024-11-05 大选日起 −81.9%，QQQ +46.2%。MAGA +53.5%，QQQ +173.2%（本文自算） | 无 | 强（事实） | [Yahoo DJT](https://finance.yahoo.com/quote/DJT/)；[Yahoo MAGA](https://finance.yahoo.com/quote/MAGA/) |
| 政策相关个股（政府入股或总统交易） | 媒体报道与价格事实 | 2025-07—2026-10 | INTC 自 2025-08-01：+523.25%（据 2026-07 报道）/+368.5%（至 2026-10-26，期间最大回撤 −41.9%，本文自算）；MP 自 2025-07-09 +24.8%，QQQ +28.8%，最大回撤 −62.0%（本文自算）。特朗普 2025 年在 8 个账户中交易超过 2.1 万笔，以金额区间披露，无法算出收益 | 公告当天就跳空 | 弱（事后挑选的个例） | [24/7 Wall St](https://247wallst.com/investing/2026/07/06/trump-vs-pelosi-who-made-more-money-in-the-stock-market-last-year/) |

### 3.5 指数纳入与剔除效应

| 对象 | 方法 | 样本期 | 相对 QQQ / 标普的结果 | 披露延迟 | 强度 | 链接 |
| --- | --- | --- | --- | --- | --- | --- |
| Greenwood & Sammon，“The Disappearing Index Effect”，JF 80(2)（2025） | S&P 500 纳入和剔除事件的异常收益 | 1980 年代—2020 | 纳入超额从 1990 年代的 7.4% 降到近十年的不到 1%；剔除效应在 2010—2020 年平均只有 0.1%；其他指数家族也有类似下降 | 本文样本中公告到生效约 3—11 个交易日 | 强 | [IDEAS/RePEc](https://ideas.repec.org/a/bla/jfinan/v80y2025i2p657-698.html)；[NBER w30748](https://www.nber.org/system/files/working_papers/w30748/w30748.pdf) |
| 高盛 2025 年研究（据 ETF Trends 报道） | 新成分股在公告日相对等权标普的表现 | 2013—2025 | 2015—2019 年效应几乎消失，近年回归；2025 年 Block、Coinbase、DoorDash 等公告日平均领先 7.4 pp；公告前 3 个月平均领先 12 pp；**生效后没有持续超额**；作者归因于散户活跃（二手来源，未核实） | 同上 | 弱—中 | [ETF Trends](https://www.etftrends.com/retail-revival-fuels-comeback-sp-500-index-inclusion-effect/) |
| 本文自算：2024—2025 年 22 只 S&P 500 新成分股 | 相对 QQQ 的简单收益差；公告日期根据公开报道整理，并核对了公告后首个交易日的跳空（TTD 已据此更正为 2025-07-14）；**不是完整清单**，偏向高关注度股票 | 2024-03—2026-10-26 | 见下表 | 公告一般在收盘后发布，跳空发生在散户能下单之前 | 弱—中 | [Bankrate 新增名单](https://www.bankrate.com/investing/s-p-500-stocks-list-of-additions)；[Longport 报道](https://longportapp.cn/news/256235121) |
| 本文自算：2024-12 纳斯达克 100 新增的 PLTR、MSTR、AXON | 同上 | 2024-12—2025-06 | 公告当天相对 QQQ 平均 −1.4%，没有公告效应；纳入后 20 个交易日平均 −3.7% | 年度调整，可以预见 | 弱 | [Nasdaq 2025 调整说明](https://www.nasdaq.com/articles/global-indexes/2025-nasdaq-100-reconstitution-and-performance-highlights) |

本文自算的 S&P 500 纳入事件（相对 QQQ，单位 %，括号内为跑赢 QQQ 的个数）：

| 窗口 | 2024 年（11 只） | 2025 年（11 只） | 合计（22 只） |
| --- | --- | --- | --- |
| 公告前 63 个交易日 | 均值 +35.6 | 均值 +10.6 | 均值 +23.1（18/22） |
| 公告日收盘 → 次日开盘（隔夜跳空，无法获得） | 均值 +5.5 | 均值 +6.2 | 均值 +5.8（20/22） |
| 次日开盘买入 → 生效前一日收盘卖出（可执行） | 均值 −1.2，中位 −0.4（4/11） | 均值 +3.8，中位 +5.0（7/11） | 均值 +1.3，中位 +0.1（11/22） |
| 生效前一日收盘 → 之后 20 个交易日 | 均值 −4.2 | 均值 −5.1 | 均值 −4.6（9/22） |
| 生效前一日收盘 → 之后 120 个交易日 | 中位 −15.3 | 中位 −18.5 | 中位 −15.8（6/22） |

样本：2024 年为 SMCI、DECK、KKR、CRWD、GDDY、PLTR、DELL、ERIE、APO、WDAY、LII；
2025 年为 DASH、TKO、WSM、EXE、COIN、DDOG、TTD、XYZ、APP、HOOD、EME。

### 3.6 披露延迟如何削弱跟单

- **国会（STOCK Act）：** 法定期限为交易后 45 天，或知悉交易后 30 天，以较晚者为准，
  金额只按区间申报。2012—2022 年有 41% 的交易逾期申报。领导人的超额来自交易时点
  （例如监管行动前卖出、政府合同前买入），等到公开披露时这部分信息通常已经反映在
  价格中。用披露日作为起点的研究（Chen & Sacerdote 以及 2020—2024 年的论文）都没有
  发现正超额。
- **13F：** 季末后 45 天内申报，持仓最长可能已有约 135 天；看不到空头、大部分期权和
  现金，还可以申请保密处理推迟披露。ARK 每天公开持仓，没有任何滞后，但 2023 年以后
  照样没有稳定跑赢 QQQ，说明“消除滞后”也不足以让跟随有效。
- **指数纳入：** 公告在收盘后发布，平均约 5.8% 的超额在隔夜跳空中完成，散户无法参与；
  能参与的窗口中位数接近零，生效后还会反转。

### 3.7 年度收益对照（本文自算，截至 2026-10-26）

| 代码 | 2023 | 2024 | 2025 | 2026 年以来 | 2023-01 起累计 |
| --- | --- | --- | --- | --- | --- |
| QQQ | +54.9% | +25.6% | +20.8% | +16.3% | +173.2% |
| SPY | +26.2% | +24.9% | +17.7% | +13.1% | +109.8% |
| NANC | +20.8%（自 2-07） | +26.8% | +18.5% | +12.0% | +103.4%（自 2-07） |
| GOP | +10.2%（自 2-07） | +14.4% | +17.1% | +19.2% | +75.9%（自 2-07） |
| GURU | +19.3% | +23.8% | +25.4% | +4.3% | +93.1% |
| GVIP | +39.1% | +29.8% | +25.3% | +3.1% | +133.3% |
| BRK-B | +15.5% | +27.1% | +10.9% | +9.1% | +77.6% |
| ARKK | +69.0% | +8.4% | +35.5% | +6.4% | +164.2% |
| ARKW | +96.9% | +42.3% | +38.9% | +4.7% | +307.5% |
| BUZZ | +54.6% | +33.7% | +30.6% | +5.4% | +184.8% |
| MAGA | +10.4% | +14.7% | +10.3% | +9.9% | +53.5% |
| DJT* | +16.7% | +94.9% | −61.2% | −53.6% | −59.1% |

\* DJT 在 2024-03-26 之前的数据是 SPAC（DWAC）的价格。

## 4. 对本项目的候选路线

### 4.1 总体判断：不把任何名人或跟单信号作为主路线

| 信号 | 能否在约束内执行 | 2023 年以后相对 QQQ 的证据 | 结论 |
| --- | --- | --- | --- |
| 国会 PTR 跟单（自己建组合，或买 NANC/GOP） | 能，PTR 免费公开 | NANC 落后 31.4 pp，GOP 落后 58.9 pp；以披露日为起点的研究得到负 α | 不采用 |
| 只跟国会领导人 | 能，但滞后最长 45 天，名单很少 | 超额来自交易时点信息，没有证据表明披露后还能复制；样本截至 2021 年；禁止交易的立法在推进，Pelosi 将于 2027-01 退休 | 不采用 |
| 13F 克隆（自己建组合，或买 GURU/GVIP/OMAH/ACKY） | 能，EDGAR 免费 | 全部落后 QQQ 23—80 pp；GVIP 分年度领先也不稳定 | 不采用 |
| 明星经理或主题 ETF（ARK、IVES、GRNY） | 能 | ARKK 落后且回撤接近 QQQ 的两倍；赢家只能事后识别 | 不采用 |
| 网红、WSB、meme 股 | 部分数据免费 | WSB 的信息价值在 GME 后消失；MEME 落后 51.8 pp | 不采用 |
| 反向网红 | 需要逐条社交数据和做空 | 学术上有 +1.2%/月，但样本期未核实，没有扣成本 | 不满足“免费数据 + 只做多”，不采用 |
| 政治人物言论或政策股 | 无法事先预期 | 单日事件、事后挑选；DJT 和 MAGA 大幅落后 | 不采用 |
| S&P 500 纳入公告窗口 | 能，S&P DJI 的公告免费 | 2025 年为正，2024 年为负，中位数接近零 | 仅作为 paper 观察候选（见 4.2） |

主要原因有三个：

1. **QQQ 本身就是“名人共识”的集中体现。** 国会、对冲基金和明星经理的头部持仓高度重合
   于大型科技股（NANC 前两大持仓是 NVDA 和 MSFT；GVIP 的常客是 MSFT、AMZN、META、
   NVDA、GOOGL，据 2025 Q2 名单，二手来源）。跟单组合相当于“QQQ 的打折版”：扣掉 0.72%—0.95% 的费率，再加上
   滞后和非科技股带来的拖累。
2. **信息优势在披露之前就已经兑现。** 不论是国会领导人、13F 持仓还是指数公告，
   可获得的超额都发生在公众能够交易之前。
3. **5,000 USD 账户的成本限制。** 按项目口径（每笔 1 USD、单边 5 bps），每次个股往返
   至少 2 USD。按 1,000 USD 仓位计算，往返成本约 0.3%，与指数纳入窗口约 0.1% 的
   中位数超额相比，已经足以吃掉全部收益。

### 4.2 观察候选 C1：S&P 500 新成分股公告窗口（只做预注册 paper 观察，不进实盘）

列入原因：在所有名人或机构信号中，只有它同时满足四个条件：使用免费数据、规则是机械的、
2025 年有可执行窗口的正证据、只需做多。但 2024 年为负，22 只样本的中位数只有 +0.1%，
样本也不完整，**不能直接上线**。

规则草案（必须在看到新数据之前冻结）：

- **事件来源：** S&P Dow Jones Indices 官方公告中所有 S&P 500 新增成分，包括季度调整和
  临时替换。排除分拆新股（没有前期价格）和公告时已停牌的股票。记录公告时间戳、生效日，
  以及是否从 S&P 400/600 迁入（迁入股的效应可能更弱，只记录，不过滤）。
- **决策时点：** 公告在美东时间收盘后发布时，下一个常规交易会话开盘下单。公告在盘中
  发布的事件作废，不使用盘中信息。
- **入场：** 按开盘价整股买入（研究中以次日开盘价代理）。不设跳空过滤，以免事后加参数。
- **仓位：** 子仓位合计不超过账户净值的 20%（约 1,000 USD），资金从 QQQ 承接仓位中划出，
  遵守项目现有的资金交收可用规则。同一批多只股票等权买入；如果单只金额低于 500 USD，
  只买公告时市值最大的 2 只。只有本金阶梯处于 `active` 时执行，`warning` 和 `terminated`
  状态下不执行。
- **出场：** 在生效日前最后一个交易日收盘卖出（按收盘价成交），下一会话开盘把资金买回
  QQQ。**绝不持有过生效日**，因为生效后 20 个交易日平均 −4.6%。不加杠杆，不做空，
  不使用期权。
- **成本：** 正常情况每笔 1 USD、单边 5 bps；压力情况每笔 2 USD、单边 10 bps。
- **评估：** 每个事件计算“扣成本后的子仓位收益减去同窗口 QQQ 收益”。先用 2015—2026 年的
  **完整**公告清单，在项目的 Parquet 管线里做历史检验（需要用户批准新增事件数据源），
  再做至少 20 个事件的前向 paper 观察。
- **晋级门槛（预先登记）：** 历史样本和前向样本在压力成本下的平均超额与中位超额都大于 0，
  并且至少三分之二的年份为正；任何一项不满足就放弃，不调整参数后重试。
- **规模预期：** 按本文的粗略样本，2025 年 6 批事件的批均超额合计约 +18.2%，乘以 20% 的
  子仓位，约为账户层面 +3.6 pp（未扣成本）；2024 年 4 批合计 −3.3%，约为 −0.7 pp。每批
  成本约 4—10 USD，相当于净值的 0.1%—0.2%。即使有效，它也只是在 QQQ 之上的小幅
  加减，不是跑赢 QQQ 的主要来源。

### 4.3 负面清单（建议作为研究约束）

- 不用 NANC、GOP、GURU、GVIP、OMAH、ACKY、BUZZ、MEME、MAGA 或 ARK 系列替代 QQQ。
- 不按国会 PTR、13F 或明星经理的持仓变动追买，包括 13F 公布次日的追涨。
- 新纳入指数的股票不持有过生效日；不在纳入后追买。
- 不根据总统或政客的社交媒体帖子交易。关税等政治新闻造成的急跌不作为卖出 QQQ 的
  理由：2025-04 QQQ 一周内下跌 12.6% 后单日反弹 12.0%，当年 4-02 至年底 +29.0%。
  账户层面的风险继续由本金阶梯规则处理。
- 不在政治新闻密集期间使用杠杆，因为单日 ±10% 的指数波动足以触发 2,500 USD 的清仓底线。
- 不跟随网红推荐，也不做反向网红：前者平均为负，后者需要付费数据和做空。

## 5. 来源列表

价格与产品数据：

- Yahoo Finance 行情页（本文自算所用的免费日线来源）：
  [NANC](https://finance.yahoo.com/quote/NANC/)、[GOP](https://finance.yahoo.com/quote/GOP/)、
  [QQQ](https://finance.yahoo.com/quote/QQQ/)、[SPY](https://finance.yahoo.com/quote/SPY/)、
  [GURU](https://finance.yahoo.com/quote/GURU/)、[GVIP](https://finance.yahoo.com/quote/GVIP/)、
  [BRK-B](https://finance.yahoo.com/quote/BRK-B/)、[OMAH](https://finance.yahoo.com/quote/OMAH/)、
  [ACKY](https://finance.yahoo.com/quote/ACKY/)、[ARKK](https://finance.yahoo.com/quote/ARKK/)、
  [ARKW](https://finance.yahoo.com/quote/ARKW/)、[IVES](https://finance.yahoo.com/quote/IVES/)、
  [GRNY](https://finance.yahoo.com/quote/GRNY/)、[BUZZ](https://finance.yahoo.com/quote/BUZZ/)、
  [MEME](https://finance.yahoo.com/quote/MEME/)、[MAGA](https://finance.yahoo.com/quote/MAGA/)、
  [DJT](https://finance.yahoo.com/quote/DJT/)、[GME](https://finance.yahoo.com/quote/GME/)
- [stockanalysis.com：NANC 与 QQQ 对比](https://stockanalysis.com/etf/compare/nanc-vs-qqq/)
- [stockanalysis.com：ACKY](https://stockanalysis.com/etf/acky)
- [Global X：GURU 基金页](https://www.globalxetfs.com/funds/guru/)；[GURU 说明书](https://wp.globalxetfs.com/content/files/GURU-factsheet.pdf)
- [ETF Central：OMAH](https://www.etfcentral.com/fund/OMAH)
- [Pershing Square Holdings 2025-12 事实表](https://pershingsquareholdings.com/wp-content/uploads/2026/01/PSH-Fact-Sheet-December-2025-Website.pdf)

国会交易：

- [Chen & Sacerdote（2026），Capital in the Capitol，NBER w35041](https://www.nber.org/papers/w35041)
- [Wei & Zhou（2025），“Captain Gains” on Capitol Hill，NBER w34524](https://www.nber.org/papers/w34524)
- [哈佛法学院公司治理论坛：Political Power, Personal Portfolios（2025-12-10）](https://corpgov.law.harvard.edu/2025/12/10/political-power-personal-portfolios-and-risks-for-corporate-governance/)
- [Fortune：国会领导人超额与禁止交易法案（2025-12-07）](https://fortune.com/2025/12/07/congress-stock-market-trades-leadership-outperformance-trading-ban-bill-discharge-petition)
- [Fortune：Unusual Whales 2024 年报（2025-01-08）](https://fortune.com/2025/01/08/congress-stock-trading-pelosi-2024)
- [24/7 Wall St：Trump vs. Pelosi（2026-07-06）](https://247wallst.com/investing/2026/07/06/trump-vs-pelosi-who-made-more-money-in-the-stock-market-last-year/)
- [24/7 Wall St（经 Yahoo）：国会跟踪 ETF 自成立以来的收益（2026-04-20）](https://finance.yahoo.com/markets/stocks/articles/invested-congressional-trading-etfs-launch-120515368.html)
- [Islam（2025），MSU 博士论文](https://scholarsjunction.msstate.edu/td/6652)
- [哥德堡大学硕士论文：Trading on the Hill（二手来源，未核实）](https://gupea.ub.gu.se/items/0e1aeba3-3354-493e-b192-bee7df3c107c)
- [Lambda Finance：2026 国会交易表现（二手来源，未核实）](https://www.lambdafin.com/articles/congressional-stock-trading)
- [Lambda Finance：披露滞后后的国会交易表现（2026-01-19）](https://www.lambdafin.com/articles/congressional-stock-trading-performance-after-disclosure-delays)
- [Crypto Briefing：Unusual Whales 与 Subversive 结束合作（2026-08-17）](https://cryptobriefing.com/unusual-whales-subversive-political-etfs-split/)
- [CXO Advisory：Congressional Trade Tracking ETFs（2026-06-16，结论在付费墙后）](https://www.cxoadvisory.com/?p=44578)

13F 与克隆：

- [CXO Advisory：Form 13F Clone Portfolio Performance（2024-05-01）](https://www.cxoadvisory.com/miscellaneous/form-13f-clone-portfolio-performance/)
- [Quantpedia：Alpha Cloning – Following 13F Filings](https://quantpedia.com/strategies/alpha-cloning-following-13f-fillings)
- [Benzinga：高盛 VIP 篮子 2025 年表现（二手来源，未核实）](https://www.benzinga.com/markets/equities/25/08/47406673/top-hedge-fund-picks-from-goldman-sachs-outperform-sp-500-powering-16-gains-in-2025)
- [MarketScreener/Reuters：VistaShares 推出跟踪 Ackman 的 ETF（2025-09-09）](https://ca.marketscreener.com/news/vistashares-launches-etf-tracking-stock-bets-of-hedge-fund-activist-bill-ackman-ce7d59dfde8ef624)
- [WhaleWisdom 回测白皮书（2017，仅作为 13F 滞后机制背景）](https://whalewisdom.com/help/backtesting_whitepaper)

明星经理与主题基金：

- [Wikipedia：Ark Invest](https://en.wikipedia.org/wiki/Ark_Invest)
- [Investing.com：ARK 位列 Morningstar 财富毁灭榜首（二手来源）](https://investing.com/news/stock-market-news/ark-investments-tops-morningstar-list-of-wealthdestroying-etf-issuers-report-3293277)
- [InvestmentNews：ARK 资金流出（二手来源）](https://investmentnews.com/etfs/cathie-woods-ark-funds-are-leaking-billions-of-dollars/252578)
- [WealthManagement：Cramer ETF 全部关闭（2024-01-29）](https://www.wealthmanagement.com/etfs/jim-cramer-etfs-are-history-closure-struggling-short-fund)
- [Cointelegraph：反向 Cramer ETF 关闭（2024-01-29）](https://cointelegraph.com/news/jim-cramer-inverse-etf-shuts-down-10-months-after-launch)

社交媒体与政治人物：

- [Bradley 等（2024），Place Your Bets?，RFS 37(5)（IDEAS/RePEc）](https://ideas.repec.org/a/oup/rfinst/v37y2024i5p1409-1459..html)；[期刊页面](https://academic.oup.com/rfs/article/37/5/1409/7457987)
- [Kakhbod 等（2023），Finfluencers，SFI WP 23-30](https://www.sfi.ch/en/publications/n-23-30-finfluencers)
- [Wikipedia：2025 stock market crash](https://en.wikipedia.org/wiki/2025_stock_market_crash)

指数纳入：

- [Greenwood & Sammon（2025），The Disappearing Index Effect，JF 80(2)（IDEAS/RePEc）](https://ideas.repec.org/a/bla/jfinan/v80y2025i2p657-698.html)；[NBER w30748 PDF](https://www.nber.org/system/files/working_papers/w30748/w30748.pdf)
- [ETF Trends：散户回归推动 S&P 500 纳入效应复苏（转述高盛，二手来源，未核实）](https://www.etftrends.com/retail-revival-fuels-comeback-sp-500-index-inclusion-effect/)
- [Bankrate：S&P 500 新增成分名单](https://www.bankrate.com/investing/s-p-500-stocks-list-of-additions)
- [Longport/Benzinga：AppLovin、Robinhood 纳入 S&P 500（2025-09）](https://longportapp.cn/news/256235121)
- [Nasdaq：2025 年纳斯达克 100 调整说明](https://www.nasdaq.com/articles/global-indexes/2025-nasdaq-100-reconstitution-and-performance-highlights)
