# P1：研究数据与第三方库接入

日期：2026-10-23。实现基于 `ea96367` 的重构方案，使用 Python 3.12。
状态：P1 本地离线验收通过，尚未部署。
P1 只贯通数据和研究接口；因子搜索、策略组合、资金回测和选股动作属于后续阶段。

## 安装与离线演示

```bash
uv sync --locked --python 3.12 --group research
make quant-data-demo P1_DEMO_DIR=reports/p1-data-example
```

`research` 组固定 `pyqlib==0.9.7`、`alphalens-reloaded==0.5.0`，传递依赖由 `uv.lock`
锁定。`make install` 和 `make test` 包含该组，现有独立 IBKR SDK 环境不变。
Qlib 的传递依赖包含 MLflow、Jupyter 等包；P1 不启动这些服务，不使用远程数据服务。

演示使用明确标记的合成股票、XNYS 交易日历和美元价量，输出目录必须尚不存在。
它生成研究快照、因子、未来价格收益标签、Qlib 数据集视图和 Alphalens RankIC，
不需要行情 API、账户凭据，不读写资金账户。高 RankIC 来自构造的样例，不是投资证据。

产物包括 `snapshot/*.parquet`、`factors.parquet`、`labels.parquet`、
`qlib_dataset.parquet`、`rank_ic.parquet` 和 `diagnostics.parquet`。
所有表使用 Zstandard；Qlib 原生缓存位于 `data/cache/qlib/<cache_id>/`。

## 统一接口

| 模块 | 公开入口 | 责任 |
| --- | --- | --- |
| `contracts.py` | `SnapshotSpec`、`DataSnapshot`、`FactorFrame`、`LabelFrame` | Arrow schema、来源与快照引用、因子/标签分离 |
| `research_data.py` | `create_snapshot`、`load_snapshot`、`snapshot_from_ibkr` | 校验、不可覆盖的 Parquet 快照、IBKR 采集适配 |
| `qlib_adapter.py` | `build_qlib_cache`、`calculate_factors` | 原生缓存、因果表达式、Qlib 状态隔离、因子表 |
| `factor_diagnostics.py` | `forward_labels`、`qlib_dataset_frame`、`diagnose_factor` | 次日开盘标签、Qlib 视图、Alphalens 对齐与 RankIC |

`create_snapshot` 接收符合 `RESEARCH_BARS` 和 `UNIVERSE` 的 Arrow 表。已有 Parquet
可先用 `pyarrow.parquet.read_table` 读取再传入，不能把旧 `invest.bars.v1` 或券商原始表
仅改名后视为新契约。真实 IBKR 采集使用专门的适配入口：

```python
from pathlib import Path

from invest.factor_diagnostics import diagnose_factor, forward_labels, qlib_dataset_frame
from invest.qlib_adapter import calculate_factors
from invest.research_data import snapshot_from_ibkr

snapshot = snapshot_from_ibkr(
    Path("data/ibkr/capture-directory"),
    Path("data/research/new-snapshot"),
    allow_exploratory=True,
)
factors = calculate_factors(snapshot, {"momentum": "$close/Ref($close,5)-1"})
labels = forward_labels(snapshot, (1, 5))
inference = qlib_dataset_frame(factors, allow_exploratory=True)
training = qlib_dataset_frame(factors, labels, allow_exploratory=True)
diagnostics = diagnose_factor(
    factors,
    labels,
    "momentum",
    quantiles=5,
    max_loss=0.35,
    allow_exploratory=True,
)
```

上例需要足够的交易日和横截面股票数才能通过分组、覆盖门槛；不足时会拒绝评价。
输出表通过 `frame.table` 访问；写入新实验目录后，可用 `FactorFrame` / `LabelFrame`
包装读取回来的 Parquet 表并重新验证契约。`qlib_dataset_frame` 返回 pandas，
可以直接交给 `StaticDataLoader`，也可以用 `to_parquet(..., compression="zstd")` 保存后
由该加载器读取，再接 `DataHandlerLP` / `DatasetH`。推断接口默认不包含未来标签。

