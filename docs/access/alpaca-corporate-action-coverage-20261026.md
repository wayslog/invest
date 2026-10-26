# Alpaca 拆股正例与公司行动覆盖核查

核查日期：2026-10-26（Asia/Shanghai）。本次新增 9 次只读市场数据请求，全部 HTTP 200；只访问 `data.alpaca.markets` 的行情和公司行动接口，没有读取券商账户资料或修改订阅。币种按项目约定统一 USD。SPY/XLF 为研究池；NVDA 仅为拆股验证样本，不加入策略池。

**可以按明确范围使用 Alpaca 原始日线和已核验的现金分红；拆股覆盖应保留为供应方报告的有界研究证据。** 本次取得真实 10:1 拆股正例，并核对 SPY/XLF 全区间的拆股调整因子，但不将空事件、价格对照或单个正例表述为全部公司行动及历史版本完整。

## SPY/XLF 的区间覆盖

对 2021-01-04 至 2026-10-23 分别请求 `feed=sip`、`adjustment=raw` 和 `adjustment=split`，每组完整遍历 3 页：

| 证券 | 每组日线数 | OHLC 对照 | 成交量对照 |
| --- | --- | --- | --- |
| SPY | 1,459 | 每日四价全部相同 | 每日全部相同 |
| XLF | 1,459 | 每日四价全部相同 | 每日全部相同 |

该结果与[此前全类型公司行动查询](alpaca-readonly-validation-20261026.md)未返回两只 ETF 的拆股事件相符；此前各 23 笔现金分红的金额、除息日和支付日已与重新捕获的发行方记录完全一致。拆股因子对照和事件清单来自同一供应方，它们是互相一致性证据，不能当成两个独立来源。

独立查阅的 [State Street 2025-11-20 拆股公告](https://investors.statestreet.com/investor-news-events/press-releases/news-details/2025/State-Street-Investment-Management-Announces-Share-Splits-for-Five-Select-Sector-SPDR-ETFs/default.aspx)列明 2025-12-05 的 2:1 拆股对象是 XLK、XLY、XLE、XLU、XLB，未包含 SPY/XLF。它确认这一批次的具体名单，不能推出其他年份没有事件。本次未找到覆盖整个研究区间、明确保证 SPY/XLF 所有公司行动完整的发行方清单。

建议准入口径为 `bounded_research`，记录证券、日期区间、供应方全类型事件查询、分页完成情况、发行方现金分红核对和拆股价格/股数对照。保留 `provider_reported` 的拆股及其他公司行动覆盖限制，不能直接写为无条件 `corporate_actions=complete`。这允许研究在已知边界内推进；若实际返回不支持的行动，仍应明确拒绝或隔离。

## NVDA 真实 10:1 正例

[NVIDIA 2024-05-22 官方公告](https://nvidianews.nvidia.com/news/nvidia-announces-financial-results-for-first-quarter-fiscal-2025)说明：6 月 6 日收盘登记，每股额外分配九股，6 月 7 日收盘后分配，6 月 10 日开始按拆股后价格交易。[后续官方财报](https://nvidianews.nvidia.com/news/nvidia-announces-financial-results-for-second-quarter-fiscal-2025/)确认拆股已完成。

Alpaca 真实事件返回 `new_rate=10`、`old_rate=1`、`ex_date=2024-06-10`，与发行方比例和拆股后交易日相符。比例定义为新股数除以旧股数；持仓股数应乘 10，每股成本及相关价格尺度除以 10。

采集 2024-06-03 至 2024-06-14 的 10 个会话并逐项对照：

| 项目 | 拆股前 5 个会话 | 拆股日起 5 个会话 |
| --- | --- | --- |
| 成交量 | `split_volume = raw_volume * 10`，全部精确一致 | 原始量和调整量相同 |
| OHLC | `split_price = round(raw_price / 10, 0.01)`，观察到四舍五入至美分 | 原始价和调整价相同 |
| 无损反推原价 | 严格等式检查失败，保留失败证据 | 此样本无差异 |

例如 2024-06-04 原始收盘价为 1164.37，拆股调整收盘价为 116.44；反乘 10 得到 1164.40，已经丢失 0.03 美元的原价精度。全部 40 个 OHLC 字段符合本样本的 `ROUND_HALF_UP` 美分舍入；最大原价反算差为 0.05 美元。因此执行回测必须直接使用 `raw` 响应，本次不通过调宽误差阈值把“无损还原”改成通过。[Alpaca 调整参数定义](https://docs.alpaca.markets/us/reference/stockbars)

事件还带 `due_bill_redemption_date=2024-06-10`。其 `record_date=2024-06-07`、`payable_date=2024-06-10` 与发行方描述的登记日、收盘后分配日不同，说明不能把供应方所有日期字段统一视为发行方日期。该样本只验收已独立核对的比例和拆股后交易日；既有适配器对 due-bill 的拒绝保持不变，NVDA 不进入本次 SPY/XLF 回测。

## 证据和限制

新隔离目录为 `reports/alpaca-corporate-actions-20261026-040045/`，由 Git 忽略。数据均为类型明确的 Parquet/Zstandard：

- `raw/0001.parquet` 至 `0009.parquet`：完整响应字节、请求参数、接收时刻、摘要和 HTTP 状态；1–3 为 SPY/XLF raw，4–6 为 split，7–8 为 NVDA raw/split，9 为 NVDA 事件。
- `split-reference.parquet`：按现有 `invest.alpaca.RAW_SCHEMA` 投影第 4–6 页，`kind=split_reference`；供新导入器重放校验，原捕获不变。
- `adjustments.parquet`：2,928 个逐日对照；`checks.parquet` 保留 NVDA 原价严格反算失败。
- `precision-analysis.parquet`：40 项舍入分析，与严格检查分别保存。
- `issuer-reference.parquet`：从官方网页明确提取的事件事实和来源链接；它不是原始 HTML 回执。
- `prior-preservation.parquet`：此前 Alpaca 验证目录清单中的 41 个文件全部未变；`artifacts.parquet` 封存本次新增产物。

公开 HTML 的直接下载遇到 HTTP 403，发生时全部 9 次 Alpaca 请求及数据表已保存；官方公告通过网页工具另行核实，限制记在 `execution-notes.parquet`。没有重采集或覆盖原始行情。临时脚本读取旧辅助函数时产生的一份新字节码缓存已清理，旧证据清单全部通过保全核验。

本次仍未证明完整历史公告可知时间、修订链、退市/历史股票池和全部复杂公司行动覆盖。当前结果支持带来源和范围限制的 SPY/XLF 历史研究，不自动取得实时交易或完整历史时点数据资格。
