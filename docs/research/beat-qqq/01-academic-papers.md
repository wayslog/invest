# 跑赢 QQQ：2023–2026 年学术与工作论文证据（01）

- 研究日期：2026-10-27
- 目标口径：扣除成本后跑赢 QQQ 买入持有（基准不变）；5,000 USD 本金，IBKR，W-8BEN（股息预扣 10%，美国侧价差不征税）；只交易美股和美股 ETF；只用免费数据；净值低于 2,500 USD 清仓终止，低于 5,000 USD 不开新个股仓。
- 已排除方向：周度成分股打分选股（已失败，且低于同池随机抽样中位数）；高波动个股动量（用户否决）。

## 一、研究日期与时效规则

1. 主证据必须在 2023-01 之后发表或更新（期刊正式版、NBER/SSRN/arXiv 新版本均可）。
2. 更早的经典论文只有在 2023 年后被重新检验或复现时才引用，并标注「经典 + 近年检验」。
3. 数字只取自原文摘要、正文或作者/期刊页面。只能从博客、媒体或机构转述取得的，标注「二手来源，未核实」；SSRN 页面在本次检索中多次拒绝访问，相关条目已注明读取范围。
4. 证据强度：**强**＝同行评审，大样本，含样本外、发表后或成本检验，并有独立研究佐证；**中**＝同行评审但范围有限，或高质量工作论文（NBER、知名作者）尚未正式发表；**弱**＝未经同行评审的从业者论文或博客、单作者 arXiv、作者有商业利益或依赖未核实的二手来源。
5. 标为「本研究粗算」的数字并非论文证据。它们只用 FRED 公开序列做量级检查：纳斯达克 100 价格指数（不含股息）；去杠杆部分按 3 个月国库券利率计息，杠杆部分扣融资成本和 0.95% 年费；未计佣金、滑点和税；2006 年 QLD 上市前的杠杆为合成；参数均为事后选择。这些结果不是样本外证据，也不能替代预登记回测。

## 二、结论摘要

1. **因子与异象：多数可复制，但扣成本、扣发表后衰减后几乎无剩余。** Chen & Velikov（JFQA 2023）研究 204 个异象，在计入有效价差、发表后衰减和 2000 年代后的交易环境后，平均预期收益仅约 4 bps/月，最强者约 10 bps，组合方法约 20 bps；这还未计价格冲击。Chen、Lopez-Lira & Zimmermann（2025 版）发现，无论是同行评审的信号还是数据挖掘的信号，样本外都只保留约 50% 的预测力。Smart Beta Mirage（JFQA 2024）显示，智能贝塔指数上市前的纸面市场调整收益约 3%，ETF 上市后降至约 −0.5% 至 −1%。Jensen-Kelly-Pedersen（JF 2023）证明因子可复制，在巨型和大盘股中的复制率约 77%–82%；但「可复制」不等于做多不做空、5,000 USD、每笔 1 USD 佣金的账户能跑赢 QQQ。项目此前打分选股失败，与这一系列证据一致。
2. **机器学习和大模型选股：毛收益真实存在，但对本项目基本不可执行。** Avramov 等（MS 2023）发现，排除微盘、困境股或高波动时期后，机器学习收益明显下降，计入成本后进一步恶化。Azevedo-Hoegner-Velikov 与 Jensen-Kelly-Malamud-Pedersen（RFS 2026）则显示，长周期、考虑成本的机器学习在大盘股多空组合中仍可获利。不过它们依赖数百个付费基本面特征和做空。大模型新闻预测主要在小盘股和坏消息中有效，且随着大模型普及而减弱（Lopez-Lira & Tang 2025 版）；预训练模型的记忆和前视偏差使截止日前的回测无法识别（Lopez-Lira-Tang-Zhu 2025）；Kim-Muhn-Nikolaev 的大模型财报分析论文因数据不一致已被撤回。
3. **指数集中度是主动跑赢市值加权指数的结构性障碍。** 被动资金会使最大公司涨幅超出比例（Jiang-Vayanos-Zheng，RFS 2025）。分散化监管上限迫使大盘成长基金减持最大持仓，受约束基金表现更差，纳斯达克 100 在 2023 年因此做了特殊再平衡（Pástor-Sikorskaya-Wang，NBER 2026）。长期财富创造又极度集中于少数股票（Bessembinder 2024，二手来源细节）。结论是：任何低配超大盘、按打分挑小篮子的做法，默认都在押注会错过右尾。
4. **无杠杆择时基本不可能跑赢 QQQ。** 超过三分之一的股权溢价预测变量连样本内都已不显著；仍显著者约一半在样本外表现差（Goyal-Welch-Zafirov，RFS 2024）。异象作为整体不能预测市场收益（Cakici 等，RoF 2024）。时间序列动量的强度会被重叠收益机械抬高（Ahn 等 2026），在估值极端区也会失效（Suominen & Hjalmarsson 2026）。实盘对照显示：纳斯达克 100 Trendpilot（200 日均线切换国债）在 2021-05-19 至 2025-10-27 期间上涨 +61.3%，同期纳斯达克 100 价格指数为 +95.1%（本研究粗算，价格口径）。
5. **在大盘指数上，较稳健的增强方向是对市场组合本身做波动率缩放，而不是因子。** DeMiguel 等（JF 2024）转述 Barroso & Detzel：扣成本后，波动率管理只对市场因子仍然有效。Hood & Raughtigan（JPM 2025）发现，股指的波动率目标 alpha 主要来自杠杆效应带来的趋势暴露。反方证据同样存在：Cederburg 等（经典 + 近年检验）指出多数策略样本外失效；Nagel（NBER 2025）认为「波动率择时的动量」只是恰好在历史上表现好。要在收益上超过 QQQ，通常必须在低波动期使用大于 1 倍的暴露，真正的超额来源是**有控制的额外纳指 β**，而不是选股能力。
6. **宽基杠杆 ETF 的「波动损耗」并非必然，但尾部风险会直接触发本项目的 2,500 USD 硬线。** Murray & Sammon（2026）估算，宽基做多杠杆 ETF 为投资者带来逾 1,000 亿美元收益，其中逾 400 亿美元是相对直接持有标的的增量；单股杠杆 ETF 则因上市选择、波动损耗和择时而表现差。Hsieh 等（2025）证明，日度再平衡杠杆 ETF 的复利效应取决于收益自相关：趋势期有利，均值回复期不利。本研究粗算还显示，若从 2000-03 起点买入，**QQQ 买入持有本身**最低会跌到本金的约 19%，同样会触发硬线；也就是说，任何以纳指为核心的路线都必须正视这条底线。
7. **直接以纳斯达克 100/QQQ 为基准的研究很少，且以从业者工作论文为主。** Zarattini & Aziz（2023）的 QQQ/TQQQ 开盘区间突破报告大幅跑赢 QQQ，但该研究未经同行评审、假设无滑点、需要做空和日内 4 倍杠杆；一项独立复现（二手来源，未核实）称扣成本后收益归零。对 5,000 USD 账户而言，按每笔 1 USD 计，佣金会占去大部分边际收益。SPY 日内动量论文的不加杠杆基础版本，同期甚至跑输 SPY（178% 对 227%）。

