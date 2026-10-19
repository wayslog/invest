# Parquet 数据约定

所有数据表使用 Parquet 和 Zstandard 压缩。不能通过文件扩展名伪装格式；输入会验证
Arrow 类型、日期、价格、企业行动和来源元数据。金额/原始价格采用 `decimal128(24, 6)`，
会计运算使用 Decimal；收益和绘图可使用浮点数。

## Paper 日线：invest.bars.v1

目前每个文件只包含一个标的、每个交易日一行；列顺序和类型必须与下表一致。

| 字段 | Arrow 类型 | 含义 |
| --- | --- | --- |
| date | date32 | 美东交易日；非 UTC 时间戳 |
| symbol | string | 必须与账户配置一致 |
| open / high / low / close | decimal128(24, 6) | 未复权原始 OHLC，美元，严格为正 |
| volume | int64 | 当日成交量，非负；为零时不模拟成交 |
| split_ratio | int64 | 当日开盘前正向拆股倍数；无拆股填 1 |
| dividend | decimal128(24, 6) | 当日除息、每股现金分红；无分红填 0 |
| dividend_pay_date | date32，可空 | 实际支付日；无分红时为空 |

必须包含 Parquet schema 元数据：

```text
schema_version = invest.bars.v1
price_basis = raw
currency = USD
session_timezone = America/New_York
source = synthetic 或明确的数据提供者名称
```

代码可复用 `invest.market.BAR_SCHEMA` 构造表。`examples/generate.py` 给出完整写入示例。
如果分红和拆股发生在同一天，dividend 按拆股后的每股口径提供。仅前一交易日已持有的
股票获得分红；除息日开盘新买入的不获得。支付日遇到无输入记录的日期，在下一条日线
到来时入账；应收期间计入净值但不能用于买入。

拆股仅在发生日调整持仓、待成交数量和此前已知价格序列，不提前用未来拆股信息。
首版不支持反向拆股、分数股现金替代、股票分红、并购和退市清算；不能把这些事件填 1
或 0 静默略过。数据提供者必须核实企业行动后再导入。

日期必须唯一、递增，禁止周末记录；当前不会校验完整美股交易日历或补齐缺失日线。
缺失交易日会影响“下一条记录”成交的含义，因此真实数据必须先做外部完整性检查。
数据源名称属于可追踪信息，不等于已经完成真实性或时点正确性验证。

## 单序列分析

`invest analyze` 读取两列：`date: date32` 和数值型 `adjusted_close`，至少两行。
用于价格序列收益/回撤分析，不能作为 paper 账户的成交输入。调整口径由上游负责；
代码不会根据普通收盘价推断分红再投资收益。`examples/prices.parquet` 是人工样例。

## 账户数据完整性

每日更新提供完整累计历史。已处理记录、字段类型、来源元数据都不能被悄悄修改；
发现历史修订、引擎变化或参数变化时必须建立新账户进行对照，旧快照保留。
模型和数据变化不可用修改旧账本的方式混入同一条 paper 记录。
