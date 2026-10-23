# IBKR：唯一可信数据源与 M4 接入

更新日期：2026-10-23（北京时间）。**IBKR 是项目行情、账户、订单、成交与费用的唯一
可信外部来源**，M4 以 IBKR Paper 接入和执行核对为主线，后续实盘默认目标也是 IBKR。
嘉信保留为后续可选接入。订阅按实际需求选择并记录成本，不以全免费为前提。
来源分工及旧数据边界见 [数据来源决策](../data-sources.md)。

已完成公开资料核查、SDK 本地检查及 VPS 上的 Paper API 会话验证。
2026-10-23 15:34（北京时间），`ib_async==2.1.0` 连接主机本地 `127.0.0.1:4002` 成功，
协商协议版本为 `178`，返回一个 Paper 账户。仅建立只读用途的会话，未发送订单。
行情权限、完整账户采集和订单生命周期仍待验收，见[检查记录](https://github.com/wayslog/invest/actions/runs/39918594479)。
`0.6.1` 采集与线上冻结 M3 仍使用 Alpaca；这些数据和记录保持原来源，
属于历史复现及既有运维观察，不追认为 IBKR 数据或确认成交。

## 已知账户条件

- 用户已确认账户获批、已入金、能够登录 Paper Trading。
- 官方 TWS API 要求已开户且入金的 IBKR Pro 账户；网关 API 已接通并返回 Paper 账户，
  具体账户分类、币种、余额、持仓、美股/ETF 交易权限及行情权限仍待只读采集确认。
- 能登录 Paper Trading 不等于网关已启动，也不能据此确认 API 行情订阅。
- 行情并非全部免费：延迟报价与部分产品有免费范围，多数股票 API 行情需要相应订阅。
  SPY/XLF 对应的 Network B 非专业用户公开价为 1.50 美元/月，详见 [行情费用核查](ibkr-market-data.md)。

## Python SDK 选择

| 方案 | 本次核实结果 | 项目选择 |
| --- | --- | --- |
| 官方 `ibapi` | IBKR 官方 TWS API 提供 Python 实现；当前官方文档要求 Python 3.11+，兼容本项目的 3.12。官网提供当前 SDK；PyPI 同名包仍为 `9.81.1.post1`，发布于 2020 年 | 官方参考实现与后备方案；如采用，从官网下载匹配版本，不能把旧 PyPI 包当成当前 SDK |
| 社区 `ib_async` | 本次 PyPI 版本为 `2.1.0`，要求 Python 3.10+；项目未归档，最近一次推送为 2026-10-15。直接实现 TWS socket 协议，无需额外安装 `ibapi` | **M4 首选**，用于异步连接、订单事件、成交回报及查询核对 |
| 社区 `ib_insync` | 原仓库已经归档；`ib_async` 延续了这一接口风格 | 新接入不采用 |

已在独立的 Python **3.12.14** 环境安装 `ib_async==2.1.0`，成功导入，构造 SPY 合约与
未发送的限价单对象，并确认账户、持仓、未结订单、已完成订单、成交查询及撤单接口存在。
上述本地检查未建立网络连接。后续 VPS 会话检查已使用同一 SDK 成功接通网关；
两次检查均未提交订单，断线恢复和订单幂等尚未验收。

`ib_async 2.1.0` 将 `tzdata` 限制为 `>=2025.2,<2026`，本项目当前锁定的是 `2026.5`。
因此先在独立券商运行环境中验证，不直接改动 M3 的依赖锁或降级其时区数据。
接入时还需记录实际 Gateway/TWS 版本并验证与所选 SDK 的兼容性。
已确认协商协议版本 `178` 可建立会话；Gateway 的完整应用版本仍待记录。

## 连接方式

采用 **Python 适配器 → IB Gateway → IBKR Paper**，开发时也可用 TWS。
这是连接登录后的网关 TCP socket，不是取得 API Key 后直接访问券商云端的 HTTP 服务。
长期运行使用现有 Linux 主机；GitHub Actions 负责部署和检查，网关会话由主机维持。
无桌面 VPS 的安装、虚拟显示器及首次登录步骤见 [Gateway 安装说明](ibkr-gateway.md)。

1. 安装 IB Gateway，并选择 **Paper Trading** 登录；初次接入在网关开启 Read-Only API。
2. Python 连接本机 API 端口。默认 IB Gateway paper 为 `4002`、TWS paper 为 `7497`，
   最终以网关实际配置为准；同一网关内为执行客户端固定独立的 `clientId`。
3. 先查询账户、币种、现金、持仓、订单、成交及 SPY/XLF 合约，再试读历史日线、分钟线
   和实时报价，保存类型明确的 Parquet/Zstandard 回执；记录实际实时/延迟类型及数据时间。
   历史使用 `reqHistoricalDataAsync`、报价使用 `reqMktData` 等接口，具体权限以回执确认。
4. 完成数据规范化与本地订单状态机的离线验证后，再进行 Paper 联调，
   验证委托确认、拒单、撤单、部分成交、超时查询和重连核对。
   记录本地订单 ID 与 `clientId`、`orderId`、`permId`、`orderRef`、`execId` 的关联；
   `orderRef` 只用于关联，不能假定它会让券商自动去重。

`ib_async.connect(readonly=True)` 只调整连接初始化时的查询，不会禁止后续调用下单方法；
首次只读接入以 **Gateway/TWS 的 Read-Only API 设置**为准。
网关需要登录并按 IBKR 的日常重启、每周重新认证机制维持会话；失去会话时告警并查询恢复，
不能把 SDK 断线重连等同于重新完成登录认证。

## 行情与账务口径

- 原始行情、账户响应、委托事件、成交及费用记录均捕获为 Parquet/Zstandard，
  明确来自哪个 IBKR 接口、账户和环境；规范化结果保留与原始输入的关系。
- `TRADES` 历史价格已调整拆股，`ADJUSTED_LAST` 还调整分红；须核对价格调整、成交量单位、
  常规/盘前盘后时段与时区，不能把它们直接当作现有 `price_basis=raw` 的日线。
- 分红、拆股、费用及现金支付以 IBKR 事件、流水或报表为依据；历史字段不足时明确记录，
  不以 Alpaca、发行方表或本地推测静默补成 IBKR 数据。
- 本地下单意图、预测成交与 IBKR 确认分开存储。账本采用确认的成交和费用；
  后到费用、重复或乱序回报、券商更正保留原始记录并追加处理，不覆盖旧决定。

## 与当前系统的关系

- M3 原账户继续由现有主机唯一写入，保留 5,000 美元口径、风险历史及原观察窗口。
  IBKR Paper 余额是对应券商账户的事实快照，不能自动替换项目 5,000 美元预算、
  原本金或净值高点；须明确外部账户与项目资金账本的对应关系。
- M4 先完成 IBKR 行情/账户只读采集及通用订单状态机的离线验证，再开展 Paper 订单联调。
  SDK 的事件缓存不替代本项目的持久化和对账。
- 本地预测成交与 IBKR 确认的模拟成交分开保存；部分成交、费用及现金差异需要核对。
  Paper 是模拟撮合，不能证明实盘成交质量或策略盈利能力。
- Alpaca 和发行方旧输入保留为历史记录及参考，不作为新主线的自动回退源。
  线上冻结 M3 按原来源继续记录运维证据；接入 IBKR 时记录切换边界，
  不修改冻结研究、旧账户日志、风险状态或观察窗口。
- IBKR 实时/历史数据的公开费用已核查，实际权限、调整口径及 Flex/报表能力待只读验证。
  行情接入、Paper 工程验收及策略资格分别记录；实盘范围和账户权限在 M5 确认。

## 来源与验证记录

- [IBKR TWS API 简介](https://www.interactivebrokers.com/docs/tws-api/doc/introduction)：官方 SDK 与 socket 连接方式。
- [TWS API 要求](https://www.interactivebrokers.com/docs/tws-api/doc/notes-limitations/requirements)：账户条件与 Python 版本。
- [官方 SDK 下载](https://download2.interactivebrokers.com/installers/tws-api/index.html)与 [PyPI ibapi](https://pypi.org/project/ibapi/)：区分当前官方安装包和旧 PyPI 发布。
- [ib_async 仓库](https://github.com/ib-api-reloaded/ib_async)与 [PyPI 发布](https://pypi.org/project/ib_async/2.1.0/)：维护状态、接口及依赖。
- [ib_insync 原仓库](https://github.com/erdewit/ib_insync)：已归档。
- [API 设置](https://www.interactivebrokers.com/docs/tws-api/doc/tws-settings/introduction)：连接端口与网关配置。
- [Paper Trading 配置与限制](https://www.ibkrguides.com/clientportal/aboutpapertradingaccounts.htm)：模拟撮合及权限关系。
- [网关重新认证](https://www.interactivebrokers.com/docs/tws-api/doc/tws-settings/daily-weekly-reauthentication)：运行会话要求。

本次公开响应、获取时间及本地 SDK 检查保存在忽略目录
`reports/access/ibkr-sdk-2026-10-22/`，使用 Parquet/Zstandard。
之前的资料保留在 `reports/access/ibkr-2026-10-21/`。
