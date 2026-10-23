# IBKR 行情订阅：社区使用经验核查

核查日期：2026-10-22（北京时间）。本记录补充[官方费用核查](ibkr-market-data.md)，
依据公开开发者问答的正文与评论。用户自述及维护者解释不是账户账单，历史价格不是当前报价。
本次没有连接用户账户或购买订阅。

## 可直接查阅的案例

### 1. 实际用户讨论了月费与 L1/L2、专业用户分类

[ib_insync #514](https://github.com/erdewit/ib_insync/issues/514)，2022-10-19 至 10-20。
提问者请求 ES 历史数据收到 `No market data permissions for GLOBEX FUT`，
并表示订阅了 CUSIP 但没有解决。回复者指出需要 CME 行情，明确自述自己在用：

- [月费自述](https://github.com/erdewit/ib_insync/issues/514#issuecomment-1285058375)：`It costs $1.25/mo`。
- [分级及分类讨论](https://github.com/erdewit/ib_insync/issues/514#issuecomment-1285121534)：
  自报 L1 为 1.25 美元/月、L1+L2 为 11 美元/月；另一位用户看到 123 美元/月，
  回复者提出 Professional 分类可能解释差异，提问者随后确认其建议。

这证明实际使用中存在按市场、数据级别和用户分类选择订阅的过程，
不证明 2026 年的 CME、SPY 或 XLF 仍适用上述旧价格。当前 Network B 的
1.50 美元/月来自本次官方价目表核查，不能归为这些用户的实际支出。

### 2. 请求旧历史日期仍会碰到订阅限制

[ib_insync #461](https://github.com/erdewit/ib_insync/issues/461)，2022-03-30。
用户认为 TWS 能显示延迟图表，尝试请求不含最近数据的历史分钟线，仍收到
`No market data permissions for NYSE STK`。
[项目维护者于 2022-04-28 回复](https://github.com/erdewit/ib_insync/issues/461#issuecomment-1112032616)：
`a data subscription is required for that`。

这个案例与官方关于历史 API 权限的说明相符：免费延迟报价不自动包含历史 K 线 API。
其范围是该用户的请求，不能推广为外汇等所有产品都需要付费。

### 3. 自报已经订阅，仍不代表当前请求能成功

[ib_async #91](https://github.com/ib-api-reloaded/ib_async/issues/91)，2024-11-17。
用户自报已订阅 OPRA 非专业 L1，但请求 SPY 期权报价仍收到 354 错误：
`Requested market data is not subscribed. Delayed market data is available.`

[贡献者回复](https://github.com/ib-api-reloaded/ib_async/issues/91#issuecomment-2481685538)
建议核查账户具体套餐、先确认合约，并区分获取合约列表与获取实时报价。
该帖未给出已验证的最终根因或成功回执；不能据此断言 OPRA 无效、必须另买某套餐，
也不能把“我已订阅”作为本项目的实际权限证明。

### 4. 也保留“未额外订阅却能取历史”的相反自述

[ib_insync #535](https://github.com/erdewit/ib_insync/issues/535)，2022-12-17。
用户声称原生 `ibapi` 可以不额外订阅读取历史数据，而 `ib_insync` 报缺权限。
[维护者回复](https://github.com/erdewit/ib_insync/issues/535#issuecomment-1356147698)：
`There's no difference.`

该帖没有提供同一账户、合约、请求参数及既有权限的完整对照，原因未得到解释。
这是需要承认的成功自述，但不能据此推出更换 SDK 能绕过订阅，或股票历史 API 普遍免费。

## 对本项目的结论

社区确实反复提及订阅、月费、专业分类以及缺权限错误。它们支持先核对本账户的数据
范围，而不是从“别人能取到报价”推导零成本完整行情。
目前仍按官方公开价评估 SPY/XLF 的 Network B，实际费用及 Paper 共享以本账户核查为准。
免费延迟、历史 K 线与实时报价分别试读，记录实际数据类型及错误，不将成功个例扩展为通用承诺。

原始搜索响应、问题正文及评论保存在忽略目录 `reports/access/ibkr-community-2026-10-22/`，
使用 Parquet/Zstandard。Reddit 访问返回 403，未作为已读案例引用；
搜索结果中的研究计划或待办也未当作已发生的使用经验。
