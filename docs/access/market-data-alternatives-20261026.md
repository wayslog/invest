# 美股与 ETF 替代数据源比较

核查日期：2026-10-26，Asia/Shanghai。范围是私人日频因子研究、现金回测及后续盘中行情；本次只读官方资料、官方 SDK 和项目历史记录，未登录数据账户、读取凭据、试读账户 API、注册或购买。以下价格为美元；除 FMP 明示年付折算、Twelve Data 明示套餐起价外，列出的价格为按月价，包括 Massive Starter 29/月与 EODHD EOD Historical 19.99/月。套餐入口价只覆盖所列权益，不是所有产品总价。公开说明不是本账户准入或数据完整性验收。

**优先恢复验证 Alpaca 免费历史 SIP 和企业行动；Tiingo 作为免费日频候选；确实缺少长历史事件或证券身份时，再考虑 Massive Starter。** 全市场实时行情与历史研究分开采购。未找到一项免费服务能够有证据地同时保证原始 OHLCV、全部企业行动、完整历史证券池、当时可知版本及综合实时报价。

本报告不改变 [现行来源政策](../data-sources.md)：IBKR 仍是权威外部来源，账户、订单、成交、费用和券商现金流水继续取自 IBKR。替代源应独立标识为研究或参考数据；正式采用时再明确政策边界，不能重标为 IBKR、覆盖旧记录或重置观察账户。

## 比较口径