Qlib 视图与 Alphalens 的清洗表、RankIC 表均通过 `DataFrame.attrs["invest"]` 保留
`snapshot_id`、`source`、`price_basis`、`input_scope`、`scope`、`timing_policy`、
`allow_exploratory`、`unknown_timing_rows` 和 `timing_rejected_rows`。这些字段不会混入
模型特征；使用上述 pandas/Parquet 路径保存和加载时，元数据随表往返。
`input_scope` 保存原输入范围，`scope` 表示本次输出范围。若显式接受未知时点的有效值，
输出降为 `exploratory`，原来源及输入范围不变，也不回写或重标原快照与研究表。
未知时点及拒绝数量按长表中的有效因子值计数，不将预热空值重复计为时点拒绝。

## 时间、价格和准入

- `date` 是 XNYS 会话日期，不是 UTC 自然日；研究视图统一为无时区的纳秒日期索引。
  `available_at`、`captured_at`、标签入场/退出时间为 UTC 时间戳。
- 证券使用稳定的大写 ID，IBKR 采用 `IBKR<con_id>`，展示 symbol 保留在股票池表。
  股票池区间不得重叠；区间内缺少日线直接拒绝，不前向填充停牌或缺失行情。
- 权威 OHLCV 使用 `decimal128(38,18)`；价格为美元，成交量单位单独声明。
  Qlib 原生缓存使用 float32，因子与收益表使用 float64。浮点表示不能反向生成账本。
- P1 表达式支持声明的 OHLCV 字段、四则运算和有限的 Ref/滚动/相关等算子。
  负数或零窗口 Ref、未来字段、未声明算子和任意代码拒绝进入 Qlib；完整回看窗口不足时
  因子值为空。因子可用时间取所需输入及股票池声明的最晚时间，未知时点保持未知。
- H 会话标签：t 收盘形成特征，t+1 会话开盘入场，t+1+H 会话开盘退出，记录价格收益比例。
  标签继承快照的价格调整口径，不等于含费用、现金分红与整股限制的账户收益。
- Qlib 和 Alphalens 共用一套准入规则：决策截点为因子所属 XNYS 会话的实际收盘时刻，
  包含夏令时与提前收盘。仅 `available_at <= close_at` 的已知值可用；收盘后才可得的值
  置为空，即使早于次日入场、显式允许探索也不例外。有无标签、标签期限和末端缺失标签
  都不改变该截点。默认剔除未知可用时间；使用未知值必须设置 `allow_exploratory=True`，
  已声明为 `exploratory` 的输入也必须显式许可。探索只放宽未知证据，不放宽已知晚到。
- Alphalens 仅接项目生成的未来收益表，当前交付清洗、分组和 RankIC；没有把因子收益
  替换成项目组合回测。丢样率分母保留原始因子行，包含预热、缺失标签、时点拒绝和分组丢样。

IBKR 适配器核对采集 schema、来源、账户环境、捕获时间和合约身份，只接受完整采集中的
美元、常规时段、拆股调整日线 TRADES。它不把 `captured_at` 填成历史 `available_at`。
当前采集仍缺历史可得时间、历史股票池、已验证成交量单位和现金分红收益口径，必须明确
选择 `allow_exploratory=True` 才能生成受限快照；真实来源标为 `exploratory`，合成来源保持
`synthetic` 并保留缺口。其他供应商只能作为带原来源的历史参考，不自动并入 IBKR。

所有 P1 快照均为 `account_eligible=false`。完整企业行动和可交易性验证尚未完成，
不能将研究快照直接送入旧账户会计或据此宣称真实策略通过验收。

## 缓存与历史保护

发布包未包含官方 `scripts/dump_bin.py`，因此使用 Qlib 自带的 `FileFeatureStorage`
写入 `.bin`，配套生成其默认 provider 要求的日历和股票池文件。不复制 Qlib 源码、
不引入自定义 provider，也不在运行时下载转换脚本。

缓存 ID 绑定快照内容及来源/单位/调整口径、转换版本、Qlib/NumPy/pandas 版本、频率和字段。
修改缓存生成语义时必须更新 `CONVERTER_VERSION`；仅修改报告展示不改变这个版本。
同一输入复用缓存；不同快照、口径或转换版本使用不同目录。文件损坏会拒绝复用，不自动
覆盖目录。可删除对应 `data/cache/qlib/<cache_id>/` 后重建，不能删除整个 `data/` 或研究目录。
本阶段不启用 Qlib 的持久化表达式缓存；内存缓存在每次切换前清空。

