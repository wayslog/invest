# 免费 ETF 历史接口的补充核验

2026-10-26，用户明确仅使用免费来源。本次实际只读请求 TickerInside 的 SPY/QQQ 历史和当前持仓接口，4 次均 HTTP 200；原始响应及摘要保存在 `reports/dynamic-free-provider-20261026-v1/captures.parquet`。

[SPY 历史](https://tickerinside.com/api/v1/history/spy.json)与 [QQQ 历史](https://tickerinside.com/api/v1/history/qqq.json)返回的范围都只有 **2026-09-02 至 2026-10-22**。内容是文件日期、统计与相邻文件的变化；`holdings_at=null`，没有启用按日期取得完整历史持仓的入口。期间还存在标识规则切换，不能不加核验地从当前持仓倒推全部旧名单。这是确实取得的部分历史证据，尚不能填补 2025-07-07 起的 68 周回测。

来源归属：TickerInside，依据发行方文件整理，见[接口及历史条款说明](https://tickerinside.com/api/#history)。历史内容适用独立条款，不应将当前数据的 CC BY 4.0 标识套用到整份历史档案；本次是两只基金的一次性核查，没有设置批量镜像或定时采集。

[ETF Holdings API](https://etf-holdings.com/)也有按日期查询，但网站示例明确返回所解析的 SEC 报告日期，而非保证该请求日的实际基金持仓；程序 API 使用预付额度。本次没有注册、充值或调用收费接口，不纳入免费执行路线。

这些结果补充而不覆盖[发行方和 SEC 核查](historical-spy-qqq-membership-20261026.md)。仍需区分“发现历史接口”“取得某次历史原件”和“完整覆盖目标区间”，不能把其中一项当成另外两项的证明。
