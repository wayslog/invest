# SPY、QQQ 免费历史归档的有限核验

核查日期：2026-10-26。回测区间为 2025-07-07 至 2026-10-23，主任务需要 68 周、136 个基金周截点。本次只验证免费公开入口，限制为 **1 次检索与 9 次独立 GET，共 10 次**；未登录、付费、联系他人或修改已封存 v1 证据。

**免费归档并非不存在：已成功取得并核对一份历史 SPY 持仓原件。** 但现有正证据仍不覆盖完整区间；QQQ 找到了归档索引，尚未取得其中的成员正文，不能把索引行计作已验证持仓。

## 官方页面和公开前端配置

复用 v1 已冻结的 [SPY 官方页面](https://www.ssga.com/us/en/individual/etfs/state-street-spdr-sp-500-etf-trust-spy)、[QQQ 官方页面](https://www.invesco.com/us/en/financial-products/etfs/invesco-qqq-trust-series-1.html)，并分别读取页面实际引用的一个公开 JavaScript 文件，均 HTTP 200。

- SPY 页面实际持仓下载链接仍是 `holdings-daily-us-en-spy.xlsx`；找到的历史链接是 NAV 和分红，不是历史成员。所检查的脚本中未定位到历史持仓日期请求。
- QQQ 页面内嵌 `data-model-json` 可程序化解析。9 个引用 `holdings/fund` 的持仓表配置均为 `dateRangeConfigEnabled=false`；主要持仓表另有 `dropdownType=showLastTwelveMonths`，但 `showDropdown=false`，不能据此推断已启用历史查询。
- 页面中的价格历史组件有日期选择器，但调用 `navs`，不能拿来替代持仓历史。已读取的 QQQ 脚本未定位到持仓历史日期请求；本轮没有穷尽全部按需脚本和网站其他入口。
- QQQ 持仓组件明确提供 `productMetaData.cusip=46090E103`、`locale=en_US`、`uniqueIdentifier=cusip`。因此后续归档查询使用这个实际页面配置，不依赖猜测参数。

这说明本轮没有验证出官方历史日期下载入口，**不等于证明后台或其他公开入口不存在**。

## Wayback CDX：索引、正文和内部日期分别核验

根据 [Internet Archive 官方 CDX 文档](https://github.com/internetarchive/wayback/blob/master/wayback-cdx-server/README.md)，使用 `url`、`matchType=prefix`、`from`、`to`、`output=json`、`filter=statuscode:200`、`limit=5000`、`showResumeKey=true` 查询已观察到的发行方 URL。没有枚举或试探大量历史路径。

| 查询目标 | 实际响应 | 本轮结果 |
| --- | --- | --- |
| SPY 官方 XLSX URL 前缀 | HTTP 200 | 2025-01-01 至 2026-10-26 共 7 条捕获索引，目标区间内 4 条 |
| QQQ `shareclasses/QQQ/holdings/fund` 前缀 | 两次均 25 秒超时 | 没有索引响应；超时不表示没有归档 |
| QQQ 页面配置对应的 `shareclasses/46090E103/holdings/fund` 前缀 | HTTP 200 | 3 条捕获索引，MIME 均为 `text/html`；尚未取正文 |

SPY 在目标区间内的捕获键为 `20251225080333`、`20260517153630`、`20260925014247`、`20261005005838`。QQQ 为 `20250914071117`、`20260530001220`、`20260603152542`。这些是**捕获记录，不是文件内部持仓日期**。本次两个成功索引响应没有返回续页键；结论只限本轮查询的 URL 前缀，不覆盖所有历史别名或镜像。

### 已核验的 SPY 原件

先读取 [Wayback 捕获页](https://web.archive.org/web/20260925014247/https://www.ssga.com/library-content/products/fund-data/etfs/us/holdings-daily-us-en-spy.xlsx)，得到 HTTP 200 的 HTML 包装页；再跟随其实际 `iframe src` 取得 [XLSX 载荷](https://web.archive.org/web/20260925014247if_/https://www.ssga.com/library-content/products/fund-data/etfs/us/holdings-daily-us-en-spy.xlsx)。不能把第一步的 HTML 成功当作工作簿已取得。

| 项目 | 已验证事实 |
| --- | --- |
| 实体类型、大小 | XLSX，54,443 字节，HTTP 200 |
| 历史捕获上界 | `Memento-Datetime: Fri, 25 Sep 2026 01:42:47 GMT`，与 CDX 捕获键一致 |
| 文件内部持仓日期 | **2026-09-23** |
| 成员解析 | 505 行，503 行符合现有普通股票识别条件；其余原始行保留 |
| 原件一致性 | 载荷 SHA1 的 Base32 表达与 CDX digest 一致；另冻结 SHA256 |

这份内容最迟在历史捕获时已经被观察到，不需要猜出发行方首次发布时间。可以把该时刻作为 `known_by` 上界，供更晚的周度决策使用，并按预先固定的持仓日期时效规则判断是否过旧。例如它早于 2026-09-27 的周末决策，但其持仓所属日仍是 9 月 23 日，不能改写为 9 月 25 日，也不能据此证明中间没有更新。

### QQQ 仍只是归档线索

三个 CDX 记录的原 URL 都来自上述 CUSIP 路径，其中带有实际记录的 `idType=cusip`、`productType=ETF` 等参数。因 10 次预算已用完，本次没有继续读取其正文。`text/html` 可能是页面、包装或错误内容，即使索引状态为 200，也不能认定返回完整 JSON 成员。需要后续先验证载荷类型、基金身份、完整行数、内部日期和摘要，再计算覆盖。

本轮得到 **1 份可解析的历史 SPY 成员载荷、0 份已验证的历史 QQQ 成员载荷**。这还不足以拼出任何已完整验收的双基金周截点，更不支持全部 136 个基金周截点。这里的零仅指本轮已验证结果，不是对互联网上归档存在性的断言。

## 日期粒度可以成为保守可得界限

周度策略不必机械要求首次公开时间精确到秒。可采用以下证据规则，且在看收益前冻结：

| 日期/时刻的真实含义 | 可采用的保守规则 |
| --- | --- |
| 已取得并验证正文的历史捕获 | 用捕获时刻作为 `known_by`，只在其后决策；保留历史原件版本 |
| 来源证明某个当地日期内已公开，但只有日期 | 以该来源时区的次日零点作为保守上界，再转 UTC；正确处理夏令时。周度截点晚于上界即可使用，不必补造日内时刻 |
| 仅有持仓所属日期、生效日 | 不能据此推出当天已公开；需要捕获或其他可得证据 |
| 仅有数据商处理日期 | 若来源没有证明当日已可公开取得，不能直接当作公开日期；可以用自有首次捕获或其他已验证上界补足 |

“晚于可得上界”只解决时间顺序，还必须验证基金身份、成员完整性、内部持仓日期时效和版本。取到旧快照不证明它是当时最新的那一版；若策略允许使用截至截点最近一份**已验证**且未过期的公开快照，需要在规则和结果中说明。不能把未来捕获时间改早，不能从未来快照向过去回填成员。

## 证据目录与结果

新证据目录为 `reports/dynamic-universe-audit-20261026-v2/issuer/`。所有数据表使用有类型的 Parquet/Zstandard。

- `requests-02-06.parquet`、`requests-07-08.parquet`、`requests-09-10.parquet` 保存 9 次 GET 的完整响应、错误、方法、URL、实际采集时刻、响应头及 SHA256。
- `request-ledger.parquet` 记录 10 次外部检索/请求。第 1 次为发现官方 CDX 文档的检索，未另保存网页工具返回全文；第 2 次已实际取得该官方文档的完整 HTML。
- `frozen-page-inputs.parquet` 保留从 v1 复用的官方页面和当前下载输入，原采集时间与正文不变，不计为新增请求。
- `frontend-inspection.parquet` 保存解析出的 QQQ 持仓和价格历史组件契约。
- `archive-indices.parquet` 保留全部 10 条索引以及 `payload_verified`、`holdings_as_of`、`known_by`，不把未读取载荷的索引标成成功成员。
- `verified-spy-members.parquet` 保存已验证的 505 行历史 SPY 成员及归档来源。
- `checks.parquet` 和 `artifacts.parquet` 保存本轮摘要、格式、时间及完整清单核验。

本轮修正了“尚未找到”可能被误读成“不存在”的表述，并取得部分免费正证据；没有以稀疏归档冒充全区间动态回测，也没有继续推进付费来源。
