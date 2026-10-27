# 跑赢 QQQ 的行业实证（2023 至 2026-10）：哪些产品跑赢了，靠的是什么

- 研究日期：2026-10-27（美东时间前一交易日 2026-10-26 收盘为最新可用行情）。
- 研究问题：近 1/3/5 年，美股 ETF、主动基金、量化机构和零售新工具中，哪些真正跑赢了
  QQQ 含息买入持有，以及超额收益来自更高贝塔/杠杆、行业押注还是选股。
- 主基准：QQQ 含息买入持有，不更换。本文所有金额和收益均以 USD 计。

## 时效与口径规则

1. 只采用 2023 年以后发布的数据和报告；每个业绩数字标注截至日期和来源。
2. 找不到官方数据时标注「二手来源，未核实」；搜索摘要转述、付费墙后只看到摘要的内容也按
   二手处理。
3. 主表（表 A）统一使用第三方站点 totalrealreturns 按复权收盘价（股息再投资、名义值、
   不扣税）计算的滚动收益，区间终点为 2026-10-26。QQQ、TQQQ 和 SPMO 已用 chartrow 交叉
   核对，两者一致（例如 QQQ 1/3/5 年为 +16.0%、+110.8%、+93.6%）。这些是基金市价含息收益，
   不是发行人标准化业绩。
4. 表 B 使用发行人官网的标准化 NAV 业绩，截至 2026-09-30。由于 QQQ 官网业绩表未能加载，
   QQQ 同期数据按 SEC N-CSRS 财年 NAV 回报和 chartrow 月度回报复利推算，并标为推算值。
5. 「1 年」为累计收益（即年化收益）；「3 年」「5 年」为年化复合收益。
   最大回撤优先取近 5 年窗口（2021-10-19 至 2026-10-26）。成立不足 5 年的产品取其可得
   窗口，并在单元格中注明。
6. 选样有幸存者偏差：表中产品是事后挑选、用来说明问题的，不代表同类产品的平均表现。
   发行人的标准化业绩和第三方市价业绩之间存在少量差异，属于正常现象。
7. 本文不计 W-8BEN 下 10% 的股息预扣。QQQ 股息率约 0.5%，预扣拖累约每年 0.05 个百分点；
   高分配产品的影响更大，见下文。

## 结论摘要

1. **近 1/3/5 年同时跑赢 QQQ 的产品，主要靠杠杆或行业集中，几乎没有靠分散选股的。** 截至
   2026-10-26，三个期限都领先 QQQ（+16.0%、28.2%/年、14.1%/年）的产品有：杠杆 ETF
   （QLD、SSO、UPRO、TQQQ）、半导体/科技行业 ETF（SMH、SOXX、XLK、VGT），以及集中超配
   大型科技股的成长型共同基金（FOCPX、FDGRX、FSELX）。SPMO 近 1 年只比 QQQ 高 0.5 个
   百分点，基本打平，但 3/5 年明显领先。
2. **杠杆最直接，但与本项目的 2,500 USD 清盘线冲突。** QLD 的 5 年年化为 17.0%，QQQ 为
   14.1%。不过 QLD 在 2021-11 至 2022-12 回撤 63.7%，TQQQ 回撤 81.7%。若一开始就满仓，
   账户会触发永久终止。TQQQ 的 5 年年化只有 14.4%，与 QQQ 几乎相同，体现了波动损耗；
   它的 5 年年化截至 2026-09-30 为 21.4%，截至 2026-10-26 为 14.4%，对终点日期非常敏感。
3. **这 5 年最大的超额来源是半导体，背后是 AI 资本开支周期。** SMH 5 年年化 32.8%，QQQ 为
   14.1%。按二手报道，四大云厂商 2026 年计划资本开支约 7,250–7,450 亿美元，2025 年约
   4,100 亿美元。代价是 SMH 中 NVDA 占 20.6%，2022 年回撤 45%。AI 主题和 AI 选股产品同期
   明显落后：BOTZ 5 年 −2.0%/年，AIEQ 5 年 3.4%/年。真正赚钱的是押对了 AI 产业链中的
   半导体，而不是买「AI 概念」。
4. **因子 ETF 的结果分化，指数编制方法决定成败。** SPMO（标普 500 动量）3/5 年年化分别为
   37.1% 和 18.3%，均跑赢 QQQ，5 年最大回撤只有 −22.8%（QQQ 为 −35.1%）。同样是动量
   ETF，MTUM 的 5 年年化只有 10.5%，XMMO 近 1 年仅 +0.4%；质量因子（QUAL）和等权
   （QQEW 5 年 6.5%/年）都落后。2026 年 7 月，动量因子出现三年多来最差的连续回撤。
5. **主动管理的整体胜率很低。** SPIVA 统计，大盘主动基金跑输标普 500 的比例在 2024 年为
   65%，2025 年为 79%，2026 年上半年为 67%。QQQ 近 3/5 年又跑赢了 SPY，因此要跑赢 QQQ
   更难。少数跑赢 QQQ 的主动基金（FOCPX、FDGRX）是集中超配大型科技股的共同基金，
   5 年年化只领先 0.9–1.3 个百分点，回撤更深，非美国居民能否买到也存疑。多数主动 ETF
   （ARKK、TCHP、JGRO、CGGR、FBCG）近 1 年落后于 QQQ。
6. **顶级量化机构没有在原始收益上跑赢 QQQ，它们追求的是低相关的超额收益。** 以下均为
   二手来源：AQR Apex 2025 年 +19.6%（QQQ 同年 +20.8%）；RIEF 2025 年截至 11 月只有
   +2.3%（QQQ 同期约 +21.7%）。Two Sigma 在 2026 年一季度 QQQ 下跌约 5.9% 时取得 +3% 至 +3.7%。行业在
   2025 年夏、2025-10、2026-01 和 2026-07 多次遭遇拥挤交易平仓。它们依赖的做空、
   杠杆和高频交易，都不适用于 5,000 USD 的纯多头 ETF/股票账户。
7. **零售新工具没有可靠的超额收益证据。** AIEQ 近 1/3/5 年全部落后 QQQ。跟踪国会议员
   交易的 NANC 3 年年化 25.8%，低于 QQQ 的 28.2%。eToro 披露 55% 的零售 CFD 账户
   亏钱，跟单业绩也没有经过审计的整体统计。期权收益 ETF 因卖出看涨期权而放弃上涨
   收益：QYLD 5 年年化 8.3%，JEPQ 3 年年化 22.0%，均远低于 QQQ。QYLD 近 1 年领先，
   只是因为终点落在 2026-10 的回调中。
8. **QQQ 本身就是一个会自我更新的「规模+动量」规则，这让跑赢它更难。** 每年 12 月的
   重构会纳入已经大涨的赢家，例如 2025-12 纳入了当年上涨超过 200% 的 STX 和 WDC。
   2026-05-01 起，新规允许大型新股在第 15 个交易日后快速入选，二手报道称 SpaceX 于
   2026-07-07 入选。前十大持仓约占 46.6%，回避巨头本身就会产生很大的跟踪误差。

## 业绩对比表