本模块串行使用 Qlib 全局配置，不支持调用者同时直接修改 Qlib 配置；计算后恢复 NumPy
错误策略。缓存构建以目录为单位发布，失败只清理本次临时目录。新快照拒绝覆盖既有路径，
重新读取时核对内容和身份，过期的 `DataSnapshot` 引用不能静默指向替换后的数据。

旧账户、注册、journal、风险历史、来源、失败研究与样本外记录没有迁移或重写。
旧引擎指纹算法保持不变；新增 Python 模块会改变源码摘要，历史账户仍须使用原冻结版本，
不能用当前开发代码自动续跑或清零。M1 和前向演示使用新的合成目录。

## 首次接入验证记录

开发环境为 Python 3.12.13、NumPy 2.5.4、pandas 3.0.6、PyArrow 24.0.0。
新增真实库集成测试覆盖精度往返、缺失与重复数据、时点与来源、缓存重建及隔离、
因果表达式、未来数据追加不变性、Qlib 数据集、Alphalens 手算 RankIC、离线运行和历史保留。

| 检查 | 结果 |
| --- | --- |
| `uv sync --locked --python 3.12 --group research` | 锁定依赖安装通过 |
| `make check` | Ruff、格式、严格 mypy 通过；388 项测试全部通过，覆盖率 87% |
| P1 集成测试 | 25 项通过，调用真实 Qlib、Alphalens，包含断开网络后的完整数据路径 |
| `make quant-data-demo P1_DEMO_DIR=reports/p1-data-20261023` | 合成数据全链路通过；momentum 诊断输入 115 行、保留 75 行，丢样 34.8% |
| `make demo DEMO_ACCOUNT=reports/p1-paper-20261023` | 原纸面账户引擎在新的合成目录运行通过 |
| `make forward-demo M3_DEMO_DIR=reports/p1-forward-20261023` | 前向演示通过，106 项对账检查 |
| `make build` | wheel 和源码包构建通过，包含新增研究模块 |
| 历史保留 | 变更前本地 `data/`、`reports/` 下的 7 个既有文件内容未变；未操作部署主机或真实账户 |

本地检查日志保存在忽略 Git 的 `reports/p1-validation-20261023/`，包括最终完整检查
`check-verified.log` 和原失败记录。此前依赖宿主命令的部署、重启测试已补齐 systemctl、
flock 模拟；端口错误测试分别验证连接拒绝与超时，避免依赖 macOS 的具体返回方式。
生产部署脚本与财务引擎逻辑未修改。

这些结果证明本地工程接入和离线行为，不证明真实行情已经具备回测准入条件，也不代表
因子搜索、完整策略回测、选股动作或实盘能力已完成。

## 审阅后时点准入修复

Qlib 和 Alphalens 已统一使用上述收盘截点。新增 10 项回归，覆盖收盘边界、入场时点、
已知未来信息、末端无标签、夏令时、提前收盘、未知时点探索许可，以及来源与范围经过
Parquet、`StaticDataLoader`、`DataHandlerLP` / `DatasetH` 后仍然保留。

- `make check`：Ruff、格式、严格 mypy 通过；398 项测试通过，覆盖率 87%；其中 P1 为 35 项。
- `make quant-data-demo P1_DEMO_DIR=reports/p1-timing-demo-20261023`：新目录下研究演示通过，
  数据集、RankIC 和诊断摘要均保留准入元数据。
- `make demo DEMO_ACCOUNT=reports/p1-timing-paper-20261023` 与 `make build`：通过。
- 修复前本地 `data/`、`reports/` 下的 494 个既有文件逐一校验，内容未变、没有缺失；
  没有迁移、重写或重标历史账户与研究记录。

本轮日志位于忽略 Git 的 `reports/p1-timing-fix-20261023/`，最终完整检查为
`check-verified.log`，历史保留核验为 `history-check.log`。中间检查日志也已保留：
先修正新增测试中的 pandas 类型推断问题；随后沙箱限制 PyArrow 读取 macOS CPU 信息，
导致既有 CLI 的 stderr 断言失败，最终在普通本机权限下完整重跑通过，没有放宽该断言。