用户于 2026-10-26 确认只研究美股，统一按 USD 计算。供应方币种字段缺失不作为本项目准入阻塞，不要求额外币种关联；以下涉及币种的供应方描述仅保留接口能力事实。规范化研究数据采用[固定 USD 约定](../data.md#研究币种固定-usd)，原始响应保持不变。

现金回测需要当时成交口径的 OHLC、按股原始成交量、原始每股分红金额、除息日与支付日、拆股/合股比率，并验证指定证券和区间的完整覆盖；金额统一按 USD 计算。复权行情适合某些收益研究，但不能替代这些现金和持仓事件。股票横截面研究还需要历史证券身份、退市证券和当时股票池；有历史行情或 `active=false` 参数不等于有完整历史指数成分。

“覆盖所有美股代码”与“覆盖全市场成交及 NBBO”是两件事。下表把实时 feed、延迟和 EOD 分开；未确认的能力写成待验证，不写成技术上不可用。

## 候选初筛

| 来源 | 持续免费与历史边界 | 付费与实时 feed | 本项目关键能力及限制 |
| --- | --- | --- | --- |
| **Alpaca** | Basic 免费；美股/ETF 历史自 2016 年，200 次/分钟；历史 SIP 排除最近 15 分钟；实时 IEX、WS 30 个证券。 | Algo Trader Plus **99/月**：综合美股实时行情、WS 不限证券，官方 API 文档列历史请求 10,000 次/分钟。 | raw/拆股/分红调整可选；免费套餐明确包含 Corporate Actions。支付日可空，公告时间需另核；事件币种缺失按项目 USD 约定处理，无完整历史股票池承诺。**首选恢复只读验证。** [套餐](https://docs.alpaca.markets/us/docs/about-market-data-api)、[免费企业行动](https://alpaca.markets/data)、[Bars](https://docs.alpaca.markets/us/reference/stockbars) |
| **Tiingo** | Starter 免费；500 个不同证券/月、50 次/小时、1,000 次/日、1 GB/月；价格页列 30 年以上产品历史，美股/ETF 逐证券核实。 | Power **30/月**扩大额度。IEX TOPS 与衍生参考 feed 有区别；另有免费 Equity Realtime **Beta** 多场所衍生指标，均不能默认当作 SIP/NBBO。 | EOD 有 raw/adjusted OHLCV、`divCash`、`splitFactor`。详细分红文档准入表述冲突，支付日可空，未列币种。**日频价量候选，尚不是完整现金输入。** [价格](https://www.tiingo.com/account/billing/pricing)、[EOD](https://www.tiingo.com/documentation/end-of-day)、[实时 Beta](https://www.tiingo.com/documentation/equity-realtime-stock-data) |
| **Massive，原 Polygon.io** | Basic 免费，5 次/分钟，最近 **2 年** EOD 可用数据；包含企业行动和参考数据；没有免费实时 WS/trades/quotes。 | Starter **29/月**：5 年行情、15 分钟延迟、无限请求；Developer **79/月**：10 年、含 trades；Advanced **199/月**：20 年以上、实时 trades/quotes/NBBO。 | 原价聚合可选；新分红/拆股接口明确免费 2 年、Starter 起全部事件历史。分红币种、原始金额、支付日均有但可空；ticker 支持历史日期和退市状态。**小额付费补缺优先候选。** [套餐](https://massive.com/stocks)、[分红](https://massive.com/docs/rest/stocks/corporate-actions/dividends)、[身份](https://massive.com/docs/rest/stocks/tickers/all-tickers) |
| **EODHD** | Sandbox 持续免费 **20 次/日、20 次/分钟、1 年历史**；另赠 500 次属于欢迎额度。价格表列 ETF、分红/拆股，不能沿用“免费只有少数美股代码”的旧印象。 | EOD Historical **19.99/月**、EOD+Intraday **29.99/月**；付费 100,000 次/日、1,000 次/分钟。Fundamentals **59.99/月**；完整 SIP/NBBO 权益本轮未核定。 | 原始 OHLC，但 **volume 已做拆股调整**；分红 JSON 有原始金额、币种和支付日，支付日仍可空。适合事件补充，不能把其日线直接标成全字段 raw。 [价格](https://eodhd.com/pricing)、[行情口径](https://eodhd.com/financial-apis/api-for-historical-data-and-volumes)、[事件](https://eodhd.com/financial-apis/api-splits-dividends) |
| **Databento** | **125 美元新户额度是试用信用额，非持续免费**。历史按数据集、schema、区间计量收费，需用估价接口核实际工作集。 | 实时美股需订阅；企业行动/证券主档另有参考数据订阅。通用价格页默认展示 CME，不能拿其价格当美股与参考数据总价；本轮未取得可比总报价。 | 股票/ETF tick、BBO、盘口和 OHLCV；直接交易所 feed、聚合 feed 须按 dataset 区分。参考产品明确有 PIT 企业行动、PIT 上市/退市身份，优于只提供当前快照的契约；历史长度各数据集不同。**以后做严格事件/PIT 或微观结构时再评估。** [收费](https://databento.com/pricing)、[参考计费](https://databento.com/docs/portal/billing)、[企业行动](https://databento.com/corporate-actions)、[证券主档](https://databento.com/docs/datasets/security-master) |
| **Intrinio** | 官方为 **免费试用**，本轮未见持续免费全量研究档。 | 当前 Individual **150/月**：EOD、基本面等；其 EquitiesEdge 是 FMV 参考价格，另含 15 分钟延迟 Cboe One，不能据“实时”字样当作实时 SIP。 | EOD 列 50 年以上、raw/adjusted、成交量及拆股比率；公司行动详细支付日/币种和套餐映射未完成核实。基本面产品较齐，但当前两个 ETF 的需求不值得先承担此成本。 [当前套餐及各 feed 定义](https://intrinio.com/pricing) |
| **Financial Modeling Prep** | Basic **250 次/日、500 MB/30 日**；有 EOD，但端点和证券受限，不能推定 SPY/XLF 免费可读。 | Starter **19/月等值、年付**，5 年；Premium **49/月等值、年付**，30 年以上；月付结算价本轮未确认。 | 明确有 non-split-adjusted OHLCV 端点、分红除息/公告/登记/支付日；当前免费权限须逐端点试读。财报/退市接口存在不等于 PIT 历史完整；综合实时 feed 许可未核定。 [价格](https://site.financialmodelingprep.com/developer/docs/pricing)、[原价](https://site.financialmodelingprep.com/developer/docs/stable/historical-price-eod-non-split-adjusted)、[分红](https://site.financialmodelingprep.com/developer/docs/stable/dividends-company) |
| **Alpha Vantage** | 免费 **25 次/日**；普通日线免费 compact 仅最近 100 点，完整 25 年以上历史需 Premium；Daily Adjusted 也标 Premium。股票/ETF 可查询。 | 实时和 15 分钟延迟美股需 Premium 及额外 entitlement 流程；本次官方价格选择器未显示可核定金额，不采用第三方旧价。 | 有独立 DIVIDENDS、SPLITS、财报和上市/退市接口；独立事件不是“只能从复权收盘价猜分红”。长期日频历史免费限制较大，当前优先级低于 Alpaca/Tiingo。 [配额与授权](https://www.alphavantage.co/premium/)、[端点及历史限制](https://www.alphavantage.co/documentation/) |
| **Twelve Data** | Basic 免费 **8 API credits/分钟、800/日**；8 WS credits 标为 **trial**。官方明确 Basic 的历史/EOD 次交易日美东午夜后有全市场成交量。 | Grow **29/月起**，分红接口从 Grow 起；Pro **99/月起**。默认实时覆盖所有上市代码，但仅约 **5% 市场成交量**；综合全市场 feed 另谈授权。 | 适合免费 EOD、价量探索；不能把默认实时当 SIP/NBBO。raw volume、详细支付日/币种和 ETF 事件权益本轮未逐项验收；请求数应按 credit 权重计算。 [套餐](https://twelvedata.com/pricing)、[美股 feed 定义](https://support.twelvedata.com/en/articles/9935903-us-equities-market-data)、[ETF 分红准入实例](https://twelvedata.com/markets/109877/etf/nyse/dgro/historical-data/dividends) |
| **SEC EDGAR** | 公共 submissions/XBRL API 无 Key、免费；XBRL 自 2009 年开始强制，早期内容覆盖与结构不同。 | 无需数据订阅；只作为财报与申报原始证据。 | 可构建按申报时点使用的财报因子；不是行情、完整股票池、历史指数成分或 ETF 现金分配事件库。`frames` 取最近申报事实，不能直接当历史当时可知版本。 [官方 API](https://www.sec.gov/search-filings/edgar-application-programming-interfaces) |
| **Yahoo / yfinance** | 开源客户端可免费使用，但没有项目所需的稳定供数、完整覆盖和服务级别承诺。 | 不是购买正式市场数据授权的替代方式；不能从开源许可证推导数据使用权。 | 维护者明确非 Yahoo 官方认可产品、用于研究教育并提示个人用途。可作人工探索对照；当前不选作现金账本或实时风控主输入。 [维护者说明](https://github.com/ranaroussi/yfinance/blob/main/README.md) |

上述各家的产品历史长度都是上限或产品描述，均不是指定证券自某日起每个字段齐全的证明。ETF 价格覆盖也不代表 ETF 资本利得分配、返还资本、due-bill 和其他复杂事件已经被当前引擎支持。

## 三家优先深入

### Alpaca：已有工程与历史证据，免费范围比“只有 IEX”更大

当前官方套餐表确认历史与实时是两个权限维度：Basic 可请求最近 15 分钟之前的历史 SIP，实时则为 IEX；SIP 基于 CTA/UTP 综合数据。请求应显式指定 `feed=sip`、`adjustment=raw`，保存 feed、时段、单位与批次，禁止失败后静默改成 IEX。[当前 API 套餐](https://docs.alpaca.markets/us/docs/about-market-data-api)、[历史 Bars 参数](https://docs.alpaca.markets/us/reference/stockbars)

[当前市场数据价格页](https://alpaca.markets/data) 的免费和付费两列均包含 Corporate Actions；这是公开权益证据。具体数据端点是 `GET /v1/corporate-actions`，不是券商账户流水，也不应与另一套 corporate action announcement API 混用。它支持现金分红、正/反向拆股、名称变更、合并等事件。[当前事件 API](https://docs.alpaca.markets/us/reference/corporateactions-1)

关键查询与字段约束：

- `start`/`end` 是包含边界的 **process_date 区间**。已除息而尚未处理/支付的事件可能落在未来 process_date；截至今天查询会漏取，不能把空结果解释成没有分红。
- `data_quality=complete` 默认排除“**不完整且尚未处理**”记录；已处理的记录即使仍缺字段也会返回。`all` 可以用于发现早期不完整记录，不能直接放行记账。官方明确不保证事件创建及时性，宣布后可能延迟出现。
- 官方 SDK `CashDividend` 有 `rate`、`ex_date`、`process_date`；`record_date`、`payable_date` 可空。当前模型没有 `declaration_date` 或 `currency`；原始响应按实际返回保存，公告时间仍需核实，币种缺失按项目固定 USD 约定处理。
- SDK 将 `rate` 定义为 `float`，这不是供应方保证六位小数的契约。精确账务应保留原始数值文本，使用 Decimal 并拒绝静默截断；不能经过 SDK 浮点转换后声称仍保留原始精度。

查询规则见 [API 文档](https://docs.alpaca.markets/us/reference/corporateactions-1)，字段与类型见 [官方 SDK 模型](https://github.com/alpacahq/alpaca-py/blob/master/alpaca/data/models/corporate_actions.py)。

项目 [旧验收](../data-sources.md) 记录了 2026-10-19/20 的 Basic 实际成功，以及修复 `actions_through` 后，SPY/XLF 2021-01-04 至 2026-10-19 各 1,455 条 SIP 日线和 23 笔分红通过发行方核对。它也记录了早期支付日缺失、七位分红精度和 XLK due-bill 拒绝。**这些是过去的明确范围，不能替代当前权限和新事件验收。** 未来 120 天的处理日期窗口是项目的采集策略，不是供应方保证，也不是历史信息可得时间。

### Tiingo：免费日频直接，详细事件与新实时产品须拆开看

EOD 的 `volume` 表示股数，同时提供 `adjVolume`；`divCash` 在除息日记录，不能当支付日现金。详细事件文档一方面要求 Beta-enabled/enterprise，另一方面说所有 EOD entitlement 包含，必须试读确认；支付日等允许空，详细分红历史从 2023 年起。相关边界见 [既有核查](tiingo-coverage.md)、[EOD 字段](https://www.tiingo.com/documentation/end-of-day)、[详细分红](https://www.tiingo.com/documentation/corporate-actions/dividends)、[分红产品历史](https://www.tiingo.com/products/corporate-actions/stock-etf-mutual-fund-dividend-api)。

最新文档已有免费 **Equity Realtime Beta**，汇合交易所、ATS 和 OTC 场所，提供 REST/WS 参考价与流动性指标。`tngoLast` 可能是实际 last，也可能是算法选取的 mid；`lqBidPrice`/`lqAskPrice` 属于流动性指标，不能直接冠以 NBBO。文档仍建议生产场景使用 IEX 端点。IEX 完整 TOPS 自 2025-02-01 起要求交易所协议；不签协议的衍生参考 feed 是另一产品。[Equity Realtime 文档](https://www.tiingo.com/documentation/equity-realtime-stock-data)、[IEX 文档](https://www.tiingo.com/documentation/iex)

### Massive：用少量订阅费补事件和历史身份，先试免费窗口

Polygon.io 已在 **2025-10-30** 更名为 Massive，并提供新域名和 SDK；不把旧域名的长期兼容性当承诺。[官方更名公告](https://massive.com/blog/polygon-is-now-massive)

当前新接口为 `/stocks/v1/dividends` 和 `/stocks/v1/splits`，目录将原先接口标为 Deprecated。分红有原始 `cash_amount`、`currency`、`ex_dividend_date`、`pay_date`、公告/登记日期，以及另列的 `split_adjusted_cash_amount`；这些重要字段仍标 optional，必须逐条检查。Basic 仅 2 年，Starter 起开放产品全部事件历史；这与 Starter 只有 5 年行情不矛盾。[分红契约](https://massive.com/docs/rest/stocks/corporate-actions/dividends)、[拆股契约](https://massive.com/docs/rest/stocks/corporate-actions/splits)

`/v3/reference/tickers` 有 `date`、`active`、FIGI、`delisted_utc`，可按历史日期枚举证券，明显比用今天仍存续的 ticker 清单回填更适合研究。**历史日期查询不自动证明当时发布版本、完整退市收益或历史指数成分。** 先验证改名/退市样本和分页完整性，再决定能否用于选股。[证券身份契约](https://massive.com/docs/rest/stocks/tickers/all-tickers)

EODHD 是此路线的较便宜候补：分红 JSON `unadjustedValue` 才是当时每股金额，`value` 已按后来拆股调整，`currency` 明确为支付币种；公告/登记/支付日可空。它能补事件，但基础日线的拆股复权成交量需要明确处理，不能直接导入原始成交量契约。[事件字段](https://eodhd.com/financial-apis/api-splits-dividends)、[成交量定义](https://eodhd.com/financial-apis/api-for-historical-data-and-volumes)

## 基本面、PIT 和可维护性

后续股票财报因子可先用 SEC：保留原申报 accession、期间、单位、申报及接受时间、修订版本，再按研究截点选事实。SEC `companyfacts` 汇集多个申报，而 `frames` 使用最近申报事实；不能按财报期末把后来修订值回填到过去。此处是根据 API 结构作出的工程建议，仍需单独实现和验收。SEC 不收 API Key，自动下载需遵守公开访问规则。[数据 API](https://www.sec.gov/search-filings/edgar-application-programming-interfaces)、[开发者 FAQ](https://www.sec.gov/about/webmaster-frequently-asked-questions)

本轮不做“口碑排名”。可复查的成熟度证据是 Alpaca、Massive、Databento 均有官方 Python 客户端、示例和公开开发记录：[alpaca-py](https://github.com/alpacahq/alpaca-py)、[Massive client-python](https://github.com/massive-com/client-python)、[databento-python](https://github.com/databento/databento-python)。这支持可集成、可追踪问题的判断，**不证明行情无错或 uptime 更高**。对本项目更有分量的是 Alpaca 既有真实发行方对照及失败样例；其余候选尚无本项目实测。未对各家相同时间窗的事故率或覆盖错误率做可比抽样，不引用厂商客户 Logo、星标数或营销评价代替数据质量证据。

## 建议的三条路线与最小试读

| 路线 | 组合与新增订阅费 | 下一步可验收结果 |
| --- | --- | --- |
| **零新增费用，先推进小规模日频研究** | Alpaca Basic 历史 SIP+事件；Tiingo Starter 作为独立价量对照候选；财报阶段加 SEC。 | 先用现有 Alpaca 只读权限重取 SPY/XLF 的一个已验收年度和最近已除息未支付区间，核验 raw OHLCV、支付日、全分页、查询上界和发行方分配表，金额统一按 USD 计算。通过多少证券/年份就只开放多少；不以“有免费接口”宣称全量就绪。 |
| **少量付费，补已证实缺口** | 先试 Massive Basic 最近 2 年事件/身份，字段和覆盖通过后再考虑 Starter **29/月**；保留 Alpaca/Tiingo 的较长行情，独立记录来源。EODHD **19.99/月**是事件候补。 | 对 SPY/XLF 的分红及一个拆股、合股、改名、退市样本检查原始金额和支付日期，金额统一按 USD 计算。付款理由应是实测得到的历史深度/事件缺口，而非重复购买已有免费日线。来源组合需要显式关联与对账，不做静默拼接。 |
| **需要综合实时行情时** | 先完成 IBKR 所需 feed 的实时权限验收；若研究系统需要独立 REST/WS 综合源，Alpaca Plus **99/月**可优先试，Massive Advanced **199/月**适用于还需要更深历史 trades/quotes 的场景。 | 检查实际 feed、交易所/接收时间、bid/ask 与 size、断线重连、过期报价与异常价拦截；免费 IEX、Twelve 默认约 5% feed、Tiingo 衍生参考价不替代综合实时验收。IBKR 仍提供唯一券商账户和执行事实。 |

试读还应包含普通日、半日市、拆股前后及跨年支付分红；将金额、单位、交易日时区、复权口径、查询参数、分页、抓取时间和原始响应来源保存在类型明确的 Parquet/Zstandard 中。缺失支付日或不支持的事件应隔离，不填默认日期；空结果、最后一页或 HTTP 200 都不能单独证明“该区间没有事件”。供应方声明的覆盖、独立发行方核对和本项目实测应分别保留。