### 表 A：主表（截至 2026-10-26 收盘，第三方按复权价计算）

QQQ 同期：1 年 +15.95%，3 年 28.21%/年，5 年 14.12%/年；近 5 年窗口最大回撤 −35.12%
（2021-12-27 至 2022-11-03）。「—」表示产品成立不足该期限或数据不可得。

| 产品 | 类型 | 1 年 | 3 年年化 | 5 年年化 | QQQ 同期 1/3/5 | 超额来源 | 最大回撤（窗口） | 截至 | 链接 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| QLD | 杠杆指数 2x 纳指 | +22.46% | 48.49% | 16.96% | 15.95/28.21/14.12 | 杠杆（每日 2 倍） | −63.68%（2021-11→2022-12） | 2026-10-26 | [T1](https://totalrealreturns.com/n/QQQ,QLD,TQQQ,SMH,SPMO)、[D1](https://totalrealreturns.com/n/QQQ,SSO,UPRO,QLD,TQQQ,BITO) |
| TQQQ | 杠杆指数 3x 纳指 | +24.71% | 66.08% | 14.40% | 15.95/28.21/14.12 | 杠杆；5 年几乎被波动损耗抵消 | −81.66%（2021-11→2022-12） | 2026-10-26 | [T1](https://totalrealreturns.com/n/QQQ,QLD,TQQQ,SMH,SPMO)、[C2](https://chartrow.com/compare/qqq-vs-tqqq) |
| SSO | 杠杆指数 2x 标普 | +21.52% | 42.31% | 16.22% | 15.95/28.21/14.12 | 杠杆（标的贝塔低于纳指） | −46.73%（2022-01→2022-10） | 2026-10-26 | [T2](https://totalrealreturns.com/n/QQQ,SOXX,XLK,SSO)、[D1](https://totalrealreturns.com/n/QQQ,SSO,UPRO,QLD,TQQQ,BITO) |
| UPRO | 杠杆指数 3x 标普 | +28.19% | 60.64% | 17.65% | 15.95/28.21/14.12 | 杠杆 | −63.94%（2022-01→2022-10） | 2026-10-26 | [T3](https://totalrealreturns.com/n/QQQ,VGT,UPRO,SPHB)、[D1](https://totalrealreturns.com/n/QQQ,SSO,UPRO,QLD,TQQQ,BITO) |
| SMH | 行业：半导体 | +54.73% | 58.66% | 32.83% | 15.95/28.21/14.12 | 行业押注（AI 资本开支受益者；NVDA 20.6%） | −45.30%（2021-12→2022-10） | 2026-10-26 | [T1](https://totalrealreturns.com/n/QQQ,QLD,TQQQ,SMH,SPMO)、[D2](https://totalrealreturns.com/n/QQQ,SMH,SOXX,SPMO,XLK,BITO) |
| SOXX | 行业：半导体 | +66.77% | 50.58% | 26.91% | 15.95/28.21/14.12 | 行业押注 | −45.75%（2021-12→2022-10） | 2026-10-26 | [T2](https://totalrealreturns.com/n/QQQ,SOXX,XLK,SSO)、[D2](https://totalrealreturns.com/n/QQQ,SMH,SOXX,SPMO,XLK,BITO) |
| XLK | 行业：科技 | +27.58% | 33.34% | 19.39% | 15.95/28.21/14.12 | 行业押注（相当于去掉非科技股的 QQQ） | −33.56%（2021-12→2022-10） | 2026-10-26 | [T2](https://totalrealreturns.com/n/QQQ,SOXX,XLK,SSO)、[D2](https://totalrealreturns.com/n/QQQ,SMH,SOXX,SPMO,XLK,BITO) |
| VGT | 行业：科技 | +25.56% | 35.01% | 18.40% | 15.95/28.21/14.12 | 行业押注 | −35.07%（2021-12→2022-10） | 2026-10-26 | [T3](https://totalrealreturns.com/n/QQQ,VGT,UPRO,SPHB)、[D3](https://totalrealreturns.com/n/QQQ,MTUM,QUAL,SPY,RSP,VGT,BITO) |
| AIQ | 主题：AI 与科技 | +21.29% | 35.33% | 14.97% | 15.95/28.21/14.12 | 主题押注加更高贝塔；5 年只领先约 0.9 个百分点 | −44.66%（2021-11→2022-10） | 2026-10-26 | [T4](https://totalrealreturns.com/n/QQQ,ARKK,AIQ,BOTZ,AIEQ)、[D4](https://totalrealreturns.com/n/QQQ,FOCPX,FSELX,FBGRX,AIQ,ARKK,BITO) |
| BOTZ | 主题：机器人与 AI | −11.74% | 14.26% | −2.04% | 15.95/28.21/14.12 | 落后：主题判断错误 | −55.54%（2021-11→2022-10） | 2026-10-26 | [T4](https://totalrealreturns.com/n/QQQ,ARKK,AIQ,BOTZ,AIEQ) |
| SPMO | 因子：标普 500 动量 | +16.45% | 37.13% | 18.31% | 15.95/28.21/14.12 | 因子（动量）：2023–2025 集中持有 AI 赢家，2022 年轮出科技 | −22.75%（2022-01→2022-09） | 2026-10-26 | [T1](https://totalrealreturns.com/n/QQQ,QLD,TQQQ,SMH,SPMO)、[C3](https://chartrow.com/quote/spmo/trailing-returns) |
| MTUM | 因子：MSCI 美国动量 | +16.06% | 30.56% | 10.46% | 15.95/28.21/14.12 | 3 年领先、5 年落后；编制方法不同 | −32.28%（2021-11→2022-06） | 2026-10-26 | [T5](https://totalrealreturns.com/n/QQQ,MTUM,QUAL,SPY,RSP,XMMO)、[D3](https://totalrealreturns.com/n/QQQ,MTUM,QUAL,SPY,RSP,VGT,BITO) |
| XMMO | 因子：中盘动量 | +0.40% | 22.95% | 9.43% | 15.95/28.21/14.12 | 落后 | 窗口内未取得 | 2026-10-26 | [T5](https://totalrealreturns.com/n/QQQ,MTUM,QUAL,SPY,RSP,XMMO) |
| QUAL | 因子：质量 | +14.60% | 21.60% | 11.01% | 15.95/28.21/14.12 | 落后（低贝塔） | −28.23%（2021-12→2022-10） | 2026-10-26 | [T5](https://totalrealreturns.com/n/QQQ,MTUM,QUAL,SPY,RSP,XMMO) |
| SPHB | 因子：标普高贝塔 | +21.36% | 30.32% | 12.83% | 15.95/28.21/14.12 | 高贝塔；5 年落后 | 窗口内未取得 | 2026-10-26 | [T3](https://totalrealreturns.com/n/QQQ,VGT,UPRO,SPHB) |
| QQEW | 纳指 100 等权 | +8.16% | 17.15% | 6.51% | 15.95/28.21/14.12 | 落后：低配巨头 | −32.13%（2021-11→2022-10） | 2026-10-26 | [T6](https://totalrealreturns.com/n/QQQ,MGK,SCHG,XLG,QQEW) |
| MGK | 超大盘成长 | +9.11% | 27.48% | 12.92% | 15.95/28.21/14.12 | 落后：集中度更高未必更好 | −36.01%（2021-12→2022-11） | 2026-10-26 | [T6](https://totalrealreturns.com/n/QQQ,MGK,SCHG,XLG,QQEW) |
| SPY | 参照：标普 500 | +14.23% | 24.37% | 12.41% | 15.95/28.21/14.12 | 参照 | −24.50%（2022-01→2022-10） | 2026-10-26 | [T5](https://totalrealreturns.com/n/QQQ,MTUM,QUAL,SPY,RSP,XMMO) |
| RSP | 参照：标普等权 | +15.43% | 19.04% | 8.29% | 15.95/28.21/14.12 | 落后：低配巨头 | −21.39%（2022-01→2022-09） | 2026-10-26 | [T5](https://totalrealreturns.com/n/QQQ,MTUM,QUAL,SPY,RSP,XMMO) |
| FOCPX | 主动共同基金（Fidelity OTC） | +29.86% | 34.82% | 15.40% | 15.95/28.21/14.12 | 选股为主，但集中超配大型科技、贝塔更高 | −37.05%（2021-11→2022-10） | 2026-10-26 | [T7](https://totalrealreturns.com/n/QQQ,FOCPX,FSELX,TRBCX,CGGR)、[D4](https://totalrealreturns.com/n/QQQ,FOCPX,FSELX,FBGRX,AIQ,ARKK,BITO) |
| FDGRX | 主动共同基金（Fidelity Growth Co.） | +24.47% | 35.57% | 15.07% | 15.95/28.21/14.12 | 选股加成长风格超配 | −40.25%（2021-11→2022-10） | 2026-10-26 | [T8](https://totalrealreturns.com/n/QQQ,BPTRX,FDGRX,TCHP,BITO) |
| FSELX | 主动行业基金（半导体） | +46.37% | 54.48% | 32.81% | 15.95/28.21/14.12 | 主要是行业押注，与 SMH 接近 | −46.37%（2021-12→2022-10） | 2026-10-26 | [T7](https://totalrealreturns.com/n/QQQ,FOCPX,FSELX,TRBCX,CGGR) |
| FBGRX | 主动共同基金（Blue Chip Growth） | +16.07% | 31.85% | 12.95% | 15.95/28.21/14.12 | 1/3 年小幅领先，5 年落后 | −43.08%（2021-11→2022-12） | 2026-10-26 | [T9](https://totalrealreturns.com/n/QQQ,FBGRX,FCNTX,FBCG,JGRO) |
| FCNTX | 主动共同基金（Contrafund） | +13.15% | 28.37% | 13.85% | 15.95/28.21/14.12 | 基本打平或落后 | 窗口内未取得 | 2026-10-26 | [T9](https://totalrealreturns.com/n/QQQ,FBGRX,FCNTX,FBCG,JGRO) |
| BPTRX | 主动共同基金（Baron Partners） | +37.69% | 31.65% | 8.76% | 15.95/28.21/14.12 | 重仓 Tesla 的单股集中，叠加基金杠杆；5 年落后 | −49.87%（2021-11→2022-12） | 2026-10-26 | [T8](https://totalrealreturns.com/n/QQQ,BPTRX,FDGRX,TCHP,BITO) |
| FBCG | 主动 ETF | +10.57% | 29.48% | 11.76% | 15.95/28.21/14.12 | 3 年小幅领先，1/5 年落后 | 窗口内未取得 | 2026-10-26 | [T9](https://totalrealreturns.com/n/QQQ,FBGRX,FCNTX,FBCG,JGRO) |
| ARKK | 主动 ETF（颠覆式创新） | −8.38% | 33.03% | −7.25% | 15.95/28.21/14.12 | 高贝塔：3 年反弹领先，5 年大幅落后 | −76.12%（2021-11→2022-12） | 2026-10-26 | [T4](https://totalrealreturns.com/n/QQQ,ARKK,AIQ,BOTZ,AIEQ)、[D4](https://totalrealreturns.com/n/QQQ,FOCPX,FSELX,FBGRX,AIQ,ARKK,BITO) |
| TCHP | 主动 ETF（T. Rowe 蓝筹成长） | −0.72% | 23.37% | 8.15% | 15.95/28.21/14.12 | 落后 | −42.34%（2021-11→2022-11） | 2026-10-26 | [T8](https://totalrealreturns.com/n/QQQ,BPTRX,FDGRX,TCHP,BITO) |
| JGRO | 主动 ETF（摩根大通成长） | −1.69% | 22.10% | — | 15.95/28.21/— | 落后 | −22.70%（可得窗口，2025-01→2025-04） | 2026-10-26 | [T9](https://totalrealreturns.com/n/QQQ,FBGRX,FCNTX,FBCG,JGRO) |
| CGGR | 主动 ETF（Capital Group 成长） | +2.87% | 25.63% | — | 15.95/28.21/— | 落后 | −28.90%（2022-03→2022-10） | 2026-10-26 | [T7](https://totalrealreturns.com/n/QQQ,FOCPX,FSELX,TRBCX,CGGR) |
| NANC | 跟踪国会议员交易的 ETF | +12.12% | 25.82% | — | 15.95/28.21/— | 落后（实际高度超配大型科技） | −20.94%（2025-02→2025-04；QQQ 同窗 −22.77%） | 2026-10-26 | [T10](https://totalrealreturns.com/n/QQQ,NANC) |
| AIEQ | AI 选股 ETF | +7.29% | 20.25% | 3.39% | 15.95/28.21/14.12 | 落后：AI 选股未产生超额 | −38.97%（2021-11→2023-05） | 2026-10-26 | [T4](https://totalrealreturns.com/n/QQQ,ARKK,AIQ,BOTZ,AIEQ)、[D5](https://totalrealreturns.com/n/QQQ,QYLD,XYLD,AIEQ,QQEW,BITO) |
| QYLD | 期权收益：纳指备兑 | +18.53% | 17.28% | 8.29% | 15.95/28.21/14.12 | 1 年领先只因终点落在回调中；3/5 年大幅落后 | −24.60%（2021-12→2022-10） | 2026-10-26 | [T11](https://totalrealreturns.com/n/QQQ,JEPQ,QYLD,QQQI,XYLD,JEPI)、[D5](https://totalrealreturns.com/n/QQQ,QYLD,XYLD,AIEQ,QQEW,BITO) |
| JEPQ | 期权收益：纳指 ELN 备兑 | +13.28% | 21.96% | — | 15.95/28.21/— | 落后 | −20.07%（2025-02→2025-04；QQQ 同窗 −22.77%） | 2026-10-26 | [T11](https://totalrealreturns.com/n/QQQ,JEPQ,QYLD,QQQI,XYLD,JEPI) |
| QQQI | 期权收益：纳指备兑 | +11.62% | — | — | 15.95/—/— | 落后 | −20.00%（2025-02→2025-04） | 2026-10-26 | [T11](https://totalrealreturns.com/n/QQQ,JEPQ,QYLD,QQQI,XYLD,JEPI) |
| AMOMX | 量化共同基金（AQR 大盘动量） | +15.89% | 20.47% | 12.41% | 20.8/32.9/—（截至 2025-12-31，按月度回报推算） | 落后 | 未取得 | 2025-12-31 | [Z1](https://zacks.com/funds/mutual-fund/quote/AMOMX/performance)（二手来源，未核实） |

注：T. Rowe Price Blue Chip Growth（TRBCX）在同一数据源中的 1 年收益显示为 0.00%，疑似分配处理
异常，已剔除。共同基金在第三方站点上的复权方式（资本利得分配）可能与官方 NAV 口径不同。

### 表 B：发行人标准化 NAV 业绩交叉核对（截至 2026-09-30）

| 产品 | 1 年 | 3 年年化 | 5 年年化 | QQQ 同期 1/3/5 | 净费率 | 来源 |
| --- | --- | --- | --- | --- | --- | --- |
| TQQQ | +51.85% | 65.37% | 21.42% | ≈23.9/≈28.1/≈16.3（推算） | 0.78%（页面所列豁免期至 2026-09-30，毛费率 0.94%） | [ProShares](https://www.proshares.com/our-etfs/leveraged-and-inverse/tqqq) |
| QLD | +39.57% | 48.07% | 21.56% | 同上 | 0.89% | [ProShares](https://www.proshares.com/our-etfs/leveraged-and-inverse/qld) |
| SSO | +24.50% | 38.59% | 18.96% | 同上 | 0.84% | [ProShares](https://www.proshares.com/our-etfs/leveraged-and-inverse/sso) |
| UPRO | +32.68% | 54.27% | 21.86% | 同上 | 0.88% | [ProShares](https://www.proshares.com/our-etfs/leveraged-and-inverse/upro) |
| QYLD | +22.94% | 16.79% | 9.33% | 同上 | 0.60% | [Global X](https://www.globalxetfs.com/funds/qyld/) |
| QQQ（推算） | ≈+23.9% | ≈28.1% | ≈16.3% | — | 0.18%（官网） | [SEC N-CSRS](https://www.sec.gov/Archives/edgar/data/0001067839/000119312526250483/8deb6f921189c0e.htm) + [chartrow 月度](https://chartrow.com/quote/qqq/monthly-returns) |

QQQ 推算方法：SEC N-CSRS 披露的财年 NAV 总回报为 FY2022 −24.86%、FY2023 +34.98%、
FY2024 +37.21%、FY2025 +23.63%，2025-10 至 2026-03 半年为 −3.63%。FY2026（2025-10 至
2026-09）用 chartrow 月度含息回报复利，约为 +23.9%，再与上述财年连乘。chartrow 显示 QQQM
截至 2026-09-30 的 1 年和 5 年收益分别为 +23.9% 和 16.4%/年，两者吻合。

对比表 A 与表 B：终点只相差不到一个月，TQQQ 的 5 年年化就从 21.4% 降到 14.4%，1 年收益
从 51.9% 降到 24.7%。原因是 2026-10 至 26 日 QQQ 下跌约 3.7%，而 TQQQ 当月下跌约 12.3%
（chartrow）。可见，杠杆产品的「跑赢」结论高度依赖区间终点。

### 表 C：量化机构与对冲基金的公开业绩（全部为二手来源，未核实）

| 机构/产品 | 类型 | 期间 | 收益 | QQQ 同期 | 来源 |
| --- | --- | --- | --- | --- | --- |
| Renaissance RIEF | 长偏向股票量化（目标是 3 年滚动跑赢标普 500 4–6 个百分点，杠杆约 2.5 倍） | 2024 年 | +22.7% | ≈+25.7% | Institutional Investor |
| Renaissance RIEF | 同上 | 2025-10 单月 / 2025 年截至 11 月 | −14.39% / +2.34% | 2025 年截至 11 月 ≈+21.7% | Institutional Investor |
| Renaissance RIEF / RIDA | 同上 / 多元 alpha | 2026 年截至 7 月 | +4.5% / +14% | ≈+12.4% | AlphaMaven 转述 Bloomberg |
| AQR Apex | 多策略 | 2025 年 | +19.6% | ≈+20.8% | Bloomberg 标题 |
| AQR Delphi | 股票多空 | 2024 年 / 2025 年截至 11 月 | +24.4% / +16.4% | ≈+25.7% / ≈+21.7% | Hedgeweek、HedgeCo |
| AQR Adaptive Equities | 市场中性股票 | 2025 年 | +24.4%（与 Delphi 2024 年数字相同，存疑） | ≈+20.8% | 搜索摘要转述 Bloomberg |
| Two Sigma Absolute Return Enhanced / Spectrum | 多策略 / 股票量化 | 2023 年 | +12% / +8.6% | ≈+54.7% | Hedgeweek 转述 Business Insider |
| Two Sigma Spectrum / ARE | 同上 | 2026 年一季度 | +3% / +3.7% | ≈−5.9% | Bloomberg 标题与摘要 |
| Two Sigma ARE | 同上 | 2026 年截至 7 月 | +9% | ≈+12.4% | AlphaMaven 转述 |
| 量化对冲基金平均 | 行业 | 2025 年 | +7.7% | ≈+20.8% | PivotalPath，经搜索摘要转述 |
| 量化股票多空基金（Goldman 主经纪商数据） | 行业 | 2025-06-01 至 07-25 | −4.2%（同期美股约 +8%） | — | MSCI 博客（2025-10-30） |
| Robeco BP US Large Cap Equities | 美股大盘价值 | 2025 年 | +16.1%（相对其基准 +0.2%） | ≈+20.8% | Robeco 2025 年报，经搜索摘要转述 |

表中 QQQ 同期值按 chartrow 月度含息回报复利推算：2023 年 +54.7%，2024 年 +25.7%，2025 年
+20.8%，2026 年截至 9 月 +21.0%。

### 分类解读：靠贝塔/杠杆，还是靠选股

**杠杆指数 ETF。** QLD、SSO、UPRO、TQQQ 在三个期限上都领先 QQQ，但这完全来自杠杆，
不是选股。这类产品每日再平衡，在震荡市里会产生波动损耗：TQQQ 用 3 倍杠杆，5 年年化
只比 QQQ 高 0.3 个百分点。ProShares 的 2x 纳指产品净费率 0.89%，另有隐含融资成本。
近 5 年窗口中，除 SSO 外，各产品回撤都超过 63%，突破了本项目「本金亏损一半即永久终止」
的底线。SSO 跟踪标普 500，标的回撤较浅，回撤为 46.7%，离清盘线只差 3.3 个百分点。

**行业与主题 ETF。** 半导体（SMH、SOXX、FSELX）是这 5 年唯一同时具备「超额幅度大」和
「持续三个期限」的类别，驱动因素是 AI 训练和推理带来的算力、存储需求（见下文的资本开支
数据）。超额的本质是行业集中：SMH 共 26 只成分股，前十大占 69%，其中 NVDA 占 20.6%
（stockanalysis，截至 2026-10-24）。宽泛的 AI 主题 ETF 中，AIQ 勉强跑赢，BOTZ 大幅落后，
说明靠「AI 概念」选主题并不可靠。

**因子 ETF。** SPMO 是近 3/5 年表现最好的非杠杆、非行业 ETF。按 stockanalysis 的描述，
它跟踪「波动调整后动量最强的 100 只标普 500 成分股」，费率 0.13%。按市值乘动量分加权、
每半年调仓的细节来自对指数编制的一般了解，属于二手来源，未核实。它在 2022 年轮出科技
股，回撤较浅；2023–2025 年集中持有 AI 赢家，因此大幅领先。当前持仓已明显轮换：截至
2026-10-23，前十大为 AAPL 10.3%、MU 8.6%、AMD 5.2%、JNJ 4.9%、GOOGL 4.9%、INTC
4.4%、XOM 3.7% 等，与 QQQ 的相关性随之变化。同为动量 ETF，MTUM 和 XMMO 都落后，说明
结果高度依赖编制细节和样本区间。等权产品（QQEW、RSP）在集中化行情中系统性落后。

**主动基金和主动 ETF。** 少数跑赢 QQQ 的主动基金（FOCPX、FDGRX）是 Fidelity 旗下的
成长型共同基金，持仓集中在大型科技和半导体，5 年年化只领先 QQQ 0.9–1.3 个百分点，
回撤却更深（−37% 至 −40%）。它们无法与「更高的成长和科技贝塔」清楚区分；共同基金
也不在本项目的「美股和美股 ETF」范围内。非美国居民能否通过 IBKR 购买美国共同基金未核实。
主动 ETF 中，没有一只在三个期限上都领先。SPIVA 统计，大盘主动基金跑输标普 500 的
比例在 2025 年为 79%，是 25 年来第四差；2024 年为 65%，2026 年上半年为 67%
（S&P DJI；PDF 抓取被拒，数字来自 S&P 页面摘要和 InvestmentNews 转述）。

**量化机构的表现与公开观点。**

- **业绩：** 头部量化机构的主力产品是市场中性或多空策略，追求与市场低相关的超额收益。
  在 2023–2025 年的单边上涨中，它们的原始收益普遍低于 QQQ（见表 C），但在下跌季度
  （如 2026 年一季度）表现更好。
- **拥挤与回撤：** 量化股票策略多次集中回撤，且都与拥挤交易平仓有关：
  - 2025 年 6–7 月的「垃圾股反弹」：MSCI 认为驱动因素是动量走弱、空头集中的股票上涨、
    盈利能力因子落后。
  - 2025-10 的去杠杆，据路透转述 Goldman。
  - 2026 年 1 月上半月：Goldman 数据为 −1%，UBS 估计美国量化基金约 −2.8%（Hedgeweek，
    2026-01-22）。
  - 2026 年 7 月：动量策略连续两周各跌超过 3%，是三年多来最差；资金从高动量的 AI
    受益股（包括 Micron 等半导体）轮出（Hedgeweek 转述 Bloomberg，2026-07-07）。
- **AQR：** Asness 在 2024 年提出「市场变得更不有效」，认为价值价差处于历史极端，指数化
  和社交媒体可能是原因。BlackRock 2026-04 在 JPM 上发表的研究持反对意见，认为价格仍能
  有效预测基本面（Alpha Architect，2026-06-26）。
- **Robeco：** 2025-05 的文章明确表示，少数美国大型科技股的主导地位让防御型量化策略难以
  跑赢指数。按 Robeco 2025 年报，其组合中跑赢基准的比例从 2024 年的 43% 升至 2025 年的
  69%（搜索摘要转述）。
- **Man Group：** 2026 年一季度交易公告披露，一名客户从系统化长仓股票策略赎回 61 亿美元，
  截至 2026-03-31 资管规模为 2,287 亿美元。没有找到 Man 关于「跑赢纳指」的明确公开观点。
- **结论：** 机构量化的优势来自做空、杠杆、低相关和容量管理，不是一个可以平移到
  5,000 USD 纯多头账户、用来战胜 QQQ 的选股方法。

**零售新工具。**

- **AI 选股：** 最早上市的 AI 选股 ETF AIEQ，5 年年化只有 3.4%，三个期限都落后 QQQ。
  其他 AI 选股应用和信号服务没有找到经过审计、覆盖完整样本的长期业绩，宣传中的胜率不能
  作为证据。
- **跟单与「名人交易」：** eToro CopyTrader 页面（2026-10-27 抓取）展示的明星交易员是事后
  挑选的，页面同时披露 55% 的零售 CFD 账户亏钱，并提示过往业绩不代表未来。跟踪国会
  议员交易的 NANC，3 年年化落后 QQQ 2.4 个百分点。
- **期权收益 ETF 为什么通常跑输 QQQ：**
  1. **上行被封顶、下行几乎全承担。** 卖出看涨期权限制了上涨空间，Global X 页面也写明
     「covered call writing can limit the upside」。截至 2026-10-26，QYLD 卖出的看涨期权
     行权价只比当前指数高 1.37%，QQQ 一个月涨 10% 时，它只能拿到权利金加不到 1.4% 的涨幅。
  2. **长期上涨的市场里权利金不够补偿。** 纳指在 2023 年和 2024 年分别上涨约 55% 和
     26%，卖出的上涨远多于收到的权利金。
  3. **路径依赖。** 大跌后的反弹同样被封顶，净值恢复更慢。
  4. **高分配不等于高收益。** QYLD 的分配率约 11.8%，其中估计包含资本返还；在 W-8BEN
     身份下，分配越多，预扣影响越大。具体按分配性质预扣，未核实。
  5. **短期领先只是截面效应。** QYLD 近 1 年领先是因为终点落在 2026-10 的回调中；截至
     2026-09-30 的官方 1 年收益为 22.9%，低于 QQQ 的约 23.9%。

### 2025–2026 市场结构变化与「跑赢 QQQ」的难度

- **指数集中度。** 截至 2026-10-23，QQQ 前十大持仓合计 46.58%：NVDA 8.09%、AAPL 8.07%、
  MSFT 6.19%、MU 4.35%、AMZN 4.25%、AMD 3.70%、TSLA 3.11%、META 3.04%，Alphabet 两类
  股份合计 5.78%（stockanalysis，二手来源）。chartrow 依据 N-PORT 持仓计算，前十大占比在
  2023-06 达到峰值 60.8%，2026-06 为 47.8%。集中度虽从峰值回落，但低配巨头依然意味着很大的
  跟踪误差。等权产品的落后（QQEW 5 年 6.5%/年，QQQ 14.1%/年）正是「巨头溢价」的直接体现。
- **2023 年特别再平衡。** Nasdaq 于 2023-07-07 宣布，2023-07-24 开盘前生效，不增删成分股，
  只降低最大公司的权重，并把多出的权重分配给其他成分股（Nasdaq 原文）。按二手报道：触发
  条件是单个权重超过 4.5% 的公司合计超过 48%，再平衡后降到 40%；前五大合计从约 46.7% 降到
  约 38.5%（二手来源，未核实）。影响：QQQ 对最大几家公司的集中有制度上限，所以「超配
  巨头」的产品（如 MGK）在部分期间会领先 QQQ；但近 1 年 MGK 落后，说明这不是稳定的超额来源。
- **年度重构即内置动量。** 2025-12-22 生效的重构纳入 ALNY、FER、INSM、MPWR、STX、WDC，
  剔除 BIIB、CDW、GFS、LULU、ON、TTD（Nasdaq 新闻稿）。Nasdaq 文章称 STX 和 WDC 当年
  涨幅超过 200%，TTD 和 LULU 分别下跌 68% 和 46%（搜索摘要转述，未逐字核对）。
  QQQ 自动剔除失败者、纳入赢家，在 QQQ 成分中做「去弱留强」的选股，与指数本身的规则
  高度重叠。
- **2026 年方法论更新（Nasdaq 原文，2026-03-30 公布结论，2026-05-01 生效）：**
  1. 计算入选资格用的市值同时计入上市和未上市股份，权重仍按上市股份计算。
  2. 新增「快速纳入」：新上市的大型公司通常在第 15 个交易日后纳入。二手报道称资格为市值
     排名前 40。
  3. 低流通股按 3 倍流通市值调整权重，并取消 10% 最低流通比例。
  4. 「10 基点规则」改为每季度剔除排名在第 125 名以外的成分股。
  5. 停止在季度内调整总股本（TSO），改为在季度调仓时统一处理。
  首次影响权重的是 2026-06-22 的季度调仓。二手报道称 SpaceX 于 2026-07-07 经快速纳入
  入选，跟踪 QQQ 的资金约买入 43 亿美元（JPMorgan 估算），入选首日股价下跌近 7%
  （Contrary Research，二手来源，未核实）。影响：大型新股会更快进入 QQQ，「在 IPO 后、
  入选前买入」的指数套利窗口变短；被动资金在纳入日集中买入，可能给 QQQ 带来少量
  执行冲击。
- **AI 资本开支周期。** 按 AI Weekly 转述的 FT 统计（2026-07-31）：Amazon、Microsoft、
  Alphabet、Meta 2026 年计划资本开支合计约 7,250 亿美元（FT 标题为 7,450 亿美元），比
  2025 年约 4,100 亿美元高 77%；Evercore 和美银预计 2027 年超过 1 万亿美元（二手来源，未核实）。
  资本开支在供应链上转化为收入，半导体、存储和网络设备直接受益：MU 和 AMD 已进入 QQQ
  前十大。花钱的平台公司则要承受折旧和自由现金流压力。这就是 SMH 类产品大幅领先 QQQ
  的根本原因。资本开支的增速一旦见顶，同一机制会反向放大回撤。
- **对难度的影响。**
  1. QQQ 本身已经超配 AI 赢家，并持续纳入新赢家，「在 QQQ 里挑股票」的空间被压缩。
  2. 集中度高时，偏离巨头就要承担很大的跟踪误差；SPIVA 显示大多数主动管理人在这种环境下
     落后。
  3. 量化因子越来越拥挤，2025–2026 年多次集中平仓，信号衰减和回撤风险上升。
  4. 想跑赢 QQQ，基本只剩两条路：比 QQQ 更集中于正确的子行业，或者承担更高的贝塔/杠杆。

## 对本项目的候选路线

前提：只交易美股和美股 ETF，不用期权、期货和外汇；只用免费数据（研究阶段可用 Alpaca SIP
历史数据）；本金 5,000 USD；净值不高于 2,500 USD 时永久清仓终止。现行本金阶梯只区分
「个股」和「QQQ」，引入下列 ETF 之前，必须预先登记它们在 warning 状态下按哪一类处理。
建议杠杆 ETF 和行业 ETF 按风险资产处理：warning 时不新增，并逐步转回 QQQ。下面的
组合回撤都是**粗略线性估算，不是回测结果**，只用于判断与清盘线的距离。三条路线的超额
来源高度重叠（AI、半导体、大型成长股），不能互相当作独立证据。

### 路线 A：QQQ 核心 + 半导体 ETF 卫星（行业押注）

- **执行：** QQQ 70%–80%，SMH（或 SOXX）20%–30%。按容忍带再平衡，例如卫星权重偏离目标
  10 个百分点时调仓，或每年调一次；每年交易不超过 4 笔，按每笔 1 USD 计，成本低于每年
  0.1%。全部为 ETF，不触发「低于本金不得新开个股」的限制，但要按上文补登 warning 规则。
- **依据：** SMH 截至 2026-10-26 的 1/3/5 年收益为 +54.7%、58.7%/年、32.8%/年，QQQ 为
  +16.0%、28.2%/年、14.1%/年。两者相关性高，卫星仓位主要放大 QQQ 已有的 AI 暴露，
  而不是引入陌生风险。
- **回撤估算：** 30% SMH 时，2022 年的组合回撤约为 0.7×35.1% + 0.3×45.3% ≈ 38%，
  距清盘线约 12 个百分点。
- **主要风险：** 半导体是强周期行业，SOXX 全历史最大回撤 −66.9%（2007-07 至 2008-11）。
  NVDA 在 SMH 中占 20.6%，单一公司风险集中。资本开支增速见顶或出口管制收紧时，回撤会
  快于 QQQ。当前是在 SMH 5 年上涨 313% 之后入场，有追高的风险。
- **反证：** AI 主题 ETF（BOTZ、AIEQ）同期失败，「押对行业」很可能事后才看得清楚。2026-07
  的动量回撤中，半导体首当其冲。如果用 2000–2002 年或 2008 年那样的周期来测试，这条
  路线可能大幅落后。
- **验证建议：** 预先登记 20% 和 30% 两档权重，在项目账本中用 Alpaca 行情尽量覆盖 2016
  年以来的区间（含 2018 年四季度、2020 年、2022 年、2025 年 4 月），使用两档成本和
  10% 股息预扣，以同成本的 QQQ 账户为基准。

### 路线 B：有上限的纳指 2 倍杠杆 + 趋势闸门（贝塔/杠杆）

- **执行：** 默认满仓 QQQ。只有当 QQQ 收盘价高于其 200 日均线时，才把最多 30% 的仓位换成
  QLD，组合等效约 1.3 倍。收盘跌破均线后，下一会话开盘卖出 QLD 换回 QQQ。另设一道
  账户级去杠杆闸门：净值低于本金或较峰值回撤超过 25% 时，强制回到纯 QQQ。均线参数
  只登记一次，不做参数搜索。
- **依据：** QLD 截至 2026-10-26 的 1/3/5 年收益为 +22.5%、48.5%/年、17.0%/年；ProShares
  截至 2026-09-30 的官方数据为 +39.6%、48.1%/年、21.6%/年。只要市场上涨，杠杆就是跑赢
  QQQ 最可靠的来源。
- **回撤估算：** 不加闸门、30% QLD 时，2022 年约为 0.7×35.1% + 0.3×63.7% ≈ 44%；
  50% QLD 时约 49%，已贴近清盘线。所以仓位上限和闸门都是必需的，不能省。
- **主要风险：** 均线信号滞后，2025-04 QQQ 在 7 周内回撤 22.8%，闸门来不及反应；横盘
  行情反复穿越均线，会造成来回止损和交易成本；隔夜跳空；QLD 有 0.89% 的费率和隐含
  融资成本；IBKR 对杠杆 ETF 可能要求适当性确认或限制非美国居民交易，未核实，需在
  账户中实际确认。
- **反证：** TQQQ 用 3 倍杠杆，5 年年化只比 QQQ 高 0.3 个百分点；终点只差一个月，结论就
  明显变化（表 B 与表 A）。「靠杠杆跑赢」在风险调整后不一定更优，而本项目的验收标准是
  原始收益跑赢 QQQ，这一点必须向用户明确：超额来自承担更多风险，不是信息优势。

### 路线 C：用 SPMO 部分替代 QQQ（因子 ETF）

- **执行：** QQQ 和 SPMO 各占 50%，在指数半年调仓后的下一个月再平衡一次，每年约 2–4 笔
  交易。也可以把 SPMO 作为路线 A 中 SMH 卫星的替代，二选一，不叠加。
- **依据：** SPMO 截至 2026-10-26 的 3/5 年年化为 37.1% 和 18.3%，QQQ 为 28.2% 和
  14.1%；近 5 年窗口最大回撤 −22.8%，QQQ 为 −35.1%。费率 0.13%，规则透明，
  100 只成分股分散持有。
- **主要风险：** 动量崩溃（2026-07 出现三年多来最差的动量回撤，SPMO 近 1 年最大回撤约
  −15.6%）；半年调仓有滞后，市场急转时会追高杀低；持仓已从 AI 赢家转向 AAPL、MU、JNJ、
  XOM 等，与 QQQ 的相关性下降，跟踪误差变大。用户已否决「高波动个股动量」，SPMO
  与之同属动量家族，但它是指数化、分散、低换手的 ETF，需要用户明确确认这一区别是否可以
  接受。
- **反证：** MTUM 的 5 年年化只有 10.5%，XMMO 近 1 年 +0.4%，同类动量 ETF 落后。
  SPMO 近 1 年只比 QQQ 高 0.5 个百分点。2023–2025 年的领先与 AI 赢家集中同源，与路线 A
  高度重叠。

### 不建议纳入候选的方向

- **期权收益 ETF（QYLD、JEPQ、QQQI）：** 结构上放弃上涨收益，3/5 年大幅落后 QQQ。
- **AI 选股 ETF 和应用、跟单平台、国会交易跟踪：** 没有经过审计的超额收益证据。
- **宽泛主题 ETF 和高贝塔主动 ETF（ARKK 等）：** 5 年业绩差，回撤超过 70%，会直接触发
  清盘线。
- **复制量化对冲基金：** 需要做空、杠杆和高换手；业绩来源与「跑赢 QQQ」的目标不一致。
- **主动共同基金：** 不在本项目的标的范围内；可得性存疑，超额幅度小。
- **满仓 TQQQ、QLD、UPRO：** 2022 年的回撤会触发永久终止。

## 来源列表

所有链接于 2026-10-27 访问。标注「二手」的来源，其数字未经原始文件核实。

### 业绩数据（第三方计算，截至 2026-10-26）

- [T1] totalrealreturns，QQQ/QLD/TQQQ/SMH/SPMO：<https://totalrealreturns.com/n/QQQ,QLD,TQQQ,SMH,SPMO>
- [T2] totalrealreturns，QQQ/SOXX/XLK/SSO：<https://totalrealreturns.com/n/QQQ,SOXX,XLK,SSO>
- [T3] totalrealreturns，QQQ/VGT/UPRO/SPHB：<https://totalrealreturns.com/n/QQQ,VGT,UPRO,SPHB>
- [T4] totalrealreturns，QQQ/ARKK/AIQ/BOTZ/AIEQ：<https://totalrealreturns.com/n/QQQ,ARKK,AIQ,BOTZ,AIEQ>
- [T5] totalrealreturns，QQQ/MTUM/QUAL/SPY/RSP/XMMO：<https://totalrealreturns.com/n/QQQ,MTUM,QUAL,SPY,RSP,XMMO>
- [T6] totalrealreturns，QQQ/MGK/SCHG/XLG/QQEW：<https://totalrealreturns.com/n/QQQ,MGK,SCHG,XLG,QQEW>
- [T7] totalrealreturns，QQQ/FOCPX/FSELX/TRBCX/CGGR：<https://totalrealreturns.com/n/QQQ,FOCPX,FSELX,TRBCX,CGGR>
- [T8] totalrealreturns，QQQ/BPTRX/FDGRX/TCHP：<https://totalrealreturns.com/n/QQQ,BPTRX,FDGRX,TCHP,BITO>
- [T9] totalrealreturns，QQQ/FBGRX/FCNTX/FBCG/JGRO：<https://totalrealreturns.com/n/QQQ,FBGRX,FCNTX,FBCG,JGRO>
- [T10] totalrealreturns，QQQ/NANC：<https://totalrealreturns.com/n/QQQ,NANC>
- [T11] totalrealreturns，QQQ/JEPQ/QYLD/QQQI/XYLD/JEPI：<https://totalrealreturns.com/n/QQQ,JEPQ,QYLD,QQQI,XYLD,JEPI>
- 近 5 年窗口回撤（加入 2021-10-19 上市的 BITO，把公共窗口限定为 2021-10-19 至 2026-10-26）：
  [D1](https://totalrealreturns.com/n/QQQ,SSO,UPRO,QLD,TQQQ,BITO)、
  [D2](https://totalrealreturns.com/n/QQQ,SMH,SOXX,SPMO,XLK,BITO)、
  [D3](https://totalrealreturns.com/n/QQQ,MTUM,QUAL,SPY,RSP,VGT,BITO)、
  [D4](https://totalrealreturns.com/n/QQQ,FOCPX,FSELX,FBGRX,AIQ,ARKK,BITO)、
  [D5](https://totalrealreturns.com/n/QQQ,QYLD,XYLD,AIEQ,QQEW,BITO)
- chartrow 交叉核对：[QQQ 滚动收益](https://chartrow.com/quote/qqq/trailing-returns)、
  [QQQ 月度收益](https://chartrow.com/quote/qqq/monthly-returns)、
  [QQQ 与 TQQQ 对比](https://chartrow.com/compare/qqq-vs-tqqq)、
  [SPMO 滚动收益](https://chartrow.com/quote/spmo/trailing-returns)、
  [QQQM 滚动收益](https://chartrow.com/quote/qqqm/trailing-returns)、
  [纳指 100 集中度](https://chartrow.com/nasdaq-100/concentration)
- [Z1] Zacks，AMOMX 业绩（二手）：<https://zacks.com/funds/mutual-fund/quote/AMOMX/performance>

### 发行人与监管文件

- ProShares：[TQQQ](https://www.proshares.com/our-etfs/leveraged-and-inverse/tqqq)、
  [QLD](https://www.proshares.com/our-etfs/leveraged-and-inverse/qld)、
  [SSO](https://www.proshares.com/our-etfs/leveraged-and-inverse/sso)、
  [UPRO](https://www.proshares.com/our-etfs/leveraged-and-inverse/upro)（标准化业绩，截至 2026-09-30）
- Global X，QYLD（业绩截至 2026-09-30，分配率与期权行权价截至 2026-10-26）：<https://www.globalxetfs.com/funds/qyld/>
- Invesco，QQQ 业绩页（业绩表未能加载；页面列明费率 0.18%，并称截至 2026-06-30 近 10 年中
  有 7 年跑赢标普 500）：<https://www.invesco.com/qqq-etf/en/performance.html>
- SEC，Invesco QQQ Trust N-CSRS（财年 NAV 总回报）：
  <https://www.sec.gov/Archives/edgar/data/0001067839/000119312526250483/8deb6f921189c0e.htm>
- 持仓（stockanalysis，二手）：[QQQ](https://stockanalysis.com/etf/qqq/holdings/)、
  [SMH](https://stockanalysis.com/etf/smh/holdings/)、[SPMO 持仓](https://stockanalysis.com/etf/spmo/holdings/)、
  [SPMO 概况](https://stockanalysis.com/etf/spmo/)

### 指数规则与市场结构

- Nasdaq，2023 年特别再平衡公告（2023-07-07）：<https://indexes.nasdaqomx.com/docs/NDX_SpecialRebalance_2023.pdf>
- 特别再平衡阈值和权重（二手）：[WisdomTree](https://www.wisdomtree.com/dk/insights/blog/what-the-nasdaq-100s-special-rebalance-does-and-does-not-mean-for-investors)、
  [Daily Investor](https://dailyinvestor.com/investing/23186/nasdaq-100-rebalance-to-shake-up-weights-of-tech-giants/)
- Nasdaq，2026 年 2 月征询：<https://indexes.nasdaqomx.com/docs/NDX_Consultation-February_2026.pdf>
- Nasdaq，征询结论（2026-03-30）：<https://indexes.nasdaqomx.com/docs/Nasdaq-100_Index_Consultation_February_2026_Summary_of_Responses_and_Conclusion.pdf>
- Nasdaq，2025 年年度成分变更新闻稿：<https://www.nasdaq.com/press-release/annual-changes-nasdaq-100-indexr-2025-12-13>
- Nasdaq，2025 年重构与表现回顾（经搜索摘要转述）：<https://www.nasdaq.com/articles/global-indexes/2025-nasdaq-100-reconstitution-and-performance-highlights>
- SpaceX 快速纳入（二手）：[Contrary Research](https://research.contrary.com/report/spacex-joins-the-nasdaq-100)、
  [Motley Fool 2026-04-01](https://www.fool.com/investing/2026/04/01/spacex-could-join-the-nasdaq-in-record-time-after/)、
  [Nasdaq.com 文章](https://www.nasdaq.com/articles/spacex-set-rapid-entry-nasdaq-100-etfs-focus)
- AI 资本开支（二手）：[AI Weekly 转述 FT，2026-07-31](https://aiweekly.co/alerts/amazon-microsoft-alphabet-meta-plan-725b-ai-capex-in-2026)；
  FT 原文（付费墙，未读）：<https://www.ft.com/content/dcf3873e-7b32-4a24-a90d-3bccf1d2c996>

### 主动管理胜率

- S&P DJI，SPIVA U.S. Year-End 2025：<https://www.spglobal.com/spdji/en/spiva/article/spiva-us-year-end-2025/>
- S&P DJI，SPIVA U.S. Mid-Year 2026：<https://www.spglobal.com/spdji/en/documents/spiva/spiva-us-mid-year-2026.pdf>
- InvestmentNews，2026-03-04：<https://investmentnews.com/equities/active-managers-stumble-again-in-2025-as-large-caps-dominate/265541>

### 量化机构

- Institutional Investor（二手、付费墙）：[RIEF 2025-11 反弹](https://www.institutionalinvestor.com/article/premium/renaissances-public-funds-stage-double-digit-comeback-november)、
  [RIEF 2025-10 亏损](https://www.institutionalinvestor.com/article/renaissance-suffers-huge-losses-october)、
  [RIEF 2024 年](https://www.institutionalinvestor.com/index%2ephp/article/2e0uykr3vn5booz0smrcw/hedge-funds/renaissances-2024-rebirth)
- AlphaMaven，2026 年 7 月量化业绩（二手，抓取被拒，经搜索摘要转述）：<https://alpha-maven.com/story/hedge-fund/quant-hedge-funds-were-winners-in-a-chaotic-july>
- Bloomberg，AQR Apex 2025 年业绩（标题）：<https://www.bloomberg.com/news/articles/2026-01-02/aqr-s-multistrategy-apex-gains-19-6-in-turbulent-quant-year>
- AQR Delphi（二手）：[Hedgeweek](https://www.hedgeweek.com/aqr-strategies-post-double-digit-h1-gains/)、
  [HedgeCo](https://hedgeco.net/news/12/2025/aqr-capital-management-posts-strong-year-to-date-gains-as-2025-winds-down.html)
- Two Sigma（二手）：[Hedgeweek 2024-01-08](https://hedgeweek.com/two-sigma-posts-solid-gains-despite-year-of-drama)、
  [Bloomberg 2026-04-06](https://www.bloomberg.com/news/articles/2026-04-06/two-sigma-profits-from-chaotic-march-beating-multistrat-peers)
- MSCI，2025 年夏季量化回撤（2025-10-30）：<https://www.msci.com/research-and-insights/blog-post/unraveling-summer-2025s-quant-fund-wobble>
- 路透转述 Goldman，2025-10 系统化基金亏损（二手）：<https://de.tradingview.com/news/reuters.com%2C2025%3Anewsml_L6N3VO0IN%3A0-systematic-hedge-funds-hit-with-daily-losses-in-october-says-goldman-sachs>
- Hedgeweek，2026-01-22：<https://www.hedgeweek.com/quant-hedge-funds-see-worst-drawdown-since-october-as-crowded-trades-unwind/>
- Hedgeweek，2026-07-07：<https://www.hedgeweek.com/quant-funds-suffer-steepest-momentum-drawdown-since-2023-amid-factor-rotation/>
- Robeco：[Conservative Equities，2025-05-21](https://www.robeco.com/en-ch/insights/2025/05/8-out-of-9-conservative-equities-scores)、
  [2025 年报（经搜索摘要转述）](https://www.robeco.com/files/docm/docu-riam-annu-2025.pdf)
- Man Group，截至 2026-03-31 的季度交易公告：<https://www.investegate.co.uk/announcement/rns/man-group--emg/trading-statement-for-quarter-ended-31-march-2026-/9533708>
- Asness 的「市场更不有效」观点（二手转述）：<https://www.morningstar.com.au/insights/stocks/254489/legendary-investor-markets-are-less-efficient-and-social-media-is-the-big-culprit>
- Alpha Architect，BlackRock 的反驳研究（2026-06-26）：<https://alphaarchitect.com/impressive-markets-hypothesis/>

### 零售工具

- eToro CopyTrader 页面（风险披露）：<https://www.etoro.com/copytrader/>
