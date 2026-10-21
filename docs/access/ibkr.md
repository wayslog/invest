# TODO：IBKR 支持（后期）

状态：后期 TODO，当前不实施。记录日期：2026-10-21（北京时间）。
用户确认账户已获批、已入金且能登录 Paper Trading；本项目尚未连接 IBKR API。
当前继续推进 M3 的 CI、部署、日结、备份及观察记录，IBKR 不作为当前任务或阻塞项。

后续进入 M4/M5 时再排期评估这些能力：

- [ ] 通过 TWS API / IB Gateway 读取账户、现金、持仓、订单与成交，保存 Parquet 快照。
- [ ] 接入 paper 报单、撤单、拒单及成交回报，验证幂等、断线恢复和订单状态核对。
- [ ] 接入券商报表与 Flex Queries，核对费用、现金流水和持仓。
- [ ] 评估实时/历史行情作为现有数据源的补充，核实实际授权与订阅成本。
- [ ] 评估同券商 paper 到实盘的接口复用，以及多币种、期权等后续扩展。

届时再核实 IBKR Pro/API 条件、交易及行情权限、网关登录与定期重新认证。
Paper 成交属于模拟；既有资金账户、风险历史、研究资格及观察窗口继续保留。

公开资料已归档到忽略目录 `reports/access/ibkr-2026-10-21/`，供后续参考：

- [TWS API 要求](https://www.interactivebrokers.com/docs/tws-api/doc/notes-limitations/requirements)
- [Paper Trading 配置与限制](https://www.ibkrguides.com/clientportal/aboutpapertradingaccounts.htm)
- [行情与费用](https://www.interactivebrokers.com/en/pricing/market-data-pricing.php)
- [网关重新认证](https://www.interactivebrokers.com/docs/tws-api/doc/tws-settings/daily-weekly-reauthentication)