## 三、逐项证据表

### A. 因子与异象的样本外、发表后检验（含大盘与低成本实施）

| 论文 | 年份 | 样本期 | 核心发现 | 是否扣成本 | 是否适用大盘股 | 对 QQQ/标普的含义 | 证据强度 | 链接 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Chen & Velikov，Zeroing in on the Expected Returns of Anomalies，JFQA 58(3) | 2023 | 美国 CRSP 历史；交易技术现代期为 2000 年代初以后（起止细节以原文为准） | 204 个异象经有效价差、发表后效应和现代交易期调整后，平均预期收益约 4 bps/月；最强者扣除数据挖掘后至多约 10 bps；组合约 20 bps；未计价格冲击 | 是（有效价差，作者称为偏低估计） | 部分（成本缓释用市值加权等） | 用公开异象做多空增强，扣成本后几乎没有空间；只做多的小账户更难 | 强 | [Cambridge](https://www.cambridge.org/core/journals/journal-of-financial-and-quantitative-analysis/article/zeroing-in-on-the-expected-returns-of-anomalies/945133D5A3ECEEAF466AEE91551FD225) |
| Jensen, Kelly & Pedersen，Is There a Replication Crisis in Finance?，JF 78(5)（经典 Hou-Xue-Zhang 2020 的近年反检验） | 2023 | 153 个因子，93 个国家 | 多数因子可复制且样本外有效；NBER 版本中，美国巨型股和大盘股复制率分别为 77.3% 和 81.5%，全样本为 84.0% | 否（研究的是毛收益显著性） | 是（按 NYSE 分位分组） | 因子溢价在大盘中仍存在，但这是多空毛收益，不能直接推出只做多能跑赢以超大盘成长股为主的 QQQ | 强 | [DOI](https://doi.org/10.1111/jofi.13249) / [NBER](https://www.nber.org/papers/w28432) |
| Chen, Lopez-Lira & Zimmermann，Does Peer-Reviewed Research Help Predict Stock Returns?（arXiv v7） | 2025-12 | CRSP/Compustat 历史；挖掘 29,000 个会计比率 | 同行评审信号与 t>2 的数据挖掘信号表现相近，样本外均只保留约 50% 的预测力；理论标签并不能提高样本外表现 | 否 | 未单独说明 | 自行挖掘或采用文献信号时，应预期样本外收益腰斩；这与本项目历史打分失败一致 | 中（工作论文，作者权威） | [arXiv](https://arxiv.org/abs/2212.10317) |
| Bowles, Reed, Ringgenberg & Thornock，Anomaly Time，JF 79(5) | 2024 | 美国，带信息首次公开日期的数据库（期间以原文为准） | 异象收益集中在信息公开后约一个月内，随后迅速衰减；每年 6 月建仓的学术惯例使用了过时信息 | 否 | 未单独说明 | 若想吃到异象收益，必须在信息发布后迅速交易，与周度/月度低成本小账户的执行方式相冲突 | 强 | [DOI](https://doi.org/10.1111/jofi.13372) |
| Huang, Song & Xiang，The Smart Beta Mirage，JFQA 59(6) | 2024 | 美国智能贝塔 ETF 上市前后 | 指数在 ETF 上市前的纸面市场调整收益约 3%，上市后约为 −0.5% 至 −1%；作者归因于构建指数时的数据挖掘 | 是（以实际上市后表现衡量） | 是（多为大盘因子 ETF） | 用因子 ETF 替代 QQQ，期望超额为负 | 强 | [DOI](https://doi.org/10.1017/S0022109023000674) |
| Ben-David, Franzoni, Kim & Moussawi，Competition for Attention in the ETF Space，RFS 36(3) | 2023 | 美国 ETF | 专题和特色 ETF 上市后五年经风险调整约损失 30%，原因是上市时成分股已被高估，而非费用 | 是 | 是 | AI 或科技主题 ETF 不太可能跑赢 QQQ | 强 | [NBER](https://www.nber.org/papers/w28369) |
| Greenwood & Sammon，The Disappearing Index Effect，JF | 2024 | 1990 年代至近十年 | 标普 500 纳入的异常收益从 1990 年代约 7.4% 降至近十年不足 1%，剔除效应同样缩小 | 不适用 | 是 | 「指数纳入/剔除」这类大盘事件型 alpha 已基本消失 | 强 | [作者页](https://marcosammon.com/research/) |

### B. 机器学习、大模型与替代数据选股

| 论文 | 年份 | 样本期 | 核心发现 | 是否扣成本 | 是否适用大盘股 | 对 QQQ/标普的含义 | 证据强度 | 链接 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Avramov, Cheng & Metzker，Machine Learning vs. Economic Restrictions，MS 69(5) | 2023 | 美国个股（期间以原文为准） | 机器学习收益主要来自难套利股票和高套利限制时期；排除微盘、困境股或高波动期后显著下降；计入合理成本后因高换手而进一步恶化 | 是 | 否（大盘中明显减弱） | 免费数据加机器学习选大盘股，难以复制论文中的高夏普 | 强 | [DOI](https://doi.org/10.1287/mnsc.2022.4449) |
| Azevedo, Hoegner & Velikov，The Expected Returns on Machine-Learning Strategies（工作论文） | 2023–2025 | 1957-03 至 2021-12；样本外 2005–2021 | 计入成本、发表后衰减和小数报价后，绩效平均下降约 57%，但 LSTM 策略的预期毛/净夏普仍为 0.94/0.84；在 NYSE 80 分位以上的大盘股中，多空收益为 66 bps/月（t=3.13） | 是（Chen-Velikov 价差） | 是（多空） | 机器学习在大盘中有信号，但依赖 320 个异象特征（付费数据）和做空，换手超过 50%；本项目不可执行 | 中（工作论文） | [AEA 2025](https://www.aeaweb.org/conference/2025/program/paper/TihddefB) / [SSRN 4702406](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=4702406) |
| Jensen, Kelly, Malamud & Pedersen，Machine Learning and the Implementable Efficient Frontier，RFS 39(10) | 2026 | 美国（期间以原文为准） | 忽视成本的机器学习过度依赖短命的小市值特征，导致净收益差；把成本纳入目标、直接学习组合权重后，净前沿明显改善 | 是 | 部分 | 结论支持「低换手、慢信号」，但实现需要完整特征库和优化器 | 强 | [DOI](https://doi.org/10.1093/rfs/hhag022) |
| Blitz, Hanauer, Hoogteijling & Howard，The Term Structure of Machine Learning Alpha，JFDS | 2023 | 美国，重点为 2004–2021 | 预测 1 个月收益的机器学习策略在 2004 年后扣成本接近零；3–12 个月周期模型更依赖慢信号和传统因子，在高效组合构建下扣成本仍为正；3 个月周期比 1 个月周期每年多 1.58% | 是 | 部分 | 若仍做选股，必须用长周期、低换手；作者来自资管机构（Robeco） | 中 | [DOI](https://doi.org/10.3905/jfds.2023.1.135) |
| Kelly, Malamud & Zhou，The Virtue of Complexity in Return Prediction，JF 79(1)（经典 + 近年检验，见下条） | 2024 | 美国市场择时 | 参数多于观测值的复杂模型理论上和经验上都能提高市场收益预测 | 部分 | 是（指数层面） | 支持用复杂模型对指数择时，但受到下条的直接挑战 | 中 | [DOI](https://doi.org/10.1111/jofi.13298) |
| Nagel，Seemingly Virtuous Complexity in Return Prediction，NBER w34104 | 2025-08 | 同上 | 短窗口随机傅里叶特征的预测本质上是近期收益加权平均，即**波动率择时的动量**；在人工构造的均值回复数据中会失败；这一策略只是恰好在历史上表现好 | 否 | 是 | 「复杂机器学习择时跑赢指数」可能只是动量加波动率择时的伪装；这也是本文路线 A/B 的重要反证 | 中（NBER 工作论文） | [NBER](https://www.nber.org/papers/w34104) |
| Lopez-Lira & Tang，Can ChatGPT Forecast Stock Price Movements?（arXiv v6） | 2025-10 | GPT 知识截止日后的新闻标题 | GPT-4 能预测后续漂移，在小盘股和坏消息上更明显；随着大模型使用普及，策略收益下降 | 摘要未提及 | 否（以小盘为主） | 大模型新闻信号在大盘中优势弱且正在消失 | 中 | [arXiv](https://arxiv.org/abs/2304.07619) |
| Glasserman & Lin，Assessing Look-Ahead Bias in Stock Return Predictions Generated by GPT Sentiment Analysis | 2023 | 标普 500 新闻（汤森路透）及 6,000 余家公司 | 样本内，匿名化标题反而优于原标题，「分心」（模型自带公司知识）的影响大于前视偏差，在大公司中尤其明显 | 否 | 是（大公司影响更大） | 用大模型分析大盘股新闻，会被模型对知名公司的先验干扰 | 中 | [arXiv](https://arxiv.org/abs/2309.17322) |
| Lopez-Lira, Tang & Zhu，The Memorization Problem: Can We Trust LLMs' Economic Forecasts? | 2025（2026 年再修订） | 多类经济数据与股票收益 | 模型能复现知识截止日前的数据；指令或掩码无法阻止回忆；截止日前的预测能力在统计上不可识别 | 不适用 | 是 | 任何截止日前的大模型选股回测都不能作为证据 | 中 | [arXiv](https://arxiv.org/abs/2504.14765) |
| He, Lv, Manela & Wu，Chronologically Consistent Large Language Models | 2025 | 次日新闻收益预测 | 只用当时可得文本训练的模型，夏普与大得多的 Llama 相近，说明在该任务中前视偏差有限 | 未说明 | 未说明 | 提供了一种去偏方法，但不改变「小盘、日频、高换手」的执行难题 | 中 | [arXiv](https://arxiv.org/abs/2502.21206) |
| Kim, Muhn & Nikolaev，Financial Statement Analysis with Large Language Models | 2024–2025 | — | v3（2025-02）已撤回：合作者在复现中发现数据和分析不一致 | — | — | 广为流传的「GPT 读财报胜过分析师」结论目前不可引用 | 不适用（已撤回） | [arXiv](https://arxiv.org/abs/2407.17866) |
| Chen, Green, Gulen & Zhou，What Does ChatGPT Make of Historical Stock Returns? | 2025-12 | 个股短期收益预测 | 个股收益倾向反转，大模型却过度外推趋势、过度乐观并低估极端上涨，提示工程难以纠正 | 不适用 | 是 | 让大模型看图或看历史收益来判断涨跌，会系统性偏误 | 中 | [AEA 2026](https://www.aeaweb.org/conference/2026/program/paper/zNrQ4Yn6) |
| Lv，Do Sell-side Analyst Reports Have Investment Value? | 2025 | 2000–2023 年 120 万份卖方研报 | 大模型嵌入研报文本可预测长期收益，超出数值预测和已知因子 | 摘要未提及 | 未说明 | 依赖付费研报数据，免费数据下不可复现 | 弱–中（工作论文） | [arXiv](https://arxiv.org/abs/2502.20489) |
| Yılkı，Supply Chain Propagation of Textual Signals | 2026 | 2011–2025 年 255 家标普 500 公司 | 10-K 文本嵌入沿供应链传播后，多空夏普 0.86，五因子 alpha 为 7.27%/年 | 摘要未提及 | 是 | 小样本、单作者、未计成本，只能作为线索 | 弱 | [arXiv](https://arxiv.org/abs/2606.29290) |
| Fitchue, Stowe & Schwartz，Machine Learning-Driven Strategies for NASDAQ 100 Outperformance，J. Accounting & Finance | 2026 | 2018–2025，「七巨头」 | XGBoost 加宏观与技术过滤：VIX 过滤可降回撤，但滞后会拖累快速反弹期收益，且有过拟合风险 | 未说明 | 是 | 直接以纳指 100 为基准，但期刊层级低，结论偏定性 | 弱 | [DOI](https://doi.org/10.33423/jaf.v26i2.8290) |

### C. 指数集中度（七巨头、AI 龙头）与主动跑赢的难度

| 论文 | 年份 | 样本期 | 核心发现 | 是否扣成本 | 是否适用大盘股 | 对 QQQ/标普的含义 | 证据强度 | 链接 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Pástor, Sikorskaya & Wang，The Hidden Cost of Stock Market Concentration: When Funds Hit Regulatory Limits，NBER w35007 | 2026（2026-09 修订） | 2019–2024，约 5,000 只美国股票基金 | 集中度上升使分散化监管上限频繁约束大盘成长基金：受约束基金会减持最大持仓并降低股票仓位，表现更差。布斯评论转述：减持基金随后三个月少赚约 28 bps，2023–24 年超过 1 个百分点；被迫卖出的股票随后六个月跑赢 2.3%。纳指 100 于 2023-07 因此下调七巨头权重。基于约束的持有度指标可预测最大公司的收益 | 是（基金净值） | 是 | 机构必须低配超大盘，个人不受这一约束；这是唯一支持「超配超大盘」的学术机制（见路线 C），但效应量不大 | 中（NBER 工作论文；部分数字为机构转述） | [NBER](https://www.nber.org/papers/w35007) / [Booth Review](https://www.chicagobooth.edu/review/hidden-cost-magnificent-seven) |
| Jiang, Vayanos & Zheng，Passive Investing and the Rise of Mega-Firms，RFS 38(12) | 2025 | 1996–2020，标普 500 及其被动资金流 | 被动资金流入使最大公司价格和特质波动上升最多，且上涨超出比例；即使只是主动转被动，大盘也可能上涨。早期版本估计 50 家最大公司因此多涨约 30%（二手来源，未核实） | 不适用 | 是 | 被动化趋势持续时，超大盘有结构性顺风，主动低配很吃亏；资金流逆转时则相反 | 强 | [RFS](https://academic.oup.com/rfs/article/38/12/3461/8280528) / [NBER](https://www.nber.org/papers/w28253) |
| Bessembinder，Which U.S. Stocks Generated the Highest Long-Term Returns?（SSRN）（经典 2018 偏度研究 + 近年更新） | 2024 | 1925-12 至 2023-12，29,078 只股票 | 51.6% 的股票累计收益为负；财富创造集中于极少数股票（二手来源，未核实） | 不适用 | 是 | 小篮子主动选股大概率错过右尾，与项目选股落后于指数的结果一致 | 中（细节为二手来源） | [SSRN](https://doi.org/10.2139/ssrn.4897069) |
| Sammon & Shim，Index Rebalancing and Stock Market Composition，JFE | 2026 | 美国指数基金 | 指数再平衡相当于隐性择时，多空组合年化约 −4.67%，拖累 47–70 bps/年；再平衡更少且有滞后的指数每年约可省 50 bps | 是 | 是 | 指数自身有可被规避的小额拖累，但对 5,000 USD 账户，复制 100 只成分股的佣金远超 50 bps | 强 | [作者页](https://marcosammon.com/research/) |
| Ruf，Diversifying an Index | 2023 | 纳指 100 于 2023-07 的特殊再平衡 | 纳斯达克的封顶方法会产生副作用（例如改变权重排序），作者提出替代规则 | 不适用 | 是 | 说明 QQQ 权重是封顶的市值加权，并非纯市值加权 | 弱–中（arXiv） | [arXiv](https://arxiv.org/abs/2311.10713) |

### D. 杠杆、波动率管理与趋势择时（含批评）

| 论文 | 年份 | 样本期 | 核心发现 | 是否扣成本 | 是否适用大盘股 | 对 QQQ/标普的含义 | 证据强度 | 链接 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Goyal, Welch & Zafirov，A Comprehensive 2022 Look at the Empirical Performance of Equity Premium Prediction，RFS（经典 Goyal-Welch 2008 + 近年检验） | 2024 | 至 2021 年底；共 46 个变量 | 2008 年后新提出的 29 个变量中，逾三分之一连样本内都不显著；仍显著者约一半样本外表现差；只有少数变量仍然可用 | 否 | 是（市场层面） | 用估值、宏观变量择时 QQQ 不可靠 | 强 | [DOI](https://doi.org/10.1093/rfs/hhae044) |
| Cakici, Fieberg, Metko & Zaremba，Do Anomalies Really Predict Market Returns?，Review of Finance 28(1) | 2024 | 42 个国家 | 多种机器学习方法下，异象整体不能预测市场收益；美国的少量证据缺乏外部有效性，且依赖细小的方法选择 | 否 | 是 | 用横截面异象信号对指数择时不可靠 | 强 | [DOI](https://doi.org/10.1093/rof/rfad025) |
| DeMiguel, Martín-Utrera & Uppal，A Multifactor Perspective on Volatility-Managed Portfolios，JF 79（经典 Moreira-Muir 2017 + 近年检验） | 2024 | 美国因子，样本外 | 条件多因子波动率管理在样本外扣成本后仍优于无条件组合；文中转述 Barroso & Detzel（2021）：扣成本后，单因子波动率管理只对市场因子有效 | 是 | 是 | 对市场组合（QQQ）做波动率缩放，是少数扣成本后仍有支撑的指数增强方式 | 强 | [DOI](https://doi.org/10.1111/jofi.13395) / [LBS](https://lbsresearch.london.edu/id/eprint/3716) |
| Cederburg, O'Doherty, Wang & Yan，On the Performance of Volatility-Managed Portfolios，JFE（经典 2020；2024 年 DeMiguel 等正面回应） | 2020 | 103 个策略 | 支撑性回归中的 alpha 在实时样本外大多不能转化为更高的夏普或确定性等价收益，原因是结构不稳定 | 部分 | 是 | 主要反证：波动率管理可能只在样本内有效 | 强（经典） | [PDF](https://www.lehigh.edu/~xuy219/research/COWY.pdf) |
| Hood & Raughtigan，Volatility Targeting Is Trendy，JPM | 2025 | 14 个全球股指期货及商品、债券、外汇期货 | 波动率目标相对买入持有的 alpha 主要来自趋势跟踪暴露（下跌伴随波动上升的杠杆效应）；控制趋势后 alpha 基本消失；alpha 只出现在股指，在其他资产中不存在 | 未说明 | 是（股指） | 股指波动率目标确有超额，但它本质上是趋势暴露，会继承趋势策略的 V 形反转风险 | 中–强 | [DOI](https://doi.org/10.3905/jpm.2025.1.764) |
| Dai, Hong, Merton & Pellerin，Forecasting and Managing Volatility: An S&P 500 Case Study，JOIM 23(1) | 2025 | 1997–2023，日内和日度数据 | 在标普 500 与国库券之间做波动率目标；预测误差更小并不必然带来更稳定的波动；隐含波动率与简单历史估计组合时，控制效果好且换手低 | 部分（讨论换手） | 是 | 可用免费的 VXN/VIX（FRED）和 20 日实现波动构建低换手的波动缩放 | 中 | [JOIM](https://joim.com/article/forecasting-and-managing-volatility-an-sp-500-case-study/) |
| Ahn, Hambusch & Hong，How Overlapping Returns Inflate Measured Time Series Momentum，JRFM 19(1) | 2026 | 1996–2019，标普 500 与 ASX 200 | 重叠收益窗口会机械累积自相关，夸大时间序列动量；用非重叠收益时效应变弱，统计上不显著 | 否 | 是 | 「回看期越长趋势越强」可能是测量假象 | 中 | [DOI](https://doi.org/10.3390/jrfm19010046) |
| Suominen & Hjalmarsson，Boundaries of Time-Series Momentum，Financial Management | 2026 | 股市长历史，使用 CAPE、股息率、期限利差 | 时间序列动量在中等估值区有效，在估值历史极端区附近失效，因为方向常在此处反转 | 否 | 是 | 高估值阶段的趋势信号更不可靠 | 中 | [DOI](https://doi.org/10.1111/fima.70055) |
| Hsieh, Chang & Chen，Compounding Effects in Leveraged ETFs: Beyond the Volatility Drag Paradigm（经典「杠杆 ETF 不宜长持」观点的近年检验） | 2025 | 约 20 年 SPY 与 QQQ 数据 | 收益独立时，日度杠杆 ETF 相对目标倍数的期望复利为正；趋势期增强，均值回复期削弱；自相关、波动聚集和制度持续性共同决定其优劣 | 部分（讨论再平衡频率） | 是（QQQ） | 杠杆纳指 ETF 在趋势或低波动期的长期持有并非必然损耗，这是路线 A/B 的理论支撑 | 中（arXiv） | [arXiv](https://arxiv.org/abs/2504.20116) |
| Murray & Sammon，The Costs and Benefits of Leveraged ETFs（SSRN，2026-08 更新） | 2026 | 美国杠杆 ETF | 宽基做多杠杆 ETF 为投资者带来逾 1,000 亿美元收益，其中逾 400 亿美元是相对直接持有标的的增量（原因是结构性拖累较小且市场上涨）；单股杠杆 ETF 多在高波动、高过往收益时上市，损耗、融资成本和择时都更差 | 是（费用、融资、损耗） | 是 | 只考虑宽基杠杆 ETF（如 QLD），避开单股杠杆 ETF；该收益依赖市场上涨 | 中（工作论文，作者权威） | [作者页](https://marcosammon.com/research/) / [SSRN](https://doi.org/10.2139/ssrn.7133021) |
| Pauchlyová（Quantpedia），Leveraged ETFs in Asset Allocation: Opportunity or Trap? | 2025 | 1926–2025，2 倍为模拟 | 美股 2 倍持有：年化 12.6%、波动 36.9%（1 倍为 10.2%、18.2%）；加 10 个月均线过滤后，2 倍为 13.5%、波动 25.3%；未计交易成本，参数为事后选择 | 部分（费用与融资） | 是（标普） | 趋势过滤加 2 倍可提高收益并压低波动，但证据很弱 | 弱 | [Quantpedia](https://quantpedia.com/leveraged-etfs-in-asset-allocation-opportunity-or-trap/) |
| 纳斯达克 100 Trendpilot 指数（本研究粗算，FRED） | 实盘 2021-05-19 至 2025-10-27 | 同左 | 基于 200 日均线在纳指与国债间切换的规则指数（细则以方法论为准）：+61.3%（年化约 11.4%，最大回撤 −18.7%），纳指 100 价格指数为 +95.1%（年化约 16.3%，最大回撤 −35.6%）；价格口径，Trendpilot 计息口径未核实 | 指数层面无交易成本 | 是 | 不加杠杆的趋势择时近年明显落后于 QQQ | 中（真实指数数据，非论文） | [FRED 趋势](https://fred.stlouisfed.org/series/NASDAQNDXTRND1) / [FRED NDX](https://fred.stlouisfed.org/series/NASDAQ100) |

### E. 直接以纳斯达克 100/QQQ 为基准，或以大盘 ETF 日内交易为对象的研究

| 论文 | 年份 | 样本期 | 核心发现 | 是否扣成本 | 是否适用大盘股 | 对 QQQ/标普的含义 | 证据强度 | 链接 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Zarattini & Aziz，Can Day Trading Really Be Profitable?（SSRN 4416622） | 2023 | 2016-01 至 2023-02 | QQQ 5 分钟开盘区间突破，多空交易约各半：25,000 USD 本金、日内 4 倍上限、每股 0.0005 USD 佣金、**假设无滑点**；QQQ 版年化 alpha 33%；TQQQ 版总收益 1,484%，QQQ 为 169%（二者均未计滑点） | 部分（只计佣金） | 是 | 直接跑赢 QQQ 的说法存在，但需做空、日内杠杆和高频交易；独立复现称毛收益可重现、扣成本后为零（MQL5 博客，二手来源，未核实）；约 250 次交易、500 笔委托/年，按项目每笔 1 USD 计约占本金 10% | 弱（从业者论文，作者有商业利益） | [SSRN](https://papers.ssrn.com/abstract=4416622) / [复现博客](https://www.mql5.com/en/blogs/post/776235) |
| Zarattini, Aziz & Barbon，Beat the Market: An Effective Intraday Momentum Strategy for S&P500 ETF (SPY)（SFI 24-97） | 2024–2025 | 2007 至 2024 年初 | 计每股 0.0035 USD 佣金和 0.001 USD 滑点，10 万 USD 起始资金；基础版本总收益 178%，SPY 为 227%（跑输）；加波动缩放（最高 4 倍）后为 1,985%，年化 19.6%，夏普 1.33，最大回撤 25% | 是 | 是 | 超额主要来自杠杆加波动缩放；小账户的日内杠杆和佣金下限会吞掉大部分收益 | 弱–中（工作论文，作者有商业利益） | [SFI](https://www.sfi.ch/de/publications/n-24-97-beat-the-market-an-effective-intraday-momentum-strategy-for-s-p500-etf-spy) |
| Zarattini, Pagani & Wilcox，Does Trend Following Still Work on Stocks? | 2025 | 1950 至 2024-11；样本外 2005–2024 | 个股创历史新高突破的趋势跟踪：1991–2024 年化 15.19%，alpha 6.18%（未扣费；二手来源，未核实）；不到 7% 的交易贡献大部分利润；100 万 USD 以下账户受换手成本限制 | 部分 | 是 | 属于个股动量/趋势路线，接近用户已否决的方向，不纳入 | 弱 | [作者机构](https://concretumgroup.com/does-trend-following-still-work-on-stocks/) |
| Zarattini & Antonacci，A Century of Profitable Industry Trends（SSRN 4857230，2025 Dow Award） | 2024 | 1926-07 至 2024-03，48 个行业；31 只行业 ETF | 行业通道突破，按波动风险均衡，总杠杆上限 200%；具体收益与基准对比未能读取原文（未核实） | 未核实 | 是 | 行业 ETF 轮动是可选线索，但 31 只 ETF 对 5,000 USD 账户的佣金负担重 | 弱（结果未核实） | [CMT PDF](https://cmtassociation.org/wp-content/uploads/2026/02/Dow-Winner-A-Century-of-Profitable-Trends.pdf) |
| 监管背景：FINRA 规则 4210 修订（取消日内交易者 25,000 USD 门槛） | 2026 | — | 报道称 SEC 于 2026-04 批准取消 PDT 认定及 25,000 USD 门槛，改用日内保证金标准；2026-06-04 生效，券商最迟在 2027-10-20 前实施（二手来源，未核实 FINRA 原文；IBKR 实施时间需另行确认） | — | — | 日内策略的监管门槛降低，但成本和做空约束仍在 | 弱（二手来源） | [Schwab](https://international.schwab.com/story/sec-approves-scrapping-25000-day-trader-minimum) / [E*TRADE](https://us.etrade.com/knowledge/library/margin/pattern-day-trading-rule-change) |

## 四、对本项目的候选路线

总判断：在只用免费数据、5,000 USD、只做多的约束下，没有可靠证据表明任何**选股**方法能在扣成本后跑赢 QQQ。证据较多的方向是：**以纳指 100 为唯一风险资产，按规则调节暴露（0–1.5 倍或 0–2 倍）**，在平静上涨期多承担一些 β，在高波动期降低暴露。下面的路线都需要按项目惯例先预登记，再在新的连续账户中验证；不得在已查看的历史区间上调参后宣称样本外。

> 基线备注（不算策略）：QQQM 与 QQQ 跟踪同一指数，费用率约低 5 bps/年（以发行人最新披露为准）。这是唯一几乎确定的「扣成本后跑赢」，但幅度很小。下述路线如用 QQQ 实施，也可用 QQQM 替代。

### 路线 A（首选）：纳指 100 波动率缩放，杠杆有上限

- **交易标的**：QQQ（或 QQQM）、QLD（2 倍日度纳指 100）、SGOV 或 BIL（短期国债 ETF，充当现金；IBKR 小账户现金几乎不计息）。
- **规则**：每周最后一个交易日收盘后，用 QQQ 过去 20 个交易日的日收益计算年化实现波动 σ（×√252）。目标暴露 L = min(1.5, 20% / σ)，下限 0。若与当前暴露之差 |ΔL| < 0.25 则不交易；否则在下一交易会话开盘成交。L ≤ 1 时持有 L 份 QQQ 和 (1 − L) 份 SGOV；1 < L ≤ 1.5 时持有 (2 − L) 份 QQQ 和 (L − 1) 份 QLD。可预登记一个对照变体：σ 取 20 日实现波动与 VXN（FRED 序列 VXNCLS）的平均值（受 Dai 等 2025 启发）；只登记一个主版本。
- **再平衡与换手**：每周检查，加 0.25 容忍带。本研究粗算约 6–7 次调整/年，名义换手约为净值的 2–2.5 倍/年。按项目成本（每笔 1 USD、单边 5 bps）计，每次调整 1–3 笔，约 6–21 笔/年，佣金约 6–21 USD/年（本金的 0.1%–0.4%）；QQQ 与 QLD 互换时成交额约为 ΔL 的 1–2 倍，滑点约 0.1%–0.25%/年。
- **为何可能跑赢**：DeMiguel 等（2024）和 Barroso & Detzel 认为，扣成本后只有市场组合的波动率管理有效；Hood & Raughtigan（2025）发现股指确有波动率目标 alpha；Hsieh 等（2025）与 Murray & Sammon（2026）表明，宽基杠杆 ETF 在趋势和低波动期复利为正。超额的本质是「在低波动期加 β」。
- **本研究粗算（非证据，仅供量级参考）**：1986–2026 年化 15.7%，买入持有为 14.2%，最大回撤 −53%（买入持有 −83%）；2010–2026 年化 18.9%，买入持有 17.8%，最大回撤 −32%（买入持有 −36%）。目标 25%、上限 2 倍时收益更高，但回撤更深。
- **主要风险与反证**：
  1. **硬线风险**：若从 2000-03 起步，粗算本路线最低跌至本金的约 50%（目标 25%、上限 2 倍时约 36%–41%），正好在 2,500 USD 线上或线下；同起点的 QQQ 买入持有最低约 19%。1987 年式单日暴跌、隔夜跳空不受周度信号保护。
  2. Cederburg 等：多数波动率管理策略在样本外失效。Nagel（2025）：波动率择时的动量可能只是历史上的运气。Hood（2025）：其 alpha 即趋势暴露，会在 V 形反转（如 2020-03 之后的反弹）中跑输。
  3. 超额主要来自平均暴露大于 1：2010–2026 粗算的平均暴露约 1.17（无容忍带口径）。若未来出现「低波动后突然崩盘」，杠杆期恰好碰上下跌，可能显著跑输。
  4. QLD 的费用率约 0.95%（以发行人披露为准），内含融资成本随利率上升；SGOV/BIL 的分配是否适用利息相关股息免预扣，需按 W-8BEN 实际扣缴核实。
  5. 参数（20 日、20%、1.5 倍、0.25）是事后挑选的常见值，必须冻结后做前瞻验证。

### 路线 B（次选，证据较弱）：月度趋势过滤加纳指杠杆

- **交易标的**：QLD、QQQ、SGOV。
- **规则**：每月最后一个交易日，若 QQQ 收盘高于过去 10 个月月末收盘的均值（约等于 200 日均线），则下月持有 50% QLD 加 50% QQQ（约 1.5 倍），或 100% QLD（2 倍，需单独登记）；否则 100% SGOV。下一交易会话开盘执行。
- **换手**：纳指 100 在 1986–2026 年按 10 个月均线共切换 67 次，约 1.7 次/年（本研究粗算）；每次切换 1–2 笔，佣金可以忽略。
- **依据**：Gayed & Bilello「Leverage for the Long Run」（经典 2016，近年仅有 Hsieh 2025 的间接理论支持和 Pauchlyová 2025 的弱证据）；Murray & Sammon（2026）。
- **主要风险与反证（比路线 A 更突出）**：
  1. 本研究粗算 2010–2026：不加杠杆的趋势过滤只增长 6.98 倍，买入持有为 15.74 倍；1.5 倍过滤 11.75 倍，**仍然跑输**；2 倍过滤 19.82 倍，略胜，但最大回撤 −52%（2020-02 至 03，月度信号来不及）。1986–2026 年 2 倍过滤的最大回撤为 −71%，最低净值约为本金的 50%，**触线**。
  2. Trendpilot 实盘近年大幅落后（见表 D）；Ahn 等（2026）指出趋势强度被重叠收益夸大；Suominen & Hjalmarsson（2026）指出估值极端区趋势失效；Goyal-Welch-Zafirov（2024）指出择时变量普遍失效。
  3. 结论：B 不宜单独使用。若要用，可作为路线 A 的叠加条件，例如「低于 10 个月均线时暴露上限降为 1.0」，并作为单独预登记变体与 A 比较。

### 路线 C（探索性）：不受基金分散化上限约束的超大盘市值加权

- **交易标的**：纳指 100 中按未封顶总市值排名前 N（建议 N = 8–10）的个股，余额配置 QQQ。
- **规则**：每季度在纳指 100 季度再平衡生效后的下一个交易会话，按未封顶市值重新取前 N 名并按市值加权（单股上限沿用项目 25%）。整股取整后的余额配置 QQQ。净值低于 5,000 USD 时，新进入前 N 名的股票不开仓，对应资金转入 QQQ；低于 2,500 USD 时按硬线清仓。
- **换手**：前 N 名的成员变化通常较少（未核实，需用数据统计），预计每季度 0–2 笔换股加少量调权，全年约 10–25 笔，佣金约 10–25 USD。
- **依据**：Pástor-Sikorskaya-Wang（2026）认为，基金和指数受监管上限约束被迫低配或卖出最大公司，基于约束的持有度能预测最大公司的收益，被迫卖出的股票在 2023–24 年随后六个月跑赢 2.3%；个人账户不受这一约束。Jiang-Vayanos-Zheng（2025）显示被动资金持续推升超大盘；Bessembinder（2024）显示长期收益集中于少数股票。
- **主要风险与反证**：
  1. 没有找到直接检验「未封顶前 N 名对纳指 100」扣成本后表现的学术研究，证据链是间接推断，强度为**弱**。
  2. Jiang-Vayanos-Zheng 同时意味着超大盘可能被高估，被动资金一旦逆转就会反噬；关于「高集中度之后最大股票的表现」，从业者研究结论互相矛盾（二手来源，未核实）。
  3. 本项目无摩擦诊断中，513 只等权在 2020-07 至 2025-06 跑赢 QQQ（含幸存者偏差），提示「越集中越好」并非普遍成立。
  4. 个股集中会显著提高特质波动和硬线风险；「低于本金不开新个股仓」会在回撤后把策略自动退化为 QQQ。
  5. 效应量为每季度几十 bps 级别，小账户的整股取整误差和佣金可能把它吃掉。

### 明确不建议的方向（依据见证据表）

- 公开因子、异象或 Alpha158 类打分选股：Chen-Velikov、Chen-Lopez-Lira-Zimmermann、Smart Beta Mirage，以及项目自身的失败记录。
- 免费数据加机器学习或大模型个股选择：小盘依赖、高换手、付费特征、前视与记忆偏差，以及已撤回的论文。
- 日内开盘区间突破或日内动量：只有从业者回测、需要做空和日内杠杆，独立复现称扣成本后为零，小账户佣金比例过高。
- 不加杠杆的趋势择时、主题或智能贝塔 ETF、单股杠杆 ETF：见 Trendpilot、Ben-David 等、Huang 等、Murray & Sammon。

## 五、来源清单

### 已读取摘要或正文（列入证据表）

1. Chen, A. Y., & Velikov, M. (2023). Zeroing in on the Expected Returns of Anomalies. *JFQA* 58(3), 968–1004. https://www.cambridge.org/core/journals/journal-of-financial-and-quantitative-analysis/article/zeroing-in-on-the-expected-returns-of-anomalies/945133D5A3ECEEAF466AEE91551FD225
2. Jensen, T. I., Kelly, B., & Pedersen, L. H. (2023). Is There a Replication Crisis in Finance? *JF* 78(5), 2465–2518. https://doi.org/10.1111/jofi.13249 ；NBER w28432：https://www.nber.org/papers/w28432
3. Chen, A. Y., Lopez-Lira, A., & Zimmermann, T. (2025, v7). Does Peer-Reviewed Research Help Predict Stock Returns? https://arxiv.org/abs/2212.10317
4. Bowles, B., Reed, A. V., Ringgenberg, M. C., & Thornock, J. R. (2024). Anomaly Time. *JF* 79(5), 3543–3579. https://doi.org/10.1111/jofi.13372
5. Huang, S., Song, Y., & Xiang, H. (2024). The Smart Beta Mirage. *JFQA* 59(6), 2515–2546. https://doi.org/10.1017/S0022109023000674
6. Ben-David, I., Franzoni, F., Kim, B., & Moussawi, R. (2023). Competition for Attention in the ETF Space. *RFS* 36(3). https://www.nber.org/papers/w28369
7. Greenwood, R., & Sammon, M. (2024). The Disappearing Index Effect. *JF*. https://marcosammon.com/research/
8. Avramov, D., Cheng, S., & Metzker, L. (2023). Machine Learning vs. Economic Restrictions: Evidence from Stock Return Predictability. *MS* 69(5), 2587–2619. https://doi.org/10.1287/mnsc.2022.4449
9. Azevedo, V., Hoegner, C., & Velikov, M. The Expected Returns on Machine-Learning Strategies（工作论文）. https://www.aeaweb.org/conference/2025/program/paper/TihddefB ；https://papers.ssrn.com/sol3/papers.cfm?abstract_id=4702406
10. Jensen, T. I., Kelly, B., Malamud, S., & Pedersen, L. H. (2026). Machine Learning and the Implementable Efficient Frontier. *RFS* 39(10), 3035–3078. https://doi.org/10.1093/rfs/hhag022
11. Blitz, D., Hanauer, M. X., Hoogteijling, T., & Howard, C. (2023). The Term Structure of Machine Learning Alpha. *JFDS*. https://doi.org/10.3905/jfds.2023.1.135
12. Kelly, B., Malamud, S., & Zhou, K. (2024). The Virtue of Complexity in Return Prediction. *JF* 79(1), 459–503. https://doi.org/10.1111/jofi.13298
13. Nagel, S. (2025). Seemingly Virtuous Complexity in Return Prediction. NBER w34104. https://www.nber.org/papers/w34104
14. Lopez-Lira, A., & Tang, Y. (2025, v6). Can ChatGPT Forecast Stock Price Movements? https://arxiv.org/abs/2304.07619
15. Glasserman, P., & Lin, C. (2023). Assessing Look-Ahead Bias in Stock Return Predictions Generated by GPT Sentiment Analysis. https://arxiv.org/abs/2309.17322
16. Lopez-Lira, A., Tang, Y., & Zhu, M. (2025). The Memorization Problem: Can We Trust LLMs' Economic Forecasts? https://arxiv.org/abs/2504.14765
17. He, S., Lv, L., Manela, A., & Wu, J. (2025). Chronologically Consistent Large Language Models. https://arxiv.org/abs/2502.21206
18. Kim, A., Muhn, M., & Nikolaev, V. Financial Statement Analysis with Large Language Models（v3 已撤回）. https://arxiv.org/abs/2407.17866
19. Chen, S., Green, T. C., Gulen, H., & Zhou, D. (2025). What Does ChatGPT Make of Historical Stock Returns? https://www.aeaweb.org/conference/2026/program/paper/zNrQ4Yn6
20. Lv, L. (2025). Do Sell-side Analyst Reports Have Investment Value? https://arxiv.org/abs/2502.20489
21. Yılkı, A. (2026). Supply Chain Propagation of Textual Signals. https://arxiv.org/abs/2606.29290
22. Fitchue, M., Stowe, K., & Schwartz, L. (2026). Machine Learning-Driven Strategies for NASDAQ 100 Outperformance. *J. Accounting and Finance* 26(2). https://doi.org/10.33423/jaf.v26i2.8290
23. Pástor, Ľ., Sikorskaya, T., & Wang, J. (2026). The Hidden Cost of Stock Market Concentration: When Funds Hit Regulatory Limits. NBER w35007. https://www.nber.org/papers/w35007 ；Chicago Booth Review 转述：https://www.chicagobooth.edu/review/hidden-cost-magnificent-seven
24. Jiang, H., Vayanos, D., & Zheng, L. (2025). Passive Investing and the Rise of Mega-Firms. *RFS* 38(12), 3461–3496. https://academic.oup.com/rfs/article/38/12/3461/8280528 ；NBER w28253：https://www.nber.org/papers/w28253
25. Bessembinder, H. (2024). Which U.S. Stocks Generated the Highest Long-Term Returns? SSRN. https://doi.org/10.2139/ssrn.4897069
26. Sammon, M., & Shim, J. J. (2026). Index Rebalancing and Stock Market Composition. *JFE*. https://marcosammon.com/research/
27. Ruf, J. (2023). Diversifying an Index. https://arxiv.org/abs/2311.10713
28. Goyal, A., Welch, I., & Zafirov, A. (2024). A Comprehensive 2022 Look at the Empirical Performance of Equity Premium Prediction. *RFS*. https://doi.org/10.1093/rfs/hhae044
29. Cakici, N., Fieberg, C., Metko, D., & Zaremba, A. (2024). Do Anomalies Really Predict Market Returns? New Data and New Evidence. *Review of Finance* 28(1), 1–44. https://doi.org/10.1093/rof/rfad025
30. DeMiguel, V., Martín-Utrera, A., & Uppal, R. (2024). A Multifactor Perspective on Volatility-Managed Portfolios. *JF*. https://doi.org/10.1111/jofi.13395 ；https://lbsresearch.london.edu/id/eprint/3716
31. Cederburg, S., O'Doherty, M. S., Wang, F., & Yan, X. (2020). On the Performance of Volatility-Managed Portfolios. *JFE*（经典）. https://www.lehigh.edu/~xuy219/research/COWY.pdf
32. Hood, B. T., & Raughtigan, C. (2025). Volatility Targeting Is Trendy. *JPM*. https://doi.org/10.3905/jpm.2025.1.764
33. Dai, W., Hong, X., Merton, R. C., & Pellerin, M. (2025). Forecasting and Managing Volatility: An S&P 500 Case Study. *JOIM* 23(1). https://joim.com/article/forecasting-and-managing-volatility-an-sp-500-case-study/
34. Ahn, K., Hambusch, G., & Hong, K. J. (2026). How Overlapping Returns Inflate Measured Time Series Momentum. *JRFM* 19(1). https://doi.org/10.3390/jrfm19010046
35. Suominen, M., & Hjalmarsson, E. (2026). Boundaries of Time-Series Momentum. *Financial Management*. https://doi.org/10.1111/fima.70055
36. Hsieh, C.-H., Chang, J.-R., & Chen, H. H. (2025). Compounding Effects in Leveraged ETFs: Beyond the Volatility Drag Paradigm. https://arxiv.org/abs/2504.20116
37. Murray, C., & Sammon, M. (2026). The Costs and Benefits of Leveraged ETFs. https://marcosammon.com/research/ ；https://doi.org/10.2139/ssrn.7133021
38. Pauchlyová, M. (2025). Leveraged ETFs in Asset Allocation: Opportunity or Trap?（Quantpedia）. https://quantpedia.com/leveraged-etfs-in-asset-allocation-opportunity-or-trap/
39. Zarattini, C., & Aziz, A. (2023). Can Day Trading Really Be Profitable? https://papers.ssrn.com/abstract=4416622 ；独立复现（二手来源）：https://www.mql5.com/en/blogs/post/776235
40. Zarattini, C., Aziz, A., & Barbon, A. (2024/2025). Beat the Market: An Effective Intraday Momentum Strategy for S&P500 ETF (SPY). SFI 24-97. https://www.sfi.ch/de/publications/n-24-97-beat-the-market-an-effective-intraday-momentum-strategy-for-s-p500-etf-spy
41. Zarattini, C., Pagani, A., & Wilcox, C. (2025). Does Trend Following Still Work on Stocks? https://concretumgroup.com/does-trend-following-still-work-on-stocks/
42. Zarattini, C., & Antonacci, G. (2024). A Century of Profitable Industry Trends. https://cmtassociation.org/wp-content/uploads/2026/02/Dow-Winner-A-Century-of-Profitable-Trends.pdf
43. FRED：NASDAQNDXTRND1（https://fred.stlouisfed.org/series/NASDAQNDXTRND1 ）、NASDAQ100（https://fred.stlouisfed.org/series/NASDAQ100 ）、DTB3（https://fred.stlouisfed.org/series/DTB3 ）。本研究粗算的数据截至 2026-10-26；Trendpilot 序列在 FRED 上止于 2025-10-27。
44. PDT 规则变化（二手来源）：https://international.schwab.com/story/sec-approves-scrapping-25000-day-trader-minimum ；https://us.etrade.com/knowledge/library/margin/pattern-day-trading-rule-change

### 仅见题录、未读到摘要（未纳入结论，供后续精读）

- Bessembinder, H. (2026). Volatility and Returns to Leveraged ETFs. https://doi.org/10.2139/ssrn.7376118
- Angelidis, T., & Tessaromatis, N. (2023). The Disappearing Profitability of Volatility-Managed Equity Factors. *J. Financial Markets*. https://doi.org/10.1016/j.finmar.2023.100857
- Xu, X. (2024). Improving Volatility-Managed Portfolios in Real Time. *Critical Finance Review*. https://doi.org/10.1108/cfr-03-2023-2491
- Moskowitz, T. J., Sabbatucci, R., Tamoni, A., & Uhl, B. (2025). Nonlinear Time Series Momentum. https://doi.org/10.2139/ssrn.5933974
- Lo, C.-S. (2025). Can NASDAQ-100 Derivatives ETF Portfolio Beat QQQ? https://doi.org/10.2139/ssrn.5288772
- Nakamura, A. (2026). Leverage, De-risking, and Sequence Risk in Nasdaq-100 Retirement Spending. https://doi.org/10.2139/ssrn.7549160
- Trainor, W. J. (2025/2026). Beyond Volatility Decay: Correcting Relative Expected Return Estimates for Leveraged ETFs（*JRFM*）；Weekly and Monthly and Quarterly Leveraged ETFs, Oh My!（*J. Beta Investment Strategies*）. https://doi.org/10.3905/jbis.2026.004
- Chen, Y., Kelly, B., & Xiu, D. Expected Returns and Large Language Models（大盘子样本结果未核实）。
