# 04 经典策略近年复验：扣成本后能否跑赢 QQQ

- 研究日期：2026-10-27。外部数据大多截至 2026-10-23 至 10-26；AAII 筛选数据截至 2026-09-30。
- 研究方法：只用公开网页（WebSearch / WebFetch）。本文没有运行本项目回测，也没有改动任何账户、研究记录或数据。
- 基准：QQQ 买入持有（含分红再投资的总回报）。基准不变。
- 用户约束：本金 5,000 USD，IBKR，W-8BEN（美国侧不征资本利得税，股息预扣 10%），只交易美股和美股 ETF，只用免费数据；净值不高于 2,500 USD 时必须清仓并终止。

## 时效规则与标注

1. 判断依据只用 2023 年以后发表的检验、复现或实盘，或覆盖 2024–2026 年的数据。原论文和原书只作为规则来源；2023 年以前的批评文献只作背景，单独注明。
2. 不编造数字。没能在原页面上看到的数字标"二手来源，未核实"。
3. 标注含义：
   - "已核实"：在原网页、PDF 或数据文件中看到了该数字。
   - "二手来源，未核实"：只见于搜索摘要或他人转述，原页面打不开（多为 403 或付费墙）。
   - "自算"：用已核实的年度数据连乘或换算得到，原来源没有直接给出。
4. 口径：
   - ETF 回报为名义美元，含分红再投资，已扣基金费率，但没有扣投资者自己的佣金、滑点和股息预扣。
   - AAII 筛选为价格口径（不含股息），不扣成本，每月全部调仓。
   - 指数回测（如 Invesco QQQ 15）按各自说明书口径。

## QQQ 基准数据

| 区间 | QQQ 总回报 | 来源与状态 |
| --- | --- | --- |
| 2020 / 2021 / 2022 | +48.62% / +27.42% / −32.58% | totalrealreturns（已核实） |
| 2023 / 2024 / 2025 | +54.86% / +25.58% / +20.77% | totalrealreturns（已核实）；chartrow 给出相同的取整值 |
| 2026 年初至 10-23/26 | +16.33% | totalrealreturns（已核实）；chartrow 为 +16.3%，并显示当前距历史高点 −6.2% |
| 2023-01-01 起累计 | +173.2% | 自算 |
| 2022-01-01 起累计 | +84.2% | 自算 |
| 2024-01-01 起累计 | +76.4% | 自算 |
| 最大回撤（2010 年以来） | −35.12%（2021-12-27 至 2022-11-03） | totalrealreturns（已核实） |
| 2025 年关税下跌 | 约 −23%（2025-02-19 至 04-08） | 纳斯达克研究的转述（二手来源，未核实） |
| 2000 / 2001 / 2002 | −36.1% / −33.3% / −37.4%，三年连乘约 −73% | chartrow 第三方估算（年度值已核实，连乘为自算） |
| 2008 | −41.9% | chartrow 第三方估算 |
| 官方交叉核对：财年（截至 9-30）NAV 总回报 | FY2023 +34.98%，FY2024 +37.21%，FY2025 +23.63%；2025-10-01 至 2026-03-31 为 −3.63% | Invesco QQQ 2026 年半年报 N-CSRS（已核实） |

QQQ 的股息约为每年 0.6%（chartrow 2025 年股息贡献），10% 预扣的拖累约每年 0.06%（自算）。

## 一、结论摘要

1. **1 倍仓位的择时和日历规则，在 2023–2026 年全部跑输 QQQ。**
   - GTAA：Cambria GMOM 实盘 2023 年以来累计 +49.1%，同期 QQQ +173.2%（自算）。
   - Sell in May：2022-11 至 2026-10 只持冬半年 +48.5%，全程持有 +162.8%（自算）。
   - 波动率目标：Invesco QQQ 15 指数 2023–2025 年累计 +58.1%，同期 QQQ +134.9%（自算）。
   - GEM、月末效应、选举周期也都跑输。
   - 这些规则只在 2022 年减少了亏损，随后错过 2023 年的反弹和 2025 年 4 月后的 V 形反弹。它们是降低暴露的工具，不是超额收益的来源。
2. **经典选股规则全面落后，证据强。**
   - 2023-01 至 2026-09，AAII 模型组合：神奇公式 +35.2%，F-Score −6.9%，CAN SLIM 最好的版本 +84.9%，道指狗股 +27.5%。这些都是价格口径、未扣成本；同期 QQQ 约 +184%。
   - 真实实盘的 FFTY（IBD 50）：2015 年成立至 2024 年底年化 1.88%，同期标普 500 为 13.29%；年换手 1,304%，2022 年 −51.09%。
3. **ETF 层面的行业动量轮动全部落后；宽基动量 ETF 能否跑赢取决于起点。**
   - FV、XLSR 和用 French 十行业数据回测的"持前 3 名"规则都大幅落后 QQQ。
   - SPMO 从 2022 或 2024 年初起算跑赢 QQQ，从 2023 年初起算落后；2019-05 以来年化 19.83%，QQQ 为 20.77%。
   - 多空动量因子 2023、2025 年为负。2026 年 7 月，高贝塔动量篮子把全年涨幅全部回吐。
4. **唯一在回测里明显跑赢 QQQ 的经典思路是 LRS（均线过滤 + 杠杆），但超额来自杠杆，不是均线。**
   - 2010-02 至 2026-10：TQQQ+200 日均线回测年化 30.3%，直接持有 TQQQ 年化 41.6%，QQQ 年化 19.20%。
   - 均线的作用是把杠杆 ETF 持有时 −64% 到 −82% 的回撤压下来。
   - 证据弱：2023 年后没有同行评审检验，也找不到 2022–2026 年的分年度结果；按 LRS 规则运作的公开虚拟组合近 1 年为 −0.8%。
5. **2023–2026 年 QQQ 的收益高度集中在大型科技股**（XLK 2023 年以来 +207.1%）。分散、价值、低波动或降低暴露的规则都会因此吃亏。在经典策略里，想跑赢 QQQ 实际上只剩"更集中"或"更多杠杆"两条路，而两条路都会提高触及清盘线的风险。
6. **−50% 清盘线改变了比较的含义。**
   - QQQ 本身 2000–2002 年三年连乘约 −73%，2008 年 −41.9%（第三方年度数据）。没有过滤的 QQQ 买入持有在这些时期同样会触线。
   - QLD 2010 年以来最大回撤 −63.68%。
   - 对本账户来说，趋势过滤的首要价值是避免永久终止，其次才是收益。
