# Alpaca 现有凭据只读验证

核查日期：2026-10-26（Asia/Shanghai）。**SPY/XLF 的指定历史行情、现金分红金额和支付日已实测通过；公告时间与历史修订版本仍缺失，拆股空结果也不能独立证明完整无事件。** 因此它可以补充当前日频研究所需的主要输入，但不能据此宣称 Alpaca 单源已补齐全部正式准入要求。

用户在本次核查后明确：只研究美股，统一按 USD 计算。按[研究币种约定](../data.md#研究币种固定-usd)，事件币种未返回不再列为缺口或准入阻塞，也不要求额外关联发行方币种；原始采集字段保持不变。

本次复用同一用户已有本地交易项目的 Alpaca 配置，密钥只进入进程内存和 `data.alpaca.markets` 的认证头；没有读取交易账户个人资料或账单，未独立确认与 invest 旧验收账户相同。当前凭据能访问下述接口，28 次请求的限额头均为 200；这与[官方 Basic 免费权限](https://docs.alpaca.markets/us/docs/about-market-data-api)一致，但不构成当前账户套餐或收费状态的证明。没有购买、升级或修改订阅。

## 实际采集与结果

Alpaca 请求发生于 **2026-10-26 03:44:30—03:45:03 UTC**，共 28 次 GET，全部 HTTP 200。范围为 SPY/XLF、2021-01-04 至最近完成会话 2026-10-23；`feed=sip`、`adjustment=raw`、`currency=USD` 显式传入。仅访问 `/v2/stocks/bars` 与 `/v1/corporate-actions`，另重新捕获一次 State Street 官方历史分红表。

| 验证项 | SPY | XLF | 结论 |
| --- | --- | --- | --- |
| 原始 SIP 日线 | 1,459 条 | 1,459 条 | 与 XNYS 会话集合一致，无缺日、重复、越界或 OHLC 结构错误 |
| 2024 年子集 | 252 条 | 252 条 | 覆盖既有首轮年度 |
| 2025-10-24—2026-10-23 子集 | 251 条 | 251 条 | 覆盖当前 IBKR 一年采集窗口 |
| 区间内现金分红 | 23 笔 | 23 笔 | 除息日集合、金额和支付日与本次发行方捕获逐笔一致 |
| 支付日 | 23/23 非空 | 23/23 非空 | 均不早于除息日；SPY 有 5 笔跨年支付、1 笔当前未支付 |
| 事件 `currency` | 未返回 | 未返回 | 研究按项目约定使用 USD，原始缺失字段不阻塞准入 |
| 事件 `declaration_date` | 未返回 | 未返回 | 公告时间仍未取得 |
| 正向/反向拆股查询 | 空 | 空 | 只证明指定参数下返回空，不证明服务覆盖或全历史无拆股 |

全部日线时间戳对应纽约 00:00，UTC 小时随夏令时为 04/05；成交量为非负整数。`raw` 的价格、成交量和币种参数依据[当前 Bars 契约](https://docs.alpaca.markets/us/reference/stockbars)解释，没有把日线视为常规时段分钟线的简单汇总，也未重新验证交易级成交量全量覆盖。09-17 至 09-24 的小窗口另测 `split` 与 `all`：`split` 与 raw 相同，`all` 在分红前日期有变化。这验证了该样本的调整参数行为，不推广为拆股正例验收。

原始响应先完整封装，再用 Decimal 解析数值；未经过 SDK float。46 笔区间内分红均符合现有六位小数契约，没有截断或舍入。事件 CUSIP 为 SPY `78462F103`、XLF `81369Y605`，与发行方身份匹配。

## 分页、待支付事件与独立核对

行情 raw 查询完整遍历 3 页；企业行动 `complete`、`all` 各遍历 10 页，每页上限故意设为 5。两组各取得 47 条且组内事件 ID 无重复、内容无冲突；其中 SPY 2020-12-18 除息、2021 年处理的 1 条在研究范围外，保留原始记录但排除于上述 46 笔。两种质量参数在此次样本结果相同，不能用于证明不完整事件在其他样本中的过滤行为。

企业行动查询按 `process_date` 使用 2021-01-01 至 **2027-02-23** 的范围，即采集日后 120 天。专门对 SPY 做截止日期对照：从 2026-09-01 查到当天 2026-10-26 返回空；扩至上述未来上界后取得：

| 除息日 | 金额 | 支付日 / 处理日 | 当前含义 |
| --- | --- | --- | --- |
| 2026-09-18 | 1.888834 | 2026-10-30 | 已除息、尚未支付；可核对应收，不能提前记为现金 |

这重现了现有 `actions_through` 处理日期边界，原因与免费/付费权限无关。未来日期是查询范围，不是信息可得日期；本次所有返回只证明此次采集时已可见。Alpaca [公司行动文档](https://docs.alpaca.markets/us/reference/corporateactions-1)也不保证事件宣布后立即创建，默认 `complete` 仍可能返回已处理但缺字段的记录。

本次从[State Street 历史分红表](https://www.ssga.com/library-content/products/fund-data/etfs/us/spdr-etf-historical-distributions.xlsx)重新捕获原始文件，封装为 Parquet，与两只 ETF 的全部 46 笔区间内分红逐笔核对，金额、除息日、支付日及事件集合均一致。原表保留在证据目录；没有覆盖以前的发行方捕获。

此前另查得的币种参考保留为研究记录：发行方[分配页面](https://www.ssga.com/us/en/individual/resources/documents/etf-dividend-distributions)使用 `Distribution ($)`；[SPY 基金页](https://www.ssga.com/us/en/individual/etfs/state-street-spdr-sp-500-etf-trust-spy)与[XLF 基金页](https://www.ssga.com/us/en/individual/etfs/state-street-financial-select-sector-spdr-etf-xlf)列 USD 基础币种，XLF 另列 NYSE ARCA / USD 交易币种。用户已明确采用固定 USD 口径，这些外部币种资料不再作为准入要求。**本次原始事件表仍保留 currency=null；后续规范化研究表可按项目约定声明 USD。**

## 能补哪些缺口

- **已有直接证据可补充**：两只 ETF 在指定区间的 raw 日线，以及经发行方独立核对的现金分红金额、除息日和支付日；包括此前遗漏的已除息未支付 SPY 分红。
- **采用时仍需显式处理**：来源政策和输入接入须另行确定，不能将 Alpaca 数据改标 IBKR 或静默混入已有快照。研究币种统一按 USD，不再需要额外币种关联。
- **本次没有补齐**：拆股及其他公司行动的独立完整性证明、公告与可知时间、历史修订版本、历史股票池/退市数据，以及更早年份或其他证券。没有据此宣称全市场选股、PIT 回测或 P5 正式闭环已通过。

建议继续使用该已验证范围推进日频研究输入设计，暂时没有证据支持为这些同样的历史日线和现金分红立即购买付费数据。是否需要付费，应由后续确切字段或覆盖缺口决定。

## 证据与历史保全

隔离目录：`reports/alpaca-readonly-validation-20261026-034259/`，已由 Git 忽略。主要文件为 `capture.toml`、`raw/*.parquet`、`requests.parquet`、`bars.parquet`、`events.parquet`、`issuer-source.parquet`、`checks.parquet`、`audit.parquet`、`runtime.parquet`、`artifacts.parquet`。业务表均为明确类型的 Parquet/Zstandard；原始响应保留完整字节与采集时刻。

7 项采集检查加 61 项离线核对无 error，其中发行方逐笔核对 46 项；主代理另行复核了原始响应哈希、分页链、日期与分红集合。执行前后 `data/`、`reports/` **12,649 个已有文件全部未变**，见 `history-before.parquet`、`preservation.parquet`。没有写入历史账户、登记、日志、风险状态、研究结果或旧缓存；VPS 仅作配置位置的只读检查。

临时脚本在所有请求及结果保存后，曾因发行包名误写为 `invest` 而未完成运行时元数据收尾；已按真实发行包 `wayslog-invest` 离线补齐，记录于 `execution-notes.parquet`，没有重试网络或覆盖原始捕获。运行时为 wayslog-invest 0.7.1、PyArrow 24.0.0、exchange-calendars 4.13.2。本轮未改应用代码，因此没有重跑 `make check`；本报告不把只读数据验证表述为策略收益或交易执行验收。
