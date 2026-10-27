# SPY 股票池与每周研究漏斗的数据来源

核查日期：2026-10-26。此次只读取公开资料和 SPY 官方持仓文件，没有读取凭据或访问券商账户。实现可使用 SPY 当前持仓建立研究关注名单；当前成分回溯、价格评分和完整交易回测的证据范围必须分别记录。

## 官方持仓入口与本次实测

[State Street SPY 产品页](https://www.ssga.com/us/en/individual/etfs/state-street-spdr-sp-500-etf-trust-spy)的 “Download All Holdings: Daily” 指向[官方 XLSX 文件](https://www.ssga.com/library-content/products/fund-data/etfs/us/holdings-daily-us-en-spy.xlsx)。直接 HTTP GET 已返回 200，内容类型为 XLSX，大小 54,375 字节。页面将下载入口标为每日数据，但没有在该页面承诺具体更新时刻。

本次下载文件中的持仓日期为 **2026-10-22**，不是采集日期 10 月 26 日，也不是最近行情截点 10 月 23 日。HTTP `Last-Modified` 为 2026-10-24 05:25:49 UTC，不能替代工作簿中的持仓日期。产品页也显示 10 月 22 日的持仓信息。因此应分别保存 `holdings_as_of`、`price_as_of`、`captured_at`；不能把持仓文件改标为周五数据。[持仓原文](https://www.ssga.com/library-content/products/fund-data/etfs/us/holdings-daily-us-en-spy.xlsx)

本次来源和解析检查位于 Git 忽略的 `reports/spy-universe-research-20261026-0515/`：

- `holdings-source.parquet`：原始 URL、最终 URL、HTTP 状态和响应头、实际采集时刻、原始 XLSX 字节及 SHA256。
- `holdings-inspection.parquet`：类型明确的逐行字段；原始权重百分数与比例分别保留，金额或股数不经浮点转换。
- `holdings-inspection-initial.parquet`：保留初次将非现金行归为同一类的解析结果；后续检查将异常代码单列，原始文件不变。
- `inspection-checks.parquet`、`artifacts.parquet`：统计、限制及产物清单。

原始工作簿 SHA256 为 `df96332ee05f95e11cdfb3a69991b162bfb349564e91010333840a35373a708a`。

## 可实现的解析契约

工作簿只有 `holdings` 工作表，对应 `xl/worksheets/sheet1.xml`；字符串使用 `xl/sharedStrings.xml`。检查基金身份后定位标题行，不应把空行、页尾说明或整个工作表行数当作证券数量。本次实际位置如下：[原始工作簿](https://www.ssga.com/library-content/products/fund-data/etfs/us/holdings-daily-us-en-spy.xlsx)

| 位置 | 本次内容或处理 |
| --- | --- |
| `A2` / `B2` | `Ticker Symbol:` / `SPY` |
| `A3` / `B3` | `Holdings:` / `As of 22-Oct-2026` |
| 第 5 行 `A:H` | `Name`, `Ticker`, `Identifier`, `SEDOL`, `Weight`, `Sector`, `Shares Held`, `Local Currency` |
| 第 6–510 行 | 505 行持仓记录；后续还有空行和说明 |
| `Weight` | 百分数单位；例如 `7.776316` 表示 7.776316%，比例为 `0.07776316` |
| `Shares Held` | 有科学计数法；按十进制字符串读取，不先转浮点 |
| `Identifier`、`SEDOL` | 保留字符串和前导零，不作为数值 |

筛选边界来自本次实际文件：

| 类别 | 数量与观察 |
| --- | --- |
| 普通股票代码 | 503 个，代码没有重复 |
| 现金 | 1 行，`US DOLLAR` / `-` / `999USDZ92`，原始权重 0.296711% |
| 不支持的代码 | 1 行，`TPG INC` / `2602335D` / `436CVR021`，原始权重 0.000003%；不能直接作为普通股票请求或悄悄改成 `TPG` |
| 点号代码 | `BRK.B`、`BF.B`；保留供应方原值，不套用其他平台的连字符写法 |
| 多股类 | `GOOGL` / `GOOG`、`FOXA` / `FOX`、`NWSA` / `NWS`；证券身份应各自保留，最终名单可另外控制集中度 |
| 行业 | **全部 505 行为 `-`**；本文件不能提供逐股行业分类 |
| 币种 | 本次全部为 USD；项目继续遵守固定 USD 约定 |

普通股票识别在本次检查中使用字母开头、允许点号股类的保守规则；这不是 Alpaca 全部证券类型的合法代码定义。原始 505 行都要保留，并把现金、不支持代码和后续缺行情证券列入排除表。

工作簿全部持仓权重合计 **100.220262%**，普通股票为 **99.923548%**。这与严格的 100% 等式不符，原文件没有逐行给出其净额调整说明；不能静默归一化后声称等同原披露权重。漏斗只需要成员身份时，可保留原值及差异提示，不将它用作配置比例。

## Alpaca 历史行情接口

官方批量入口是 `GET https://data.alpaca.markets/v2/stocks/bars`。`symbols` 为逗号分隔列表；返回结果先按证券代码、再按时间排序。`limit` 为每页总条数，范围 1–10,000，**不是每个证券的条数**。响应不足 `limit` 也不能表示结束，必须遍历 `next_page_token`。批次应核对全部请求证券，并记录空返回、缺会话和重复会话，不能用前向填充掩盖缺失。[Historical bars](https://docs.alpaca.markets/us/reference/stockbars)

请求应冻结 `timeframe=1Day`、`feed=sip`、`sort=asc`、显式起止时间和 `asof`。官方定义 `asof` 为识别证券实体和关联旧代码的日期，**不是历史可知时间或历史版本截点**。当前代码可返回其旧名称下的历史，但映射在更名当天还可能不可用；不能把该参数解释为消除了幸存者偏差。[历史代码映射说明](https://docs.alpaca.markets/us/docs/market-data-faq)

Alpaca 的 Basic 计划当前列明：历史始于 2016 年，历史调用 200 次/分钟，最新 15 分钟受限；免费实时覆盖仅 IEX。官方 FAQ 进一步说明，无订阅查询历史 SIP 时，`end` 必须至少早于当前 15 分钟。因此适合在完整交易日结束后做周度历史研究，不能把它表述为免费实时全市场报价。[计划说明](https://docs.alpaca.markets/us/docs/about-market-data-api)、[SIP 历史权限](https://docs.alpaca.markets/us/docs/market-data-faq)

本次没有调用 Alpaca 账户或带凭据的行情接口；批量股票的实际可读性、覆盖率和特殊代码仍需主线按真实响应验证。官方参数页只定义逗号分隔列表，没有给出适用于全部资产的股票代码正则。历史上的 [Alpaca 支持答复](https://forum.alpaca.markets/t/how-to-pull-quotes-for-berkshire-hattaway/7303)使用 `BRK.A` / `BRK.B`；它可作点号保留的参考，不能代替当前响应核验。

## 调整口径与准入边界

官方定义 `raw` 为不调整，`split` 对正向和反向拆股调整价格及成交量，`dividend` 对现金分红调整价格，`spin-off` 对分拆调整价格，`all` 组合上述调整。[参数定义](https://docs.alpaca.markets/us/reference/stockbars)

首版漏斗若使用 `split` 价格计算动量、波动和回撤，结果是**供应方拆股调整后的价格指标**，不包含现金分红再投资，也不覆盖分拆导致的价格变化。流动性可单独使用 `raw` 收盘价乘原始成交量的日均代理值；该值不是实际逐笔成交金额。不能将 raw 股数与 split 价格混乘；不能从已舍入调整价反算 Decimal 账簿原价。现有真实拆股核验及舍入证据见[公司行动核查](alpaca-corporate-action-coverage-20261026.md)。

研究关注漏斗可以明确保留“现金分红、复杂公司行动和交易策略尚待验证”的状态；**它不能放宽既有 `backtest` / `decide` 的执行准入，也不能把关注名单写成已通过成本回测的买入信号**。分数是冻结规则下的相对研究优先级，不是盈利概率。原始公司行动缺口、失败记录和已有账户继续保留。

## 每周运行应保留的证据

以下是依据本次数据事实给出的实现建议，并非供应方对策略有效性的承诺：

1. 每周保存新的官方持仓字节、持仓日期、下载时刻、行情截点和代码版本。持仓日期过旧时明确提示或停止，不回填日期。
2. 对当前股票池做历史价格筛选时，保留 `current_sample` / `exploratory`。当前持仓不能证明这些股票在过去已属于 SPY；每周逐步积累的快照也不能补造此前成员历史。
3. 第一轮保留全量成员及所有淘汰理由；第二轮保留分项原始指标、标准化规则、权重、综合评分、相关性去重理由和最终名单。不足 3 只合格时不凑数。
4. 当前缺乏逐股行业数据，首版不得宣称已满足行业配额；收益相关性约束也不能等同于已验证的行业分散。
5. 同分采用固定次序；数据不足不得当作低风险或零风险。每周评分变化应能区分行情变化、成员变化和规则变更。
6. 原始输入、评分表和名单使用 typed Parquet/Zstandard，规则用 TOML。历史运行不覆盖；周度关注名单不直接下单或重置账户。
