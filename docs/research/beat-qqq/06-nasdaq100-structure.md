# 06 纳斯达克 100 内部结构：在 QQQ 自身规则里，有没有能稳定跑赢 QQQ 的机会

- 研究日期：2026-10-27
- 基准：QQQ 买入持有（含股息再投资，USD 计价）。基准不改。
- 约束回顾：本金 5,000 USD；IBKR 账户；W-8BEN（美国资本利得不征税，股息预扣 10%）；只做美股和美股 ETF；只用免费数据；净值低于 2,500 USD（即从本金回撤 50%）时清仓并终止策略。

## 时效规则与口径

1. 主要证据必须来自 2023 年及以后的研究、数据或回测。更早的研究只有在近年被复核过时才引用，并标为“早期研究”。
2. 所有业绩数字都写明截止日。找不到原始数据的，标为“二手来源，未核实”。
3. 本文有一部分数字是本研究自己算的，统一标为“本研究自算”。口径如下：
   - 数据：Yahoo Finance 公开日线（`query1.finance.yahoo.com/v8/finance/chart`），2026-10-27 抓取，区间 2005-01-03 至 2026-10-26。只在 `/tmp` 临时使用，没有写入仓库。这些数据不是权威来源，也不是项目的 Parquet 快照。正式回测前必须用项目的 Alpaca SIP / IBKR 权威数据重算。
   - 收益：用 adjclose 计算的总回报（股息再投资）。未扣 10% 股息预扣税。QQQ 股息率约 0.5%，预扣税拖累约 0.05%/年，对所有方案大致相同。
   - 年化：按每年 252 个交易日计。
   - 隔夜/日内分解：隔夜 =（T 日开盘价 + 当日除息金额）/ T−1 日收盘价 − 1；日内 = T 日收盘价 / T 日开盘价 − 1。两段相乘与全天总回报一致（自算 QQQ 2025 年 +20.77%，与 totalrealreturns 的数字相同）。
   - 轮动回测：月末收盘出信号，下一交易日收盘执行（滞后 1 天）。每次切换按每边 5 bp 扣成本，不计税。
4. 时间均为美东交易日。第三方汇总页（totalrealreturns、stockanalysis）的数字按页面显示的截止日标注。

---

## 一、结论摘要

1. **纳入/剔除效应基本消失，近年方向也不一致，不能规则化套利。** Greenwood & Sammon（JF，2025）发现：标普 500 纳入的异常收益从 1990 年代的 7.4% 降到近十年不足 1%，剔除效应在 2010–2020 年只有 0.1%，其他指数族同样下降。纳斯达克 100（NDX）的 12 月重构完全按规则执行，公告日也提前固定，很容易被抢跑。实践者统计（Schaeffer's，2010–2024）显示“被剔除股 3 个月均值好于被纳入股”，但没有风险调整。本研究自算 2023–2025 三次重构（共 30 只），生效后 3 个月相对 QQQ 的超额收益方向互相矛盾。
2. **等权长期稳定落后 QQQ。** QQQE 在 2012-03-21 至 2026-10-26 年化 14.43%，QQQ 为 18.57%。2013 年以来只有 2013、2014、2016、2022 四年领先。QQEW 从 2025-12-22 起改为“成长+质量精选 50 只等权”（NDXSE），2026 年至 10-26 的收益为 +9.83%，QQQ 为 +16.33%。
3. **只持头部小幅领先，去掉头部大幅落后，本质都是押注集中度。** 2024-10-24 至 2026-10-16，QTOP（NDX 前 30）年化 23.11%，QQQ 20.95%，QNXT（剔除前 30）只有 12.02%。七巨头等权的 MAGS 在 2024 年 +64%，但 2026 年至今只有 +7.2%（QQQ +16.3%）。头部倾斜的超额不到 2 年样本，而且完全依赖巨头继续领涨。
4. **NDX 成分内的动量选股和质量成长选股，实盘都落后 QQQ。** 动量版 QQQA（Dorsey Wright 动量最强 21 只，等权）在 2021-05-20 至 2026-10-26 年化 9.23%，QQQ 15.96%。Nasdaq 官方 NDXSE 回测（2007-12 至 2025-06，价格回报）为 13.03%，低于 NDX 的 14.24%。这和本项目“每周成分股漏斗选股跑输 QQQ”的结果一致：在市值高度集中的指数里，等权化的选股天然要先背上“小盘化”的拖累。
5. **SMH/QQQ 相对强度月度切换在全样本上跑赢，但超额集中在 2016 年以后的半导体超级周期，且回撤触碰本项目清盘线。** 本研究自算（6 个月相对动量，滞后 1 天）：2006–2026 年化 18.5%，QQQ 15.6%。但 2006–2019 只有 13.2%，QQQ 13.4%。2020–2026 为 29.7%，QQQ 19.9%，SMH 买入持有更高，为 35.2%。最大回撤 −56%。3 到 12 个月的回看期结论都相同，说明这是“半导体 beta 加行业周期”，不是稳定的结构性 alpha。
6. **“只持隔夜 QQQ”连扣成本前都跑不赢买入持有，应否决。** 本研究自算：2005–2026 QQQ 隔夜段年化 11.50%，日内段 3.20%，买入持有 15.06%。2023–2026 隔夜 18.09%，买入持有 30.30%。每次往返扣 2 bp 后再降约 6 个百分点。期货上的“凌晨 2–3 点漂移”自 2021 年起接近零（纽约联储 2026-07）。NightShares 隔夜 ETF 于 2023 年清盘。
7. **唯一确定但很小的优势是费率。** QQQM 费率 0.15%，QQQ 0.18%。2024-10-24 至 2026-10-26，QQQM 年化 20.90%，QQQ 20.84%。W-8BEN 下资本利得不征税，所以低频轮动没有税务摩擦。但这个优势只有约 0.03–0.06 个百分点/年。
8. **总判断：** 在 QQQ 自身的成分和规则里，没有找到“稳定、可实现、证据强”的跑赢结构。可做的是：以 QQQM 为核心；把 SMH 相对强度或头部集中倾斜作为受风控约束的卫星仓位，先做研究和纸面验证。纳入/剔除套利、等权、成分内动量和隔夜持有都不建议推进。

