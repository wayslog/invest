# VLO、FTNT、ILMN 发行方与公司行动证据

核查日期：2026-10-26（Asia/Shanghai）。本次只读取公开发行方和交易所资料，补齐三只股票离线成本回测所需的现金分红证据。共同候选区间为 **2024-07-01 至 2026-10-23**；起点在查看本轮收益前固定，用来排除当前引擎尚不支持的 ILMN 2024-06-25 GRAIL 分拆。本报告不包含收益、选股评分或交易建议，不修改历史账户、研究记录和正式准入规则。

**VLO 的金额和付款日已获得独立发行方证据；其官网显示的除息日存在差异，需要保留原值并显式按交易所规则派生。FTNT、ILMN 的零现金分红声明可以与供应方全类型公司行动查询交叉使用，但不能代替公司行动覆盖证据。**

## VLO：保留官网差异，明确 T+1 派生依据

[Valero 官方分红表](https://investorvalero.com/stock-information/default.aspx)提供 `Declared`、`Ex Date`、`Record`、`Payable`、`Amount`、`Type`。实际 HTTP 200 HTML 已冻结；程序按 `table--dividends` 和各单元格的 `data-heading` 提取，而非手工录入事件。只处理 `Type=U.S. Currency` 的现金分红；表中还存在历史 `Stock dividend` 行，其登记日等字段为空，不能混用。

本次程序从表中提取区间内 9 笔现金分红，与已冻结的 Alpaca 全类型公司行动响应逐项比较：

| 字段 | 结果 |
| --- | --- |
| 登记日、每股金额、付款日 | 9 笔全部相同 |
| Alpaca 除息日与发行方登记日 | 9 笔全部相同 |
| 官网显示除息日与 Alpaca 除息日 | 9 笔全部不同；官网显示较早日期 |

上述结果由 `issuer-evidence/audit_evidence.py` 从两个实际响应生成，逐笔字段及源摘要保存于 `vlo-dividend-inspection.parquet`。本次没有改写官网 `Ex Date`，也没有把 Alpaca 日期假称为发行方原值。差异成因尚未获得发行方解释。

[NYSE 当前规则说明](https://www.nyse.com/trade/ex-date-dividends)明确：T+1 下通常在登记日除息，带 due bill 等特殊情形另有安排。[NYSE 2024 年指导函](https://www.nyse.com/publicdocs/nyse/markets/nyse/NYSE_2024_Annual_Guidance_Letter.pdf)记录了从登记日前一交易日转为登记日的变更，以及 2024-05-28/29 过渡安排。拟定区间自 2024 年 7 月开始，不跨越过渡日。

[FINRA Rule 11140](https://www.finra.org/rules-guidance/rulebooks/finra-rules/11140)补充了普通分配、小于证券价值 25%、信息及时送达、非交收日和大额分配等条件。VLO 在 NYSE 上市，具体派生应首先引用 NYSE 的规则与历史生效说明；不能把 FINRA 的适用范围直接泛化为所有上市证券。

建议对这 9 笔事件分别保留 `issuer_displayed_ex_date` 和依据发行方登记日派生的除息日，并记录派生规则、输入和冲突。执行派生前仍需程序确认正常现金分红、金额比例、宣布日期、有效交易日及不存在特殊除息安排；不能无条件将任何登记日复制成除息日。金额比例检查需要行情，本次发行方证据核查没有执行该项，也不单独授予交易准入。

## FTNT、ILMN：零现金分红是有范围的交叉证据

| 证券 | 发行方证据 | 可支持的结论与边界 |
| --- | --- | --- |
| FTNT | [当前 FAQ](https://investor.fortinet.com/investor-faqs)称从未宣告或支付现金分红；[2025 年 Form 10-K](https://investor.fortinet.com/node/27496/html)的 Dividends 段提供相同历史声明 | 支持零现金分红核对。政策未来可以变化，不能据此推断无拆股、分拆或其他行动 |
| ILMN | [当前 FAQ](https://investor.illumina.com/ir-resources/investor-faqs)说明当前不派息；[2025 年报](https://investor.illumina.com/static-files/8478238c-850e-4206-9c80-d09b060ce134)说明此前从未支付现金分红 | 年报补足 FAQ 只有当前政策的不足，仍需对研究区间重新核对供应方事件清单 |

两份年报均来自发行方网站。FTNT 财年截至 2025-12-31，官方年报索引列明 2026-02-25 提交；ILMN 财年截至 2025-12-28。声明是本次实际观察到的资料，不能倒填为历史任一交易日已知的版本。[FTNT 年报索引](https://investor.fortinet.com/annual-reports-and-proxies)

重放解析定位如下，行号属于所保存的网页工具提取结果，不是稳定 API：

- `web-ftnt_dividend_policy.parquet`：问题 `Does the company pay a cash dividend?`，随后为声明；当前提取 L796–L797。
- `web-ftnt_annual_2025_dividends.parquet`：`Dividends` 标题后的段落；当前提取 L1616–L1617。
- `web-ilmn_dividend_policy.parquet`：普通股分红与 DRIP 问题后的当前政策；当前提取 L73–L75。
- `web-ilmn_annual_2025_dividends.parquet`：现金分红政策段落，当前提取 L1316@P32；股份支付假设部分 L2700–L2701@P67 另有辅助声明。

解析器应绑定来源、公司身份和正文结构，不能仅在任意网页中搜索短语就通过。不存在事件的结论必须结合本轮全类型查询、分页结束和明确日期范围；不能生成虚构的零金额分红事件。

## ILMN 分拆：保存区间外已知事件

[Nasdaq ECA2024-262](https://www.nasdaqtrader.com/TraderNews.aspx?id=ECA2024-262)明确 ILMN 对 GRAL 的分配比例为每 6 股 ILMN 获得 1 股 GRAL，登记日 2024-06-13、支付日 2024-06-24、除权日和 due-bill redemption date 均为 2024-06-25。实际 HTTP 200 HTML 和网页工具提取均已保存。

已冻结的 Alpaca 响应返回同日 `spin_offs`，新证券为 GRAL、比例近似 `0.166666667`。这不是普通现金分红或股票拆分；本轮固定 2024-07-01 起点可以使新建空仓研究区间位于该事件之后，但不能删除该事件，或把缩短区间描述为引擎已经支持分拆。

供应方全类型查询还返回 FTNT 2022 年拆股，说明“没有现金分红”并不等于“没有公司行动”。该供应方历史事件保存在原始响应中，本次没有独立验收其所有日期字段。

## 冻结产物与可重放格式

新证据目录为 `reports/focus-cost-backtest-20261026-v1/issuer-evidence/`，由 Git 忽略。共 17 条来源捕获：8 条直接 HTTP 响应和 9 条网页工具提取返回。采集时间保存在 `observed_at`，范围为 2026-10-26 06:46:15 至 06:52:20 UTC。权威表与检查表均使用有类型的 Parquet/Zstandard。

| 文件 | 内容 |
| --- | --- |
| `http-sources.parquet` | 8 条完整 HTTP 解码后实体字节。VLO、NYSE 当前规则、NYSE 指导函 PDF、FINRA 规则、Nasdaq 分拆公告为 200；FTNT FAQ、ILMN FAQ 和 ILMN 年报为 403，错误响应原样保留 |
| `web-vlo_history.parquet`、`web-nyse_exdate.parquet`、`web-nyse_t1_guidance.parquet`、`web-finra_rule.parquet` | 发行方表格及除息规则的实际网页工具返回 |
| `web-ftnt_dividend_policy.parquet`、`web-ftnt_annual_2025_dividends.parquet` | FTNT 当前声明与历史年度声明 |
| `web-ilmn_dividend_policy.parquet`、`web-ilmn_annual_2025_dividends.parquet`、`web-ilmn_spin.parquet` | ILMN 当前声明、历史年度声明和 Nasdaq 分拆公告 |
| `vlo-dividend-inspection.parquet` | 9 行独立字段比较；金额为 `decimal128(12,6)`，日期为 `date32`，比较结果为 `bool`，含两侧来源摘要及供应方事件 ID |
| `capture_http.py`、`audit_evidence.py` | 本次隔离采集和核对程序；输出路径存在时拒绝覆盖 |
| `artifacts.parquet` | 本目录另 13 个文件的路径、大小、SHA256 与核验时刻，不包含其自身 |

HTTP 捕获模式为 `invest.research.issuer_source_capture.v1`：`capture_id/symbol/url/final_url/method/content_type/sha256/error` 使用字符串，`status` 为 `int32`，`observed_at` 为 UTC 微秒时间戳，`body` 为二进制。`method=http_get_decoded_entity` 表示已解压 HTTP 内容编码后的实体，摘要计算对象就是保存的 `body`，不冒充线上的压缩传输字节。

网页提取模式为 `invest.research.web_source_capture.v1`：`capture_id/symbol/url/method/request/sha256` 使用字符串，时间和正文类型同上。`method=web_tool_extract`，`request` 保存实际请求参数，`body` 保存工具实际返回的 UTF-8 字节，包含引用标记和行号。它可能是页面或 PDF 的提取片段，**不是完整原始 HTML/PDF**；不能将该方法标记为直接 HTTP 成功。

本次读取的供应方原件为同级 `actions-probe.parquet`，使用既有 `invest.raw.alpaca.v1` 模式。查询覆盖 VLO/FTNT/ILMN、1970-01-01 至 2027-02-23，返回 43 笔 VLO 现金分红、1 笔 FTNT 拆股和 1 笔 ILMN 分拆，`next_page_token=null`；这是该供应方本次请求的返回范围，不是自 1970 年起全球公司行动完整性的保证。本次没有读取任何 Alpaca 凭据或账户，也没有改写该捕获。

## 验证与仍保留的限制

本次逐条验证了 17 个来源正文的 SHA256、UTC 时间类型及全部新增 Parquet 的 Zstandard 压缩；9 笔 VLO 分红的登记日、金额和付款日比较通过，9 个官网除息日冲突作为结果保留。代码检查及全链路回测属于主任务，本只读证据子任务没有运行 `make check`。

研究可采用 `bounded_research`：保留 Alpaca 来源、探索范围、真实请求、发行方证据、日期派生依据，以及后续 raw/split 行情对照。当前资料不能证明完整历史公告可知时刻、修订链、退市和历史股票池、全部复杂公司行动，也不能证明网站没有遗漏。FTNT/ILMN HTTP 403 的限制和网页提取方式不能隐藏；本轮结果不提升为 IBKR 执行数据或无条件完整历史时点数据。