7. **可执行的候选只有三条**：
   - 主候选：纳指 200 日均线 + 1.5 倍暴露（QQQ、QLD 各半）。
   - 激进对照：同一信号下的 2 倍 QLD 版本。
   - 低换手候选：QQQ 与 SPMO 固定比例组合。
   - 三条都需要先用本项目数据在包含 2000–2002、2008、2020、2022、2025 年的长历史上复算，并预先登记参数，才能进入 paper 阶段。

## 二、策略表

证据强度的含义：

- **强**：有实盘产品或同行评审的样本外检验，并且多个来源一致。
- **中**：多个独立的模型或回测结论一致，但缺少实盘。
- **弱**：只有单一来源，或只有厂商、个人回测；或样本很短；或各来源互相冲突。

强度评的是"能否跑赢 QQQ"这一结论的证据，不是策略本身好坏。

| 策略 | 原始出处（年份） | 规则要点 | 发表后到近年的表现，及同期 QQQ | 换手与成本 | 证据强度 | 链接 |
| --- | --- | --- | --- | --- | --- | --- |
| 双动量 GEM / 绝对动量 | Antonacci《Dual Momentum Investing》（2014）；绝对动量论文（2012–2013） | 每月末比较美股（SPY）与非美股（EFA/VEU）的 12 个月总回报。若美股 12 个月回报高于 T-bill，持有两者中较强的一只；否则持有综合债（AGG）。任何时候只持 1 只 | AlgoLab 2026-09 的复现（2008-06 至 2026-08，未计成本）：GEM 年化 8.62%、最大回撤 −33.72%；SPY 年化 11.85%、回撤 −50.70%（已核实）。分年度：GEM 2020 年 +2.6%、2022 年 −16.9%、2023 年 +7.4%，同年 QQQ 分别为 +48.62%、−32.58%、+54.86%。Inwestomat 2026-07 的变体（含新兴市场）2006–2025 年约 9.1%，标普约 10.9%（已核实）。QQQ 2008–2025 年化约 15.5%（自算）。**大幅跑输**；2022 年股债同跌，债券几乎没有起到保护作用 | 每年约 1.8–2.7 次全仓切换。每笔 0.1% 时成本可以忽略；每笔 0.5% 时长期年化约降低 2 个百分点（Inwestomat 测算） | 中：两份 2026 年的独立复现方向一致，但都是个人博客，而且没有官方实盘。Allocate Smartly 和 optimalmomentum.com 的数据没有取得 | [AlgoLab](https://algolab.co.kr/blog/dual-momentum-backtest-gem-python-2026)、[Inwestomat](https://inwestomat.eu/strategia-gem/) |
| GTAA / 10 个月均线 | Faber《A Quantitative Approach to Tactical Asset Allocation》（2007；2013 更新） | 美股、发达市场、10 年美债、商品、REIT 各 20%。月末收盘价高于 10 个月均线时持有，否则该份额转入 T-bill | Zarattini / Concretum 复现（SSRN 5230603，2025-04；博客 2026-06-23）：原样本 1972–2005 年化 11.7%；2006 至 2025-03 的样本外年化 6.05%，夏普 0.68，最大回撤 11.7%（已核实；据 Concretum 网站，这一复现用的是 200 日均线）。Cambria GMOM 实盘（趋势 + 动量，费率 0.95%），2014-12 至 2026-10 年化 6.08%、回撤 −25.02%；同期 QQQ 年化 18.56%、回撤 −35.12%（已核实）。GMOM 对 QQQ 分年度：2022 年 −2.82% 对 −32.58%，2023 年 +0.66% 对 +54.86%，2024 年 +6.75% 对 +25.58%，2025 年 +20.62% 对 +20.77%。**明确跑输** | 月度检查，需要 5–6 只 ETF。每年换手次数没有找到 | 强（仅就"跑不赢 QQQ"而言）：19 年样本外加 12 年实盘，结论一致 | [Concretum](https://concretumgroup.substack.com/p/global-tactical-asset-allocation)、[totalrealreturns GMOM](https://totalrealreturns.com/n/GMOM,GAA,QQQ) |
| Leverage for the Long Run（LRS） | Gayed & Bilello（2016） | 原文：标普 500 收盘高于 200 日均线时持有 1.25、2 或 3 倍杠杆，否则持 T-bill；日频，约每年切换 5 次。纳指版本：QQQ 高于 200 日均线时持 TQQQ 或 QLD，否则持短债 | 原文背景（1928–2015，CXO 2016 年的摘要）：200 日均线不加杠杆，夏普 0.60、回撤 −50%；2 倍 LRS 夏普 0.51、回撤 −78%；买入持有夏普 0.30、回撤 −86%。<br>2023 年后：Composer 回测（QQQ 均线 → TQQQ，否则 BSV；2010-02-11 至 2026-10-27，含滑点）年化 30.3%，夏普 0.79；同期 SPY 年化 14.46%，夏普 0.88（已核实）。同期 QQQ 年化 19.20%，TQQQ 持有 41.6%、回撤 −81.66%，QLD 持有 32.45%、回撤 −63.68%（已核实）。<br>Financial Wisdom 2025-08（作者自报，不计成本）：TQQQ+225 日均线 2011–2025 累计 +4,067%、回撤 69.9%，TQQQ 持有 +10,806%、回撤 81.7%。<br>wikifolio 的 LRS 虚拟组合自 2021-08-31 起累计 +131.8%，年化 17.3%，**近 1 年 −0.8%**，1 年波动率 55.8%（已核实；所用指数和计价货币未公开）；同期 QQQ 近 1 年约 +21.9%（二手来源，未核实）。<br>**2010 年后的回测跑赢 QQQ，但跑输直接持有杠杆 ETF**；2022–2026 年的分年度结果找不到 | 日频信号，震荡市里反复进出。Allocate Smartly 2026-08 测算：按每笔 0.1% 计，日频交易的战术配置策略摩擦拖累超过每年 2% | 弱：只有厂商和个人回测加一个虚拟组合，回撤数字互相冲突（Composer FAQ 给出的 31.58% 与其他来源不自洽，本文不采用）。Composer 自己写明样本外风险调整后表现更差 | [CXO 摘要](https://www.cxoadvisory.com/volatility-effects/leveraging-the-u-s-stock-market-based-on-sma-rules/)、[Composer](https://www.composer.trade/trading-strategies/tqqq-based-on-200d-ma-X3BQchFSANrGzrIKnDO6)、[wikifolio](https://www.wikifolio.com/en/int/w/wf00lrs200) |
| 神奇公式 | Greenblatt《The Little Book That Beats the Market》（2005） | 美股（剔除金融和公用事业），按 EBIT/EV 与 ROC 两项排名之和取前 20–30 只；每 2–3 个月买入 5–7 只，每只持有约 1 年 | AAII 模型（价格口径，不扣成本）：2023 年 +13.5%、2024 年 +17.2%、2025 年 +17.9%、2026 年至 9-30 为 −13.8%，累计 +35.2%（年度已核实，累计自算）；同期 QQQ 约 +184%（自算）。<br>Gotham Enhanced 500（GSPY，自有估值模型，不是纯神奇公式）：2023 年 +25.79%、2024 年 +23.67%、2025 年 +18.14%；5 年年化 14.25%，标普 500 为 14.42%（已核实）。<br>Gotham 1000 Value（GVLU）：2023–2025 年分别为 +18.00%、+11.15%、+10.98%（已核实）。<br>Validea 模型自 2005 年起落后市场 175.9 个百分点（已核实）。<br>Schwartz & Hanauer（SSRN，2024-12）：2000 年后 alpha 衰减，2018–2020 年有明显的相对回撤（Quantpedia 摘要已核实）。**大幅跑输** | 每年换手约 100%。分 30 只时每只约 167 USD，按每单最低 1 USD，佣金约占本金 1.2%/年（自算）。GSPY 换手 135%，GVLU 210% | 中：多个来源结论一致，但纯神奇公式没有实盘产品，学术数据只到 2022 年 | [AAII](https://www.aaii.com/stock-screens/performance)、[Gotham 招募书](https://www.sec.gov/Archives/edgar/data/1742912/000199937126001640/gotham-485bpos_012626.htm)、[Quantpedia](https://quantpedia.com/out-of-sample-test-of-formula-investing-strategies/) |
| Piotroski F-Score | Piotroski（2000） | 在市净率最低的 20% 股票中，用 9 项财务信号打分，买入 8–9 分者，每年调仓 | AAII 模型：2023 年 +4.6%、2024 年 +6.6%、2025 年 −1.1%、2026 年至 9-30 为 −15.6%，累计 −6.9%（年度已核实，累计自算）；同期 QQQ 约 +184%。<br>AAII 2024-05 的文章称 1998 至 2024-04 年化 14.0%，同期标普 6.1%（价格口径，已核实），说明长期优势主要来自 2000 年代。<br>Validea 模型自 2004 年起落后市场 153.1 个百分点（已核实）。**明显跑输** | 原版每年调仓，AAII 版每月调仓。多为小盘、微盘股，买卖价差大。AAII 模型 2015 年 −40.5%、2018 年 −36.1%、2022 年 −27.2% | 中：方向清楚，但只有模型数据，没有实盘 | [AAII](https://www.aaii.com/stock-screens/performance)、[AAII 2024 文章](https://www.aaii.com/stockideas/article/212258-separating-winners-from-losers-low-price-to-book-stocks) |
| CAN SLIM | O'Neil《How to Make Money in Stocks》（1988） | 季度 EPS 增长 ≥25%、年度 EPS 持续增长、新产品或新高、相对强度领先、机构持仓、大盘向上；亏损 7–8% 止损。FFTY 跟踪的 IBD 50：约 7,000 只股票按 11 个因子打分取前 50，每周重构 | FFTY 实盘：2022 年 −51.09%，2023 年 +12.40%，2024 年 +18.38%，2025 年 +23.40%，2026 年至今 −4.05%；2023 年以来累计 +57.5%，同期 QQQ +173.2%（年度已核实，累计自算）。<br>招募书（2025-02）：成立以来年化 1.88%，标普 13.29%；5 年年化 −2.96%（已核实）。2026-04 重组后改名 CapForce IBD 50 ETF（已核实）。<br>AAII 三个 CAN SLIM 模型，2023 至 2026-09 累计 +38.8%、+84.9%、−9.0%（自算）。**全部跑输** | FFTY 年换手 1,304%，净费率 0.80%。若用 5,000 USD 自行复制，佣金约占 2.6%/年，另加滑点（自算） | 强：扣费后的真实实盘近 10 年持续落后 | [etfreplay FFTY](https://www.etfreplay.com/etf/ffty)、[FFTY 招募书](https://www.sec.gov/Archives/edgar/data/1415726/000121390025018623/ea0230462-01_485bpos.htm) |
| 道指狗股 | O'Higgins《Beating the Dow》（1991） | 每年末从道指 30 只成分股中选股息率最高的 10 只，等权持有一年 | 2023 年：总回报约 14.5%，道指 16.0%（二手来源，未核实）；Motley Fool 称价格口径落后道指约 4 个百分点（已核实）。<br>2024 年：截至 12-20 约 +2.64%，标普 +24.77%（二手来源，未核实）。<br>2025 年：约 +19%，跑赢标普和道指（Dividend Power，已核实），但不及 QQQ 的 +20.77%。<br>2026 年至 7-27：+12.3%，道指 +7.4%（InvestmentNews，已核实）。<br>AAII 月度调仓版 2023 至 2026-09 累计 +27.5%（自算）。2023–2025 年**大幅落后 QQQ** | 每年 10–20 单，佣金约占 0.2–0.4%/年。2026 年名单股息率 3.39%，10% 预扣约拖累 0.34%/年（自算） | 强：规则简单，多个来源一致 | [Dividend Power](https://www.dividendpower.org/dogs-of-the-dow-2026/)、[InvestmentNews](https://investmentnews.com/equities/dogs-of-the-dow/267611) |
| 12-1 横截面动量 | Jegadeesh & Titman（1993）；Carhart（1997） | 按 t−12 至 t−2 月的收益排序（跳过最近 1 个月），多头取前 30%，每月调仓。MTUM 季度重构、约 125 只；SPMO 取标普 500 中风险调整动量最高的约 100 只；QMOM 取约 50 只等权，每月调仓 | French 多空 Mom 因子（不扣成本）：2023 年 −24.31%，2024 年 +19.72%，2025 年 −2.27%，2026 年 1–8 月约 +3.9%（其中 7–8 月合计约 −17%）（据 French 数据文件计算，未独立复核）。<br>多头 ETF 见下方补充表：SPMO 从 2022 或 2024 年初起算跑赢 QQQ，从 2023 年初起算落后；MTUM 只在 2024 年起算时跑赢；QMOM、PDP 落后。<br>2019-05-21 至 2026-10-23：SPMO 年化 19.83%、回撤 −30.95%；QQQ 20.77%、−35.12%（已核实）。<br>2026 年 7 月：高盛美国高贝塔动量篮子把年内约 +60% 的涨幅全部回吐（Kayne Anderson 图表，读图近似） | MTUM 年换手 111%，费率 0.15%；SPMO 费率 0.13%。投资者自己持有一只 ETF，每年 0–2 笔交易 | 中偏弱：有效样本只有约 3.8 年，结论依赖起点；从约 28 只美国动量 ETF 中事后挑出 SPMO，有选择偏差 | [totalrealreturns](https://totalrealreturns.com/n/QQQ,SPMO,SECT,PTF,AMOM)、[French 数据](https://mba.tuck.dartmouth.edu/pages/faculty/ken.french/ftp/F-F_Momentum_Factor_CSV.zip)、[Kayne](https://kayne.com/wp-content/uploads/High-Beta-Momentums-Leadership-Unraveled-Quickly-in-July.pdf) |
| 行业动量轮动 | Moskowitz & Grinblatt（1999）；Faber《Relative Strength Strategies for Investing》（2010） | 10 个行业按过去 1、3、6、12 个月收益排名，等权持有前 1–3 名，每月末调仓 | French 十行业"12-1 持前 3"回测：2023-01 至 2026-08 累计 +50.0%，市场 +109.9%；同一规则 1990–2022 年年化 14.1%，市场 9.8%，**历史优势在 2023 年后消失**（毛收益，本研究自算，未独立复核）。<br>实盘 ETF：FV（DWA 行业相对强度，持 5 只）2023 年以来 +64.1%，XLSR +74.7%，SECT（基本面选行业，不是动量）+88.2%；同期 QQQ +173.2%（年度已核实，累计自算）。**全部大幅落后** | 自建 3 只行业 ETF、每月调仓，每年约 17 笔订单。FV 总费用 0.89%（含底层基金费）。12-1 前 3 规则年化单边换手约 280% | 中到强（就"跑输"而言）：多个独立实盘产品与回测一致 | [FV](https://www.ftportfolios.com/ETF/FV)、[totalrealreturns FV](https://totalrealreturns.com/n/QQQ,FV,FVC,XLK,SPY)、[French 行业数据](https://mba.tuck.dartmouth.edu/pages/faculty/ken.french/ftp/10_Industry_Portfolios_CSV.zip) |
| 52 周新高动量 | George & Hwang（2004） | 按"现价 ÷ 52 周最高价"排序，多前 30%、空后 30%，持有 6 个月，组合重叠 | **没有找到** 2023 年后覆盖 2024–2026 年美股的复现，也没有跟踪这一信号的美国 ETF。Quantpedia 策略页（回测 1963–2009）注明"样本外回测略为负"（已核实）。Byun & Jeon（FAJ 2023，样本到 2015 年）认为用 52 周高点信号中性化可以减弱动量崩溃（二手来源，未核实） | 原规则是多空，需要上千只股票，5,000 USD 无法执行 | 弱 | [Quantpedia](https://quantpedia.com/strategies/52-weeks-high-effect-in-stocks) |
| 纳指 100 内部动量（补充） | Dorsey Wright 相对强度 | QQQA：在纳指 100 中按相对强度选 21 只，等权（二手来源，未核实） | QQQA 2023 年 +24.98%、2024 年 +16.17%、2025 年 +9.87%、2026 年至今 +31.74%；2023 年以来 +110.2%，QQQ +173.2%；2021-05 以来年化 9.23%，QQQ 15.96%（已核实）。<br>PTF（DWA 科技动量）2023 年以来 +184.6%，略胜 QQQ，但 2025 年只有 +5.68%，最大回撤 −44.88%（已核实）。PTF 本质上是把高波动个股动量装进 ETF | QQQA 费率 0.58%，规模约 1,000 万美元，有清盘风险（二手来源，未核实） | 中偏弱 | [totalrealreturns QQQA](https://totalrealreturns.com/n/QQQ,QQQA,XMMO,QQEW) |
| 月末效应（TOM） | Ariel（1987）；Lakonishok & Smidt（1988） | 月末最后 1 天到下月第 3 个交易日（或"最后 4 天 + 前 3 天"）持有，其余时间空仓，在场时间约 1/3 | Han, Han & Tian（Finance Research Letters 71，2025）：TOM 效应"2001 年后完全消失"，原因是交易成本下降（摘要已核实）。<br>QuantifiedStrategies（2025-09，标普 1960 年至今，不含股息）：年化 7%，买入持有 7.5%；最大回撤 27%，买入持有 56%（已核实）。<br>2023 年后**没有找到**针对 QQQ 或纳指 100 的 TOM 回测。**本质上是降低暴露** | 每年约 24 笔订单。按每单最低 1 USD，约占本金 0.5%/年（佣金标准为二手来源，未核实） | 中偏强（否定该效应） | [Han 等](https://ideas.repec.org/a/eee/finlet/v71y2025ics1544612324014909.html)、[QuantifiedStrategies](https://quantifiedstrategies.substack.com/p/turn-of-the-month-strategy) |
| 总统选举周期 | Hirsch《Stock Trader's Almanac》（1967 年起） | 大选前一年最强；中期选举年二、三季度偏弱，四季度开始转强 | First Trust（2026-06）统计 96 年标普平均总回报：任期第 1 年 10.66%、第 2 年 7.37%、第 3 年 18.01%、第 4 年 10.80%（已核实）。<br>实际 QQQ：2023 年 +54.86%，2024 年 +25.58%，2025 年 +20.77%，2026 年（中期选举年）至今 +16.33%；2026 年第二季度约 +27.7%（据 chartrow 月度数据自算），"二、三季度偏弱"的预期落空。<br>只在奇数年持有 QQQ：2023 年以来 +86.9%，全程持有 +173.2%（自算） | 换手极低 | 弱：每个周期只有一个样本点 | [First Trust](https://www.ftportfolios.com/Commentary/Insights/2026/7/6/election-client-resource-kit---june-2026) |
| Sell in May / 万圣节效应 | Bouman & Jacobsen（2002） | 11 月至次年 4 月持有，5–10 月持现金 | QQQ 近四个"夏半年"全部为正：2023 年 +9.1%，2024 年 +14.3%，2025 年 +32.7%，2026 年 5 月至 10-26 为 +7.0%。2022-11 至 2026-10，只持冬半年 +48.5%，全程持有 +162.8%（据 chartrow 月度数据自算）。Jacobsen 在 2023 年后的更新**没有找到** | 每年 2 笔交易；真正的成本是错过夏半年的上涨 | 中：长期跨国证据较强，但近 4 年对 QQQ 恰好相反 | [chartrow 月度](https://chartrow.com/quote/qqq/monthly-returns) |
| 波动率管理组合 | Moreira & Muir（Journal of Finance，2017） | 暴露与上月已实现方差成反比，用常数缩放到与原组合相同的长期波动，杠杆无上限 | 背景批评（2023 年前）：Cederburg 等（JFE 2020）检验 103 个策略，波动率管理版本在样本外"并不系统性跑赢"；Barroso & Detzel（JFE 2021）发现扣成本后非市场因子的超额收益约为零；Bongaerts 等（FAJ 2020）发现常规波动率目标在全球股市不能持续改善表现（摘要均已核实）。<br>2023 年后：Invesco QQQ 15 指数（以 QQQ 为核心，15% 波动目标，每日调整，仓位 0–150%，2025-03 发布、此前为回测；超额收益口径，每年扣 50bp，现金不计息）分年度为 2022 年 −15.53%、2023 年 +26.18%、2024 年 +17.50%、2025 年 +6.65%，3 年年化 10.03%（截至 2026-08-31，已核实）。2023–2025 年累计 +58.1%，QQQ +134.9%（自算）。由于口径扣除了现金收益，这个对比会夸大差距，但逐年都落后。<br>Man Group（2025-06）：2025 年 4 月的 V 形反弹中，波动率缩放策略减仓后错过了大部分反弹（已核实，没有给出具体数字）。<br>路透（2026-10-01）：波动率控制基金的股票仓位处于 2010 年以来第 98 百分位；巴克莱测算轻度回调就会触发超过 1,000 亿美元的卖盘（已核实） | 每日或每月调整，每年 12–250 笔订单 | 中偏强（就"不能带来超额收益"而言）：学术样本外检验与 2023–2026 年的 QQQ 指数数据一致 | [Invesco QQQ15](https://invesco.com/content/dam/invesco/indexing/en/documents/Invesco-QQQ15-Index-Fact-sheet.pdf)、[Cederburg 等](https://www.lehigh.edu/~xuy219/research/COWY.pdf)、[Man Group](https://www.man.com/special/v-shaped-recoveries) |

### 补充表：2023 年以来的 ETF 实盘与 QQQ 对照

数据为含分红的年度总回报，单位为百分比，2026 年截至 10-23 或 10-26。年度数字已核实，来自 totalrealreturns 和 etfreplay；累计收益为自算。

| 代码 | 策略类型 | 2022 | 2023 | 2024 | 2025 | 2026 年至今 | 2023 年以来累计 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| QQQ | 基准 | −32.58 | 54.86 | 25.58 | 20.77 | 16.33 | **+173.2%** |
| XLK | 科技板块（参照） | — | 56.02 | 21.63 | 24.61 | 29.88 | +207.1% |
| PTF | DWA 科技动量 | −31.75 | 33.73 | 43.65 | 5.68 | 40.18 | +184.6% |
| SPMO | 标普 500 动量 | −10.46 | 17.56 | 45.82 | 26.58 | 18.50 | +157.1% |
| MTUM | MSCI 美国动量 | — | 9.15 | 32.89 | 22.15 | 18.15 | +109.3% |
| QQQA | 纳指 100 内部动量 | −29.08 | 24.98 | 16.17 | 9.87 | 31.74 | +110.2% |
| PDP | DWA 动量 | — | 20.88 | 26.06 | 8.37 | 16.33（与 QQQ 完全相同，需复核） | +92.1% |
| SECT | 行业轮动（基本面） | −12.80 | 21.10 | 18.61 | 17.80 | 11.22 | +88.2% |
| XLSR | 主动行业轮动 | — | 18.95 | 17.60 | 17.34 | 6.46 | +74.7% |
| FV | DWA 行业相对强度 | — | 11.35 | 14.73 | 7.23 | 19.77 | +64.1% |
| SDOG | 行业高股息（不是道指狗股） | −0.21 | 4.21 | 14.69 | 11.12 | 23.57 | +64.1% |
| QMOM | 小规模动量 | — | 9.50 | 30.43 | 2.36 | 10.47 | +61.5% |
| FFTY | CAN SLIM / IBD 50 | −51.09 | 12.40 | 18.38 | 23.40 | −4.05 | +57.5% |
| GMOM | 趋势 + 动量（Faber） | −2.82 | 0.66 | 6.75 | 20.62 | 15.06 | +49.1% |

表注：

- MTUM 2026 年至今的数字有分歧：BlackRock 官网 NAV 口径为 +16.16%（截至 10-23，已核实），totalrealreturns 为 18.15%。
- 只有 PTF 和行业 ETF XLK 在 2023 年以来超过 QQQ。PTF 2025 年只有 +5.68%，最大回撤 −44.88%；XLK 是单一行业集中押注，不属于本文检验的经典规则。

## 三、对本项目的候选路线

### 共同前提

- **对照组**：
  - QQQ 买入持有，采用同样的整股和成本规则；
  - QQQ 1 倍加 200 日均线；
  - QLD 买入持有。
  - 设这三组的目的，是把"超额收益来自杠杆"与"超额收益来自过滤"分开。
- **成本**：沿用本项目的两档成本。正常档每笔 1 USD、单边 5 bps；压力档 2 USD、10 bps。比较时要求两档成本下都超过 QQQ。
- **执行**：决策会话收盘后计算信号，下一会话开盘成交；整股；不融资。
- **清盘线**：收盘净值不高于 2,500 USD 时，下一会话开盘清仓并永久终止。回放要用滚动起点（例如每月一个起点）统计终止比例，不能只看一个起点。
- **长历史**：需要覆盖 2000–2002、2008、2020、2022 和 2025 年。QLD 于 2006 年上市，之前的部分只能用纳指 100 日收益乘以 2 再扣费用来合成，并注明这是合成数据。
- **参数登记**：所有参数事先登记。2023–2026 年已经被本文观察过，不能再当作样本外区间。

### 候选 1（主候选）：纳指 200 日均线 + 1.5 倍暴露

- **交易什么**：QQQ、QLD（2 倍纳指 100 日收益），以及短期国债 ETF（SGOV 或 BIL）或现金。
- **规则**：
  - 每个交易日收盘后，比较 QQQ 复权收盘价与其 200 日简单均线。
  - 收盘高于均线：持有 50% QQQ + 50% QLD，名义上约为 1.5 倍纳指 100 日收益。
  - 收盘不高于均线：全部转入短期国债 ETF 或现金。
- **何时调仓**：
  - 信号翻转后，在下一会话开盘全仓切换。
  - 信号不变时，只在 QQQ 与 QLD 的比例偏离 50/50 超过 5 个百分点时再平衡（每月检查一次）。
  - 主规则按原文不设缓冲带。敏感性对照为 ±1% 缓冲带和连续 3 日确认，也要事先登记，并按长历史的整体结果取舍。
- **为什么有机会跑赢**：
  - LRS 的收益来源是在上升趋势中加杠杆。2010–2026 年，QLD 持有年化 32.45%，QQQ 为 19.20%。
  - 均线的作用是在长期熊市中离场。这同时是本账户避免触及 −50% 清盘线的主要手段：QQQ 自身 2000–2002 年约 −73%。
  - 选 1.5 倍是在收益与清盘线之间的折中。这是判断，不是证据：纳指 100 的波动约为标普的 1.3 倍，1.5 倍纳指的波动大致相当于 2 倍标普。
- **主要风险**：
  - 均线滞后。2020 年 2–3 月和 2025 年 2–4 月这类急跌，在跌破均线之前就要先承受 1.5 倍的损失。
  - 震荡市反复进出。例如有报道称 QQQ 自 2025-03-05 起跌破 200 日均线（二手来源，未核实），4 月又出现 V 形反弹。
  - 杠杆 ETF 在高波动时有损耗，QLD 费率也高于 QQQ。
  - 样本偏差：2010 年后纳指是长期牛市。
  - 短债 ETF 分红在 W-8BEN 下是否会被预扣 10%（利息类股息可能豁免），本文未核实，需要在 IBKR 实际确认。
- **反证**：
  - 2010–2026 年，TQQQ+200 日均线回测的夏普为 0.79，低于 SPY 的 0.88；直接持有 TQQQ 的年化更高（41.6%）。这说明在牛市里均线本身是成本。
  - wikifolio 的 LRS 虚拟组合近 1 年为 −0.8%。
  - Composer 自己写明样本外的风险调整表现更差。
  - LRS 原文中，2 倍版本在 1928–2015 年的最大回撤仍有 −78%。
  - 2023 年以后没有同行评审检验。
- **淘汰条件**：出现以下任一情况即淘汰。
  - 长历史回放中，两档成本下的年化收益都不高于 QQQ。
  - 滚动起点的终止比例超过用户事先设定的阈值。

### 候选 2（激进对照）：同一信号，100% QLD

- **交易什么**：收盘高于 200 日均线时持 100% QLD，否则持短期国债 ETF 或现金。调仓规则与候选 1 相同。
- **为什么列出**：用来测量杠杆从 1.5 倍提高到 2 倍，能带来多少额外收益、增加多少终止概率。原文 LRS 的主要检验对象就是 2 倍版本。
- **主要风险**：
  - QLD 持有的最大回撤为 −63.68%。加均线后的回撤缺少可靠数据；Financial Wisdom 报告的 3 倍版本（TQQQ+225 日均线）仍有 69.9%。
  - 账户早期还没有盈利缓冲时，一次急跌加一次反复进出就可能接近清盘线。
- **反证**：与候选 1 相同。另外，任何 3 倍版本（TQQQ）都不应进入候选，因为其持有回撤为 −81.66%。
- **使用条件**：只有在候选 1 通过回放，且 2 倍版本的终止比例同样可以接受时，才考虑进入 paper 阶段；否则只作为研究对照。

### 候选 3（低换手）：QQQ 70% + SPMO 30% 固定比例

- **交易什么**：QQQ 和 SPMO（标普 500 中风险调整动量最高的约 100 只，费率 0.13%）。
- **何时调仓**：每年第一个交易日再平衡到 70/30；每月检查一次，偏离超过 5 个百分点时提前再平衡。每年约 2–4 笔订单。70/30 是事先给定的比例，没有经过优化。
- **为什么有机会跑赢**：
  - SPMO 从 2022 年初起算累计 +130.2%，同期 QQQ +84.2%；从 2024 年初起算 +118.7%，QQQ +76.4%。
  - 2022 年 SPMO 只跌 −10.46%，QQQ 跌 −32.58%。
  - 当市场领涨扩散到纳指以外，或纳指龙头短暂失速时，动量 ETF 能更快调换持仓。
  - 这是 ETF 层面的动量，不是用户已否决的高波动个股动量。
- **主要风险**：
  - 动量崩溃，例如 2023 年 Mom 因子 −24.31%，2026 年 7 月高贝塔动量回吐全年涨幅。
  - SPMO 与 QQQ 的大型科技重仓可能高度重叠，分散效果有限（具体持仓重叠度本文未核实）。
  - 窄幅领涨的年份，例如 2023 年（SPMO +17.56%，QQQ +54.86%），会明显拖累组合。
- **反证**：
  - 2019-05-21 至 2026-10-23，SPMO 年化 19.83%，仍低于 QQQ 的 20.77%。
  - 从 2023 年初起算，SPMO 也落后。
  - 从约 28 只动量 ETF 中事后挑出 SPMO，有选择偏差。
  - 预期超额收益很小，主要价值可能是降低回撤。
- **淘汰条件**：在 2015-10（SPMO 上市）以来的滚动 3 年窗口中，组合跑赢 QQQ 的比例不到一半，或两档成本下的全期年化不高于 QQQ。

### 不建议进入候选的规则

- GEM、GTAA 和其他 1 倍择时；月末效应、Sell in May、选举周期；把波动率目标当作超额来源。理由：在 2023–2026 年都跑输 QQQ，本质是降低暴露。其中 1 倍均线过滤可以作为对照组，也可以作为风控层，但不应期待它带来超额收益。
- 神奇公式、F-Score、CAN SLIM、道指狗股。理由：落后幅度很大。5,000 USD 分散持有 10–30 只股票，佣金和价差拖累明显；免费基本面数据（EDGAR XBRL）需要大量清洗；CAN SLIM 和 F-Score 历史上有接近或超过 −50% 的年份。
- 行业动量轮动、52 周新高、多空 12-1 动量。理由：前者在 2023 年后全部落后，后两者无法用小账户执行，或缺少近年证据。
- TQQQ 或其他 3 倍版本。理由：与清盘线不相容。

## 四、来源

### QQQ 基准与公共数据

- totalrealreturns，QQQ、SPMO、SECT、PTF、AMOM：https://totalrealreturns.com/n/QQQ,SPMO,SECT,PTF,AMOM （已核实）
- totalrealreturns，GMOM、GAA、QQQ：https://totalrealreturns.com/n/GMOM,GAA,QQQ （已核实）
- totalrealreturns，QQQ、MTUM、PDP、QMOM：https://totalrealreturns.com/n/QQQ,MTUM,PDP,QMOM （已核实）
- totalrealreturns，QQQ、QLD、TQQQ、SPY：https://totalrealreturns.com/n/QQQ,QLD,TQQQ,SPY （已核实）
- totalrealreturns，QQQ、FV、FVC、XLK、SPY：https://totalrealreturns.com/n/QQQ,FV,FVC,XLK,SPY （已核实）
- totalrealreturns，QQQ、XLSR、SPY：https://totalrealreturns.com/n/QQQ,XLSR,SPY （已核实）
- totalrealreturns，QQQ、QQQA、XMMO、QQEW：https://totalrealreturns.com/n/QQQ,QQQA,XMMO,QQEW （已核实）
- chartrow QQQ 年度回报（第三方估算）：https://chartrow.com/quote/qqq/returns （已核实）
- chartrow QQQ 月度回报：https://chartrow.com/quote/qqq/monthly-returns （已核实）
- Invesco QQQ Trust 2026 年半年报 N-CSRS：https://www.sec.gov/Archives/edgar/data/0001067839/000119312526250483/8deb6f921189c0e.htm （已核实）
- ETF Replay：https://www.etfreplay.com/etf/qqq 、https://www.etfreplay.com/etf/ffty 、https://www.etfreplay.com/etf/sdog 、https://www.etfreplay.com/etf/dia （已核实）
- 纳指 100 在 2025 年的约 23% 回撤，纳斯达克研究：https://www.nasdaq.com/articles/nasdaq-100-tariff-resilience （二手来源，未核实，页面超时）

### 双动量、GTAA、LRS

- AlgoLab GEM 复现（2026-09-27）：https://algolab.co.kr/blog/dual-momentum-backtest-gem-python-2026 （已核实）
- Inwestomat GEM（2026-07-27）：https://inwestomat.eu/strategia-gem/ （已核实）
- Concretum GTAA 复现（2026-06-23）：https://concretumgroup.substack.com/p/global-tactical-asset-allocation （已核实）；https://concretumgroup.com/global-tactical-asset-allocation/
- CXO Advisory GTAA 延伸（2025-06-03，结果在付费墙后）：https://www.cxoadvisory.com/strategic-allocation/extension-of-a-quantitative-approach-to-tactical-asset-allocation
- Faber 2013 更新版（规则来源）：https://mebfaber.com/wp-content/uploads/2016/05/SSRN-id962461.pdf
- Cambria GMOM：https://www.cambriafunds.com/gmom
- CXO 对 Gayed & Bilello 的摘要（2016，规则与背景）：https://www.cxoadvisory.com/volatility-effects/leveraging-the-u-s-stock-market-based-on-sma-rules/
- Composer TQQQ 200 日均线：https://www.composer.trade/trading-strategies/tqqq-based-on-200d-ma-X3BQchFSANrGzrIKnDO6 （已核实）
- Financial Wisdom（2025-08-18，作者自报）：https://www.financialwisdomtv.com/post/qqq-trading-strategy-that-beats-the-market-proven-backtest-results
- wikifolio LRS 组合：https://www.wikifolio.com/en/int/w/wf00lrs200 （已核实）
- Allocate Smartly 关于交易频率的文章（2026-08-31）：https://allocatesmartly.com/does-trading-taa-strategies-more-often-improve-performance/ ；策略目录：https://allocatesmartly.com/list-of-strategies/ （策略业绩需要会员，未取得）

### 神奇公式、F-Score、CAN SLIM、狗股

- AAII 筛选业绩：https://www.aaii.com/stock-screens/performance （已核实）
- AAII 2025 年筛选回顾：https://www.aaii.com/journal/article/398718-2025-review-of-aaii-stock-screens-wangers-zebras-break-from-the-herd
- AAII Piotroski 文章（2024-05-29）：https://www.aaii.com/stockideas/article/212258-separating-winners-from-losers-low-price-to-book-stocks
- Gotham ETF 招募书（2026-01-28）：https://www.sec.gov/Archives/edgar/data/1742912/000199937126001640/gotham-485bpos_012626.htm
- Validea Greenblatt 模型：https://www.validea.com/joel-greenblatt ；Piotroski 模型：https://www.validea.com/joseph-piotroski
- Quantpedia 对 Schwartz & Hanauer《Formula Investing》的摘要（2025-01）：https://quantpedia.com/out-of-sample-test-of-formula-investing-strategies/
- Innovator FFTY 招募书（2025-02-28）：https://www.sec.gov/Archives/edgar/data/1415726/000121390025018623/ea0230462-01_485bpos.htm
- stockanalysis FFTY：https://stockanalysis.com/etf/ffty/ ；BOUT：https://stockanalysis.com/etf/bout/
- Dividend Power 狗股 2026：https://www.dividendpower.org/dogs-of-the-dow-2026/
- Motley Fool 2024 狗股：https://www.fool.com/investing/2024/01/01/meet-the-2024-dogs-of-the-dow/
- InvestmentNews（2026-07-29）：https://investmentnews.com/equities/dogs-of-the-dow/267611
- Seeking Alpha，2023 年狗股：https://seekingalpha.com/article/4660594-dow-dogs-gain-some-respect-in-q4-2023 （二手来源，未核实）
- Briefing.com，2024 年狗股：https://briefing.com/the-big-picture/archive/2024/12/20/a-2025-dogs-of-the-dow-preview （二手来源，未核实）
- dogsofthedow.com：https://www.dogsofthedow.com/ddogytd.htm

### 动量与行业轮动

- Ken French 动量因子：https://mba.tuck.dartmouth.edu/pages/faculty/ken.french/ftp/F-F_Momentum_Factor_CSV.zip
- Ken French 十行业组合：https://mba.tuck.dartmouth.edu/pages/faculty/ken.french/ftp/10_Industry_Portfolios_CSV.zip
- Ken French 三因子：https://mba.tuck.dartmouth.edu/pages/faculty/ken.french/ftp/F-F_Research_Data_Factors_CSV.zip
- Kayne Anderson 高贝塔动量图表（2026-08）：https://kayne.com/wp-content/uploads/High-Beta-Momentums-Leadership-Unraveled-Quickly-in-July.pdf
- Morningstar Factor Monitor（2026-01-15）：https://indexes.morningstar.com/insights/markets-review/blt102b1255cddffd67
- QMOM 情况说明书：https://funds.alphaarchitect.com/wp-content/uploads/compliance/etf/education/factsheet_qmom.pdf
- MTUM 摘要招股书（2024）：https://www.sec.gov/Archives/edgar/data/1100663/000119312524053810/d760848d497k.htm
- stockanalysis SPMO：https://stockanalysis.com/etf/spmo/
- First Trust FV：https://www.ftportfolios.com/ETF/FV
- SECT：https://www.mainmgtetfs.com/sect
- Quantpedia 52 周新高：https://quantpedia.com/strategies/52-weeks-high-effect-in-stocks
- Alpha Architect，动量崩溃与 52 周高点：https://alphaarchitect.com/risk-of-momentum-crashes/ （二手来源，未核实）
- Advisor Perspectives，2025-08 高盛动量篮子：https://www.advisorperspectives.com/articles/2025/08/21/goldman-traders-say-time-buy-dip-momentum-stocks （二手来源，未核实）

### 日历效应

- Han, Han & Tian《The disappearing turn-of-the-month effect》，FRL 2025：https://ideas.repec.org/a/eee/finlet/v71y2025ics1544612324014909.html （已核实）
- QuantifiedStrategies TOM（2025-09-22）：https://quantifiedstrategies.substack.com/p/turn-of-the-month-strategy （已核实）
- CXO TOM 稳健性（2024-01，付费墙）：https://www.cxoadvisory.com/calendar-effects/turn-of-the-month-effect-persistence-and-robustness
- CXO QQQ 季节性策略（2023-11，付费墙）：https://www.cxoadvisory.com/calendar-effects/seasonal-strategy-for-qqq/
- ETF Trends / Potomac TOM（2024-11）：https://www.etftrends.com/etf-strategist-channel/turn-month-effect/ （二手来源，未核实）
- First Trust 选举资料（2026-06）：https://www.ftportfolios.com/Commentary/Insights/2026/7/6/election-client-resource-kit---june-2026
- Sequoia 中期选举年（2026-06-04）：https://www.sequoia-financial.com/insights/the-midterm-year-roadmap-what-history-tells-us-about-2026/
- CMC Markets，2026 年纳指 100（2026-06-29）：https://www.cmcmarkets.com/en-gb/news-and-analysis/portfolio-rebalancing-tests-turn-of-the-month-effect-as-nasdaq-100-volatility-rises
- Ko & Yang 节前效应，CFR 2024：https://cfr.ivo-welch.org/published/papers/ko2021pre.pdf
- DQYDJ，2025 年标普回报：https://dqydj.com/2025-sp-500-return/

### 波动率管理

- Invesco QQQ 15 指数情况说明书（2026-08）：https://invesco.com/content/dam/invesco/indexing/en/documents/Invesco-QQQ15-Index-Fact-sheet.pdf （已核实）
- Cederburg, O'Doherty, Wang & Yan（JFE 2020）：https://www.lehigh.edu/~xuy219/research/COWY.pdf
- Barroso & Detzel（JFE 2021）：https://ideas.repec.org/a/eee/jfinec/v140y2021i3p744-767.html
- Bongaerts, Kang & van Dijk（FAJ 2020）：https://ideas.repec.org/a/taf/ufajxx/v76y2020i4p54-71.html
- Harvey 等《The Impact of Volatility Targeting》（2018）：https://www.man.com/insights/the-impact-of-volatility-targeting
- DeMiguel, Martín-Utrera & Uppal（JF 2024）：https://lbsresearch.london.edu/id/eprint/3716
- Man Group，V 形反弹（2025-06-05）：https://www.man.com/special/v-shaped-recoveries
- 路透，经 Kitco 转载（2026-10-01）：https://www.kitco.com/news/off-the-wire/2026-10-01/volatility-control-funds-near-record-equity-exposure-raising-selloff
- Globe and Mail，2025-04 去杠杆规模：https://theglobeandmail.com/investing/article-hedge-funds-etfs-dump-over-40-billion-in-stocks-after-trump-tariff （二手来源，未核实）

### 背景

- Jensen, Kelly & Pedersen《Is There a Replication Crisis in Finance?》（Journal of Finance，2023）：https://www.nber.org/papers/w28432 。该文认为多数因子可以复现，但它讨论的是相对市场的因子溢价，不涉及相对 QQQ 的超额收益。

### 研究局限

- 网页搜索额度在研究后期用完。以下来源没有取得数据：Allocate Smartly 的会员页面、optimalmomentum.com、Gayed 的官方更新，以及 Moreira & Muir 本人对批评的回应。
- 行业动量和 Mom 因子的分年度数字，是研究过程中用 French 数据文件自算的，没有独立复核。
- IBKR 佣金标准（Pro Fixed 每股 0.005 USD，每单最低 1 USD）是二手来源，未核实。