---

## 二、证据表

强度含义：强 = 同行评审、长样本或长期实盘；中 = 实盘或可复算但样本短、有区间依赖；弱 = 实践者统计、学位论文、单事件、发行方回测或二手来源。

| # | 机会 | 方法 | 样本期 | 相对 QQQ 的结果（注明截止日） | 成本与换手 | 证据强度 | 链接 |
|---|---|---|---|---|---|---|---|
| 1 | 指数纳入/剔除效应（总体） | Greenwood & Sammon，*Journal of Finance* 80(2)，2025-04；以标普 500 为主，并检查其他指数族 | 1980s–2020 | 纳入异常收益：1990s 为 7.4%，近十年不足 1%（2022 年 NBER 工作论文版为 0.8%）；剔除：2010–2020 为 0.1%。其他指数族同样下降。主要原因：中盘指数迁移抵消了净需求，以及事前抢跑 | 不适用 | 强（但不是 NDX 专项） | [IDEAS/RePEc](https://ideas.repec.org/a/bla/jfinan/v80y2025i2p657-698.html)，[NBER w30748](https://www.nber.org/system/files/working_papers/w30748/w30748.pdf) |
| 2 | NDX 12 月重构：买被剔除、避开被纳入 | Schaeffer's 统计 12 月重构后的绝对收益（不含年中变更） | 2010–2024；纳入 80 只，剔除 73 只 | 3 个月均值：纳入 +3.81%，剔除 +7.27%（剔除股跑赢 NDX 的比例 56%）。1 年：约 +12% 对约 +18%，跑赢 NDX 比例 40% 对 52%。截至 2024-12-26 | 未计成本，无风险调整，剔除股的波动明显更高 | 弱 | [Schaeffer's 2024-12-26](https://www.schaeffersresearch.com/content/analysis/2024/12/26/how-stocks-perform-after-nasdaq-100-rebalancing) |
| 3 | 同上（上一年版本） | Schaeffer's | 2010–2023；纳入 77 只，剔除 62 只 | 3 个月：纳入 +3.21%（46% 跑赢 NDX），剔除 +8.4%（56%）。12 个月：约 13% 对 19%。截至 2023-12-20 | 同上 | 弱 | [Schaeffer's 2023-12-20](https://www.schaeffersresearch.com/content/analysis/2023/12/20/removed-ndx-stocks-likely-to-outperform-those-added) |
| 4 | NDX 纳入/剔除的短期事件效应 | Niemelä 本科论文（塔林理工，2024），市场模型事件研究，窗口为 −4 到 +5 日 | 2014–2023；有效样本：纳入 84 只，剔除 63 只 | 纳入：CAR(0,+5) = −0.81%。剔除：CAR(0,+5) = +2.90%。两类事件前都有异常成交量 | 未计成本 | 弱（本科论文，t 值异常偏大） | [Taltech 论文 PDF](https://digikogu.taltech.ee/en/Download/d08f2143-bae7-474a-a029-347fdeafa21a) |
| 5 | 近三次 12 月重构（复核 #2–#4） | **本研究自算**：等权平均的个股超额（相对 QQQ）。公告日收盘到生效前一日收盘，以及生效后 63 个交易日 | 2023-12、2024-12、2025-12，共 15 只纳入、15 只剔除 | 公告→生效：纳入 +1.4% / −0.1% / −1.6%；剔除 +3.2% / −6.0% / −1.2%。生效后 3 个月：纳入 −9.1% / +2.9% / **+18.9%**（主要是 WDC、STX）；剔除 −9.8% / −9.2% / −0.2%。与 #2 的“买剔除股”方向**相反** | 个股，每年约 3–6 只 | 弱（样本太少） | 2025 名单来自 [Nasdaq 2025 重构报告](https://indexes.nasdaqomx.com/docs/202601%20NDX%20Reconstitution%20and%20Performance%20Highlights.pdf)。2023 和 2024 年的名单及公告/生效日由本研究按公开记录整理，未在本次抓取中逐一核对原公告。价格数据来自 Yahoo |
| 6 | 2023-07 特别再平衡（权重超过 4.5% 的成分合计超过 48% 时，压到 40%） | 规则事实加**本研究自算**：被压权重的 7 只巨头等权，对比 QQQ / QQQE | 公告 2023-07-07 盘后，生效 2023-07-24 开盘 | 公告到生效前：QQQ +2.6%，QQQE +4.9%，七巨头 +0.5%（短期承压）。生效后 1 年：七巨头 +54.4%，QQQ +29.3%，QQQE +13.8% | 单次事件 | 弱（n=1；正值财报季，难以分离原因） | [MarketBeat 2023-07-12](https://www.marketbeat.com/articles/nasdaq-100-index-shake-up-rattles-high-flying-stocks-of-2023/)；触发时合计 50.9% 来自 [globaltrading.net](https://globaltrading.net/?p=23732)（二手来源，未核实） |
| 7 | 2026 方法论变更带来的新事件 | 规则事实：Fast Entry；低流通股按流通股 3 倍封顶；季度“掉出前 125 名即剔除”取代 0.10% 权重规则；取消季内股本调整 | 2026-05-01 生效，首个影响日为 2026-06-22 | 规则：新上市股如果市值进入现有成分前 40 名，在上市第 7 个交易日评估，第 10 个交易日盘后公告，约第 15 个交易日纳入。**目前没有任何绩效证据** | 不适用 | 规则本身：强；可交易性：未知 | [方法论 PDF](https://indexes.nasdaqomx.com/docs/Methodology_NDX.pdf)，[2026-02 咨询结论](https://indexes.nasdaqomx.com/docs/Nasdaq-100_Index_Consultation_February_2026_Summary_of_Responses_and_Conclusion.pdf) |
| 8 | 等权（NDXE） | QQQE 实盘，totalrealreturns | 2012-03-21 至 2026-10-26 | 年化 14.43%，QQQ 18.57%。按完整年度，只有 2013、2014、2016、2022 领先。最大回撤 −31.2%，QQQ −35.1% | 季度再平衡回等权，换手明显高于 QQQ | 强（14 年实盘） | [totalrealreturns](https://totalrealreturns.com/n/QQQ,QQQE,SMH,SOXX) |
| 9 | 等权到精选等权（QQEW） | QQEW 实盘。2025-12-22 前跟踪 NDXE，之后跟踪 NDXSE（成长+质量精选 50 只等权） | 2021-05-20 至 2026-10-26；2026 年至今 | 年化 8.01%，QQQ 15.96%。2026 年至 10-26：+9.83%，QQQ +16.33%（基本就是 NDXSE 的实盘期）。2006–2025 年只有 5 年领先 | 费率 0.55%（经搜索摘要获得，二手来源，未核实） | 中 | [totalrealreturns](https://totalrealreturns.com/n/QQQ,QQQA,QQEW,QTEC)，[BusinessWire 公告](https://www.businesswire.com/news/home/20251104125696/en) |
| 10 | 质量+成长精选（NDXSE） | Nasdaq 发行方回测；5 个指标：3 年营收、预期 EPS、FCF 增速，ROE，毛利率 | 2007-12-21 至 2025-06-20（价格回报） | NDXSE 13.03%，NDX 14.24%，NDXE 10.81%。最大回撤 −48.6%，NDX −51.5%。对 NDX 的月胜率 46% | 季度重构 | 弱到中（发行方回测，有回填风险） | [NDXSE Research 2025-07](https://indexes.nasdaqomx.com/docs/NDXSE_Research.pdf) |
| 11 | 头部集中：NDX 前 30（QTOP） | iShares 实盘 | 2024-10-24 至 2026-10-16 | 年化 23.11%，QQQ 20.95%。2025 年 NAV +22.36%，QQQ +20.77%。截至 2026-09-30，1 年 NAV +26.56%。最大回撤 −23.3%，QQQ −22.8% | 费率 0.20%，季度再平衡 | 中到弱（不到 2 年） | [iShares QTOP 月报 2026-09-30](https://www.ishares.com/us/literature/fact-sheet/qtop-ishares-nasdaq-top-30-stocks-etf-fund-fact-sheet-en-us.pdf)，[totalrealreturns](https://totalrealreturns.com/n/QQQ,QTOP,QNXT,QQEW) |
| 12 | 七巨头等权（MAGS） | Roundhill 实盘 | 2024-10-24 至 2026-10-26 | 年化 22.24%，QQQ 20.84%。2024 年 +63.97%（QQQ +25.58%），2025 年 +22.98%（QQQ +20.77%），**2026 年至今 +7.19%（QQQ +16.33%）**。最大回撤 −29.9% | 只有 7 只，单票风险高 | 弱 | [totalrealreturns](https://totalrealreturns.com/n/QQQ,QQQM,MAGS,QTOP) |
| 13 | 剔除前 30 大（QNXT，第 31–100 名） | iShares 实盘 | 2024-10-24 至 2026-10-16 | 年化 12.02%，QQQ 20.95%。2025 年 NAV +15.05%。截至 2026-09-30，1 年 NAV +11.27% | 费率 0.20% | 中到弱 | [iShares QNXT 月报 2026-09-30](https://www.ishares.com/us/literature/fact-sheet/qnxt-ishares-nasdaq-100-ex-top-30-etf-fund-fact-sheet-en-us.pdf) |
| 14 | NDX 成分内价格动量（最强 21 只，等权） | ProShares QQQA 实盘（NDXDWA 指数） | 2021-05-20 至 2026-10-26 | 年化 9.23%，QQQ 15.96%。2026 年至今 +31.74%（QQQ +16.33%）。2021、2023、2024、2025 年落后，只有 2022 年跌得较少（−29.1%，QQQ −32.6%）。最大回撤 −38.4%，QQQ −35.1% | 费率 0.58%（二手来源，未核实），季度调仓 | 中（5.4 年实盘） | [totalrealreturns](https://totalrealreturns.com/n/QQQ,QQQA,QQEW,QTEC)，[ProShares](https://www.proshares.com/our-etfs/strategic/qqqa) |
| 15 | 分析师上调/盈利修正在 NDX 成分内轮动 | 检索 2023 年以后可核实的 NDX 专项回测 | — | **没有找到**可核实的 2023 年以后 NDX 专项证据。Schaeffer's 的副结论：被纳入且“买入”评级 ≥80% 的股票，1 年均值不到 +5%，只有 22% 跑赢 NDX；被剔除且“买入”评级 ≤20% 的股票，1 年均值约 +34%。也就是说，一致看好反而跑输 | — | 弱（证据缺口） | [Schaeffer's 2024](https://www.schaeffersresearch.com/content/analysis/2024/12/26/how-stocks-perform-after-nasdaq-100-rebalancing) |
| 16 | 科技子行业：NDX 科技板块等权（QTEC） | First Trust 实盘 | 2021-05-20 至 2026-10-26 | 年化 14.76%，QQQ 15.96%。2023 年 +67.0%，2024 年 +7.3%，2026 年至今 +32.2%。最大回撤 −45.5% | — | 中 | [totalrealreturns](https://totalrealreturns.com/n/QQQ,QQQA,QQEW,QTEC) |
| 17 | 半导体买入持有（SMH / SOXX） | 实盘 | 2012-03-21 至 2026-10-26 | SMH 年化 28.98%，SOXX 25.98%，QQQ 18.57%。SMH 最大回撤 −45.3%（2022）。截至 2026-10-26，SMH 距高点 −19.0%，但 2026 年至今仍 +50.4%。SMH 持仓 NVDA 20.6%、TSM 9.8% | SMH 费率 0.35% | 强（作为事实），但有明显的后视偏差 | [totalrealreturns](https://totalrealreturns.com/n/QQQ,QQQE,SMH,SOXX)，[stockanalysis SMH](https://stockanalysis.com/etf/smh/) |
| 18 | SMH/QQQ 相对强度轮动 | **本研究自算**：每月末若 SMH 过去 6 个月总回报高于 QQQ，下月持 SMH，否则持 QQQ；滞后 1 天执行，每边 5 bp | 2006-01 至 2026-10-26 | 全期年化 18.5%，QQQ 15.6%，SMH 18.4%。2006–2019：13.2%，QQQ 13.4%，**没有超额**。2020–2026：29.7%，QQQ 19.9%，SMH 35.2%。最大回撤 −56%，QQQ −53%。回看 3/4/5/7/8/9/12 个月：全期 16.5%–17.6%，2006–2019 全部 ≤ QQQ。按年计，2006–2015 几乎每年都输；2016 年后多数年份赢（2018、2022 输）。50% QQQ + 50% 轮动：全期 17.2%，2006–2019 为 13.4%，最大回撤 −54% | 约 2 次切换/年（21 年 43 次）。5,000 USD 每次切换的佣金约 0.70 USD，加点差 | 中到弱（样本内、依赖区间；2011 年前 SMH 为 HOLDRS 结构，数据连续性存疑） | 数据：Yahoo chart API |
| 19 | 行业/板块动量的衰减 | Quantpedia 综述（标普 9 个板块 SPDR） | 1998-12 至 2026-06 | ETF 普及后，传统多空板块动量的 alpha 明显下降；12 个月动量的价差在月初第 1 天为正，第 2–3 天反转 | — | 弱（二手来源，未核实） | [Quantpedia](https://quantpedia.com/how-to-improve-etf-sector-momentum/) |
| 20 | 隔夜漂移（期货） | Boyarchenko、Larsen、Whelan，*RFS* 36(9)，2023；作者 2026-07-01 在纽约联储博客跟进 | 1998–2020；跟进期 2021–2025 | 美东凌晨 2–3 点窗口在 1998–2020 年约 3.7%/年，占 ES 年化 5.9% 的六成以上。**2021 年后接近零**，NQ 和 YM 也一样。原因：收盘订单失衡的离散度从 6.5% 降到 2.9% | 只能用期货实现（本项目不允许） | 强 | [NY Fed SR917](https://www.newyorkfed.org/medialibrary/media/research/staff_reports/sr917.pdf)，[Liberty Street 2026-07](https://libertystreeteconomics.newyorkfed.org/2026/07/the-disappearing-overnight-drift/) |
| 21 | 隔夜与日内（现货 ETF） | Elm Wealth（Haghani 等），2025-03-03 | 约 30 年 SPY | 1 美元日内段只变成 1.20 美元，隔夜段变成 17.27 美元。作者明确不推荐，认为交易成本和冲击会吃掉大部分甚至全部收益；倾向用散户行为解释 | 每天 2 次全仓换手 | 中 | [Elm Wealth](https://elmwealth.com/night-shift/) |
| 22 | 隔夜 ETF 实盘 | NightShares NSPY / NIWM | 2022-06 至 2023-07 | NSPY −6.9%，标普 500 +22%；NIWM 下跌超过 10%，罗素 2000 +16%。2023-08-10 清盘 | ETF 每天两次全换手 | 中（实盘失败） | [WealthManagement 2023-07-20](https://www.wealthmanagement.com/etfs/night-effect-etfs-shut-down-overnight-stock-returns-elusive) |
| 23 | QQQ 隔夜持有（不持日内） | **本研究自算**，口径见上 | 2005-01-03 至 2026-10-26 | 隔夜年化 11.50%，日内 3.20%，买入持有 15.06%。2020–2026：隔夜 12.14%，日内 7.15%，买入持有 20.15%。2023–2026：隔夜 18.09%，买入持有 30.30%。逐年看日内段在 2023 年 +38.9%、2025 年 +4.0%、2026 年 +5.8%，并非一直为负。每次往返扣 2/5/10 bp 后，2023–2026 的隔夜年化分别为 12.28% / 4.10% / −8.23% | 约 250 次往返/年。5,000 USD 买约 7 股 QQQ（2026-10-26 收盘 712.20 USD），阶梯佣金每单最低 0.35 USD，单次往返约 1.4 bp 佣金加 0.2 bp SEC 费 | 中（算术稳健；开盘价是否可按此成交见下文） | 数据：Yahoo chart API |
| 24 | 板块 ETF 的隔夜与日内 | Salotra 等，*Risks* 14:84，2026；经 Harbourfront 博客转述 | 1999–2025，SPY 和 9 个板块 ETF | 隔夜多头在 10 只 ETF 上都优于日内多头，计入成本后收益下降。**没有与买入持有比较** | 高 | 弱（二手来源，未核实） | [Harbourfront 2026-04-26](https://harbourfrontquant.substack.com/p/overnight-vs-daytime-returns-in-sector) |
| 25 | 费率替换 | QQQM 与 QQQ 实盘 | 2024-10-24 至 2026-10-26 | QQQM 年化 20.90%，QQQ 20.84%。费率 0.15% 对 0.18% | 一次性换仓 | 强（机制确定，幅度很小） | [totalrealreturns](https://totalrealreturns.com/n/QQQ,QQQM,MAGS,QTOP)，[stockanalysis QQQM](https://stockanalysis.com/etf/qqqm/)，[Invesco QQQ](https://www.invesco.com/us/financial-products/etfs/product-detail?audienceType=Investor&ticker=QQQ) |

### 补充：NDX 规则要点（2026-05-01 生效版本）

- **年度重构：** 参考日是 11 月最后一个交易日。生效日是 12 月第三个周五之后第一个交易日的开盘。公告在生效日前第 6 个交易日盘后。2021–2025 年，平均 91.6% 的成分在前两步就确定了（前 75 名，加上前 100 名内的现有成分），所以 12 月的名单变动高度可预测，每年约 6 进 6 出，另有约 3 次非周期变动。
- **权重上限：** 单一公司超过 24% 时压到 20%。权重超过 4.5% 的公司合计 ≥48% 时，合计压到 40%。年度重构时还加两条证券层面的限制：单只超过 15% 时压到 14%；前 5 大合计 ≥40% 时压到 38.5%，其余单只不超过 4.4%。日终任一条件被突破，会触发**特别再平衡**。历史上只发生过 1998-12、2011-05、2023-07 三次。
- **集中度现状：** 截至 2025-12-31，前 10 大占 52% 权重，平均回报 35%。科技行业平均权重 61%，贡献了 2025 年指数总回报的 88%。NDX 2025 年总回报约 21%。
- **含义：** 上限规则会在机械上定期压低巨头权重，在巨头领涨的年份，这正是 QQQ 落后于“不封顶头部组合”（如 QTOP）的来源之一。但这种落后是否持续，取决于巨头能否继续领涨，不是规则本身能保证的超额。

### 补充：IBKR 实施成本（2026-10-27 抓取）

- 美股/ETF 佣金：IBKR Pro **阶梯**每股 0.0035 USD（月成交 ≤30 万股），每单最低 0.35 USD，最高为成交额的 1%。IBKR Pro **固定**每股 0.005 USD，每单最低 1.00 USD。0 佣金的 IBKR Lite 只对美国居民开放，**本项目账户不适用**。
- 第三方费用：SEC 交易费为卖出金额 × 0.0000206；NSCC/DTC 清算费每股 0.0002 USD；FINRA CAT 费每股 0.000003 USD。另有 NYSE/FINRA 转嫁费（按佣金比例）和交易所费用。
- 隔夜交易时段：IBKR 支持 1 万多只美股和 ETF 在美东 20:00 至次日 03:50 交易。这个时段的流动性和点差明显差于常规时段。本文的隔夜回测用的是官方开盘价和收盘价（相当于 MOO/MOC 竞价），没有用隔夜时段成交。
- 现金账户注意：T+1 结算下每天全仓往返，在现金账户里容易触发 good-faith violation，需要保证金账户。仅作提示，隔夜路线已否决。

---

## 三、对本项目的候选路线

以下规则都是**候选研究规则，不是交易建议**。任何上线前都必须按项目的 M1/M2 协议，用 Parquet 权威数据重算，做样本外检验，并做纸面观察。

### 规则 A（核心基线，可立即采用）：用 QQQM 买入持有作为不输基准的底仓

- 操作：用 QQQM 代替 QQQ 一次性建仓，股息到账后再投资，不在 12 月重构或季度再平衡窗口交易。
- 预期：相对 QQQ 约 +0.03 到 +0.06 个百分点/年（实测 2 年 +0.06）。年换手约为 0。
- 风险：这只是“几乎不输”，**不能**明显跑赢。QQQ 本身的最大回撤，按自算口径在 2007–2009 为 −53%，2022 为 −35%。2008 年那种级别的下跌就会触发 2,500 USD 清盘线，这个风险任何纯多头方案都无法消除。

### 规则 B（卫星候选，只做研究和纸面验证）：SMH/QQQM 6 个月相对动量月度切换，并加仓位上限

- 信号：每月最后一个交易日收盘后，比较 SMH 与 QQQM 过去 126 个交易日的总回报。SMH 更高，则下一个交易日收盘把卫星仓位换成 SMH，否则换成 QQQM。
- 仓位：卫星不超过总资金的 50%（建议从 30% 起），其余永久持有 QQQM。50/50 方案自算全期年化 17.2%，QQQ 15.6%，最大回撤 −54%。
- 成本：约 2 次切换/年。卫星 2,500 USD 时，每次切换佣金约 0.70 USD 加点差，约 3 bp。在 W-8BEN 下没有资本利得税。
- 必须先补的检验：
  1. 用 SOXX、不同月末日期、不同滞后天数复算；
  2. 2006–2015 年的子样本几乎每年都输，需要一个先验理由说明为什么现在不同；
  3. 加入组合层面的回撤阀门（例如净值低于 3,500 USD 时卫星强制回到 QQQM）并重新回测。**本文未测试这个阀门。**
- 反证：超额全部来自 2016 年以后的半导体周期和 AI 资本开支，等价于加了半导体 beta。SMH 前两大持仓（NVDA、TSM）合计约 30%，单票风险高。截至 2026-10-26，SMH 距高点已 −19%。6 个月相对动量在 9 月末为 +30%（10 月持 SMH），到 10-26 降到约 −0.5%，正处在切换边缘，近期可能来回切换。

### 规则 C（观察候选）：头部集中倾斜，QTOP 与 QQQM 二选一

- 想法：NDX 的上限规则会压低巨头权重。如果巨头继续领涨，不封顶的前 30 组合（QTOP）会小幅领先。
- 可操作形式：先**不交易**。用项目已有的历史成分和市值 Parquet 数据重建“NDX 前 10、前 30 市值加权组合”，回测 2006–2026。只有当它在 2006–2019 子样本中也稳定领先 QQQ，才考虑用 QTOP 替换部分核心仓位。
- 反证：只有不到 2 年实盘。MAGS 在 2026 年大幅落后，说明头部内部也会轮动。巨头领涨结束时（例如 2022 年、2026 年的 MAGS），这个方案会持续落后。

### 规则 D（事件观察，不交易）：特别再平衡和 Fast Entry 事件记录

- 当权重超过 4.5% 的成分合计逼近 48%，或出现 Fast Entry 公告时，记录被动卖出和买入名单、公告日和生效日，在纸面账户测试“生效日后持有被压权重巨头 3 到 12 个月”。
- 目前只有 2023-07 一个样本，不足以形成规则。

### 明确不推进的方向（附反证）

- **12 月重构的纳入/剔除套利：** 效应已消失（JF 2025）；近三年自算方向互相矛盾；被剔除股多是高波动个股，与用户否决的高波动个股路线相近。
- **等权和剔除头部（QQQE、QQEW、QNXT）：** 长期稳定落后，只在 2022 这类巨头杀跌年份领先。
- **NDX 成分内动量或质量成长精选（QQQA、NDXSE）：** 实盘和发行方回测都落后，与本项目每周漏斗选股的失败一致。
- **隔夜持有 QQQ：** 扣成本前就跑不赢买入持有；期货漂移自 2021 年起消失；隔夜 ETF 实盘清盘；每年约 250 次往返。

### 主要风险汇总

1. **区间依赖：** 近 10 年 NDX 的超额主要来自巨头和半导体。所有“看起来能赢”的方案（QTOP、SMH 轮动、MAGS）都是在押同一个方向，彼此不是独立证据。
2. **清盘线：** QQQ 本身历史回撤 −53%，SMH 超过 −60%。加入任何高 beta 卫星，都会提高触及 2,500 USD 的概率。
3. **数据和样本：** 自算部分使用 Yahoo 免费数据，未经项目权威数据复核。SMH 在 2011 年前是 HOLDRS 结构。QTOP、QNXT 实盘不到 2 年。
4. **规则变化：** 2026 年起的 Fast Entry、低流通股权重和季度剔除规则，会改变未来重构的可预测性和冲击，旧统计不一定适用。

---

## 四、来源列表

**指数规则与官方资料**
- Nasdaq Global Indexes，*2025 Nasdaq-100 Reconstitution and Performance Highlights*（2026-01，数据截至 2025-12-31）：https://indexes.nasdaqomx.com/docs/202601%20NDX%20Reconstitution%20and%20Performance%20Highlights.pdf
- Nasdaq-100 指数方法论（2026-05-01 生效版）：https://indexes.nasdaqomx.com/docs/Methodology_NDX.pdf
- Nasdaq-100 Index Consultation February 2026 – Summary of Responses and Conclusion：https://indexes.nasdaqomx.com/docs/Nasdaq-100_Index_Consultation_February_2026_Summary_of_Responses_and_Conclusion.pdf
- Nasdaq，*Growth and Quality: A Robust Formula for Screening Nasdaq-Listed Innovators*（NDXSE，2025-07）：https://indexes.nasdaqomx.com/docs/NDXSE_Research.pdf

**纳入/剔除与再平衡**
- Greenwood, R. & Sammon, M. (2025). The Disappearing Index Effect. *Journal of Finance* 80(2): 657–698：https://ideas.repec.org/a/bla/jfinan/v80y2025i2p657-698.html；NBER 工作论文 w30748：https://www.nber.org/system/files/working_papers/w30748/w30748.pdf
- Schaeffer's Research（2024-12-26），How Stocks Perform After Nasdaq-100 Rebalancing：https://www.schaeffersresearch.com/content/analysis/2024/12/26/how-stocks-perform-after-nasdaq-100-rebalancing
- Schaeffer's Research（2023-12-20），Removed NDX Stocks Likely to Outperform Those Added：https://www.schaeffersresearch.com/content/analysis/2023/12/20/removed-ndx-stocks-likely-to-outperform-those-added
- Niemelä, E. (2024). *Short Term Market Reactions to Nasdaq-100 Listings and Delistings in 2014–2023*（塔林理工本科论文）：https://digikogu.taltech.ee/en/Download/d08f2143-bae7-474a-a029-347fdeafa21a
- 早期研究（仅作背景，样本 1997–2015，未见近年复核）：Biktimirov & Xu (2019), *Journal of Asset Management*：https://ideas.repec.org/a/pal/assmgt/v20y2019i2d10.1057_s41260-019-00108-6.html
- MarketBeat（2023-07-12），Nasdaq 100 index shake-up rattles high-flying stocks of 2023：https://www.marketbeat.com/articles/nasdaq-100-index-shake-up-rattles-high-flying-stocks-of-2023/
- Global Trading，Tesla tips the scales（触发时合计 50.9%，二手来源，未核实）：https://globaltrading.net/?p=23732

**指数变体与 ETF 实盘**
- iShares QTOP 月报（截至 2026-09-30）：https://www.ishares.com/us/literature/fact-sheet/qtop-ishares-nasdaq-top-30-stocks-etf-fund-fact-sheet-en-us.pdf
- iShares QNXT 月报（截至 2026-09-30）：https://www.ishares.com/us/literature/fact-sheet/qnxt-ishares-nasdaq-100-ex-top-30-etf-fund-fact-sheet-en-us.pdf
- totalrealreturns（总回报，股息再投资，2026-10-27 抓取）：
  - https://totalrealreturns.com/n/QQQ,QTOP,QNXT,QQEW
  - https://totalrealreturns.com/n/QQQ,QQQE,SMH,SOXX
  - https://totalrealreturns.com/n/QQQ,QQQA,QQEW,QTEC
  - https://totalrealreturns.com/n/QQQ,QQQM,MAGS,QTOP
- First Trust QQEW 改换指数公告（经搜索摘要获得，二手来源，未核实全文）：https://www.businesswire.com/news/home/20251104125696/en
- ProShares QQQA 产品页：https://www.proshares.com/our-etfs/strategic/qqqa
- stockanalysis：QQQ https://stockanalysis.com/etf/qqq/ ，QQQM https://stockanalysis.com/etf/qqqm/ ，SMH https://stockanalysis.com/etf/smh/
- Invesco QQQ 产品页（费率 0.18%）：https://www.invesco.com/us/financial-products/etfs/product-detail?audienceType=Investor&ticker=QQQ

**行业轮动**
- Quantpedia，How to Improve ETF Sector Momentum（二手来源，未核实）：https://quantpedia.com/how-to-improve-etf-sector-momentum/

**隔夜效应**
- Boyarchenko, N., Larsen, L. C., Whelan, P. (2023). The Overnight Drift. *Review of Financial Studies* 36(9)；纽约联储 Staff Report 917：https://www.newyorkfed.org/medialibrary/media/research/staff_reports/sr917.pdf
- Liberty Street Economics（2026-07-01），The Disappearing Overnight Drift：https://libertystreeteconomics.newyorkfed.org/2026/07/the-disappearing-overnight-drift/
- Elm Wealth（2025-03-03），Still Working the Night Shift：https://elmwealth.com/night-shift/ （文中引用的 JOIM 2024 论文：https://joim.com/wp-content/uploads/emember/downloads/P0753.pdf ，经该页转述）
- WealthManagement.com（2023-07-20），'Night Effect' ETFs to Shut Down：https://www.wealthmanagement.com/etfs/night-effect-etfs-shut-down-overnight-stock-returns-elusive
- thetrading.tools，SPY 隔夜与日内统计（截至 2026-10-26）：https://www.thetrading.tools/weekday-analysis
- Harbourfront Quant（2026-04-26），转述 Salotra 等 (2026) *Risks* 14:84（二手来源，未核实）：https://harbourfrontquant.substack.com/p/overnight-vs-daytime-returns-in-sector

**IBKR 实施**
- IBKR 美股佣金与第三方费用：https://www.interactivebrokers.com/en/pricing/commissions-stocks.php
- IBKR 美股隔夜交易：https://www.interactivebrokers.com/en/trading/us-overnight-trading.php

**本研究自算数据源**
- Yahoo Finance chart API（免费日线，非权威，2026-10-27 抓取，仅用于初筛）：https://query1.finance.yahoo.com/v8/finance/chart/QQQ （SPY、SMH、QQQE 及重构相关个股同理）
