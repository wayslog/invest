# invest

个人美股投资研究框架，使用 **Python 3.12 + uv + Parquet**。
当前提供单标的日线 paper 账户，以及共享现金的多 ETF 策略研究：
趋势/轮动、次日模拟成交、资金与风险核算、基准、样本外评价和可复现报告。演示和测试无需账户或密钥；
真实行情采集使用 Alpaca 的只读数据 API。

项目建设顺序、阶段验收和近期任务见 [项目总路线图](docs/roadmap.md)。
M0 工程原型已通过验收，见 [M0 验收记录](docs/milestones/m0.md)。
M1 已完成：SPY 真实历史数据、质量准入、发行方分红核对和账户回放通过本地验收，
见 [M1 验收记录](docs/milestones/m1.md)。当前版本 **`0.6.0`**，M2 已完成，
见 [M2 验收记录](docs/milestones/m2.md)。首轮选定候选的留出收益为 -1.20%，
未通过 M3 研究门槛；工程完成不表示策略可投入运行。
M3 持续账户、原子事件日志、每日任务及恢复演练已实现；正式策略观察仍待候选资格，
见 [M3 运行说明](docs/forward.md) 和 [阶段记录](docs/milestones/m3.md)。
SPY 待支付分红的采集范围已修复，真实现金观察账户已登记；新一轮长窗口探索仍未取得
策略资格，失败结果见 [R1 记录](docs/research/r1-long-horizon-results.md)。
0.6.0 已通过归档重放、备份和状态等值校验，将原现金账户迁移至新版；账户 ID、
5000 美元、净值高点、风险状态和旧日志均保留。Linux/systemd、Telegram 告警、心跳、
日结及备份已实现，新增 [GitHub Actions 部署](docs/github-actions-deployment.md)，
主机上线仍待 runner 接入和安全凭据；见 [运行与部署](docs/operations.md)。
失败候选的复盘及新未来验证方案见 [R1 复盘](docs/research/r1-postmortem.md)，
外部账户条件见 [T09 核查](docs/access/t09.md)。

## 快速开始

安装 [uv](https://docs.astral.sh/uv/getting-started/installation/)（验证版本 `0.12.23`），
在仓库根目录运行：

```bash
uv sync --locked --python 3.12
make demo
```

云环境如默认缓存目录不可写，先运行：

```bash
export UV_CACHE_DIR=/workspace/.cache/uv-invest
export MPLCONFIGDIR=/workspace/.cache/invest-matplotlib
```

`make demo` 使用明确标记为 `synthetic` 的人工数据，不代表真实股票或策略效果。
示例 Parquet 随仓库提供，可用 `uv run --locked python examples/generate.py` 重新生成。

也可以直接运行：

```bash
uv run --locked invest analyze examples/prices.parquet
uv run --locked invest paper \
  --data examples/paper_bars.parquet \
  --config configs/demo.toml \
  --account reports/paper-demo
```

命令返回本次快照目录。打开目录内的 `report.html` 查看净值、回撤和基准比较。
同样输入再次运行返回 `updated: false`，不新增成交或快照。
开发中修改引擎后，M1 合成演示使用新的目录，例如 `make demo DEMO_ACCOUNT=reports/paper-v2`。
M3 持续资金账户必须保留身份和风险历史，不能按此方式清零后接续。

## M3 持续账户与故障演练

```bash
make forward-demo
```

离线演练提前落盘的订单、延迟成交核算、重复任务、漏跑、暂停、风险锁和备份恢复。
真实数据可用于现金运行观察；正式策略模式强制检查 M2 研究资格。
逐日操作、调度器命令、报告和恢复限制见 [运行说明](docs/forward.md)。

## M2 多 ETF 研究

```bash
make research-demo
```

无需凭据即可生成合成数据、登记 6 个候选、运行 69 次比较并逐表重算核对。
打开 `reports/m2-demo/study/report.html` 查看净值、回撤、敞口、利润归因和全部失败结果。
目录不可覆盖，重复演示指定新的 `M2_DEMO_DIR`。

真实研究已对 SPY/XLF 完成发行方分红核对；原研究池中的 XLK 因不支持的 due-bill 行动
被隔离。训练/验证、2025 已知历史、2026 上半年历史留出及滚动检查分别报告；
候选选择在留出计算前保存。完整命令、字段及限制见 [研究使用说明](docs/research/README.md)
和 [首轮冻结方案](docs/research/m2-protocol.md)。研究结果统一保存为 Parquet。

## 单标的自有 paper 账户

首版是一套离线日线撮合和账户账本，可以回放历史，也可以在日线收齐后逐日追加更新。
更新时输入截至当日的**完整累计历史**；系统校验已处理部分没有变化，再重放计算并保存
新的完整快照。首版以正确性优先，没有引入单独的增量会计实现。

- `paper` 命令为单账户单标的、美元、整股、多头与现金；多标的历史实验使用 `research`。
- 收盘生成订单，仅在下一交易日开盘有效，计入固定每单费用和双向滑点。
- 现金不足会缩减买单；零成交量或缺失交易日会拒绝该段历史，保留原账本。
- 分红先计应收，在支付日才成为现金；支持整数倍正向拆股。
- 趋势退出、单仓止损、单仓利润回撤、账户高点回撤，以及本金警戒/终止。
- 账户状态和待成交订单跨运行保留；停用后不会因重启或价格反弹自行恢复。
- 基准使用相同预热期、仓位上限、成交费用和企业行动，随后持续持有。

`paper` 更新前强制检查日历、数据完整性和独立对账。日线开盘价仍是模拟成交代理，
没有盘口、税费、资金结算或券商订单状态模拟；真实数据批次仅用于有明确限制的历史研究。

## 真实历史数据流程

通过环境安全设置提供 `APCA_API_KEY_ID` 和 `APCA_API_SECRET_KEY`；云环境的凭据目的域名
只需 `data.alpaca.markets`。不要把值写入仓库、命令行或聊天。此流程不会提交券商订单。

```bash
uv run --locked invest fetch --symbol SPY \
  --start 2024-01-02 --end 2024-12-31 --feed sip --output data/alpaca
```

命令返回新批次路径、状态和错误摘要。`quarantined` 批次不可运行；`research_only`
表示当前结构、日历和映射检查通过，仍需核实历史发布时点及企业行动覆盖。
SIP 访问失败时不会自动改用 IEX，必须先确认账户数据权限和口径。

把返回的路径填入下列变量，再离线复现并回放：

```bash
m1_dataset="data/alpaca/实际批次编号"
uv run --locked invest verify-data --dataset "$m1_dataset"
uv run --locked invest capture-dividends --output data/ssga-source.parquet
uv run --locked invest audit-dividends --dataset "$m1_dataset" \
  --source data/ssga-source.parquet --output reports/spy-dividends.parquet
uv run --locked invest paper --dataset "$m1_dataset" \
  --dividend-source data/ssga-source.parquet \
  --config configs/spy-research.toml --account reports/spy-m1
```

`capture-dividends` 读取 State Street 公共分红表，原始响应仍保存在 Parquet 中；后续核对
和回放均可离线运行。输出已存在时拒绝覆盖，应复用现有来源或另存新版本。
指定 `--dividend-source` 后，分红日期、金额或支付日不一致会阻止账户更新，核对证据随
快照保存。M1 已验证 SPY 2021—2025 年；更早的缺字段/超精度事件有明确隔离记录。

逐日更新时可加 `--require-current`，缺少最近可接纳日线就拒绝更新。Alpaca 日线保守等到
该交易日的次日纽约时间 00:15；交易所收盘本身不代表供应方整日日线已完整。
这仍不保证发布时间或修订终结，历史回放不加此选项。
新批次保留旧数据；若发现历史价格或企业行动修订，旧账户拒绝接续，应另开研究目录对照。
M3 使用独立的 `forward-*` 命令记录真实接收/决策时间；引擎冻结，升级迁移仍需另行验收。
券商 paper 属于后续阶段。

## 数据、参数和输出

- 数据格式及复权/分红口径：[Parquet 数据约定](docs/data.md)。
- 日历与质量检查：[使用方法和检查边界](docs/data.md#交易日历与质量报告)。
- 真实行情来源：[M1 数据源评估记录](docs/data-sources.md)。
- 账户状态、默认研究参数、限制及验收范围：[Paper 账户说明](docs/paper.md)。
- 模块划分及后续方向：[架构说明](docs/architecture.md)。
- `configs/demo.toml` 中的参数是工程演示默认值，尚未经过有效性验证。

```text
reports/paper-demo/
├── CURRENT                    最新完整快照的编号
└── runs/<编号>/
    ├── bars.parquet           本次使用的全部行情
    ├── config.parquet         实际参数快照
    ├── manifest.parquet       引擎、输入文件校验值及版本
    ├── equity.parquet         每日现金、持仓、应收、净值、状态、待成交订单
    ├── trades.parquet         成交及决策日期、数量、价格、费用和原因
    ├── events.parquet         分红、拆股、拒单及风险事件
    ├── benchmark_trades.parquet
    ├── metrics.parquet        汇总指标
    ├── quality.parquet        账户输入的质量检查
    ├── reconciliation.parquet 策略及基准逐日独立对账
    ├── dividends.parquet      发行方分红核对（指定 --dividend-source 时）
    ├── dividend-source.parquet 对应的原始来源证据
    ├── dataset/               真实数据批次的完整副本（使用 --dataset 时）
    ├── equity.png             净值和回撤图
    └── report.html            报告
```

所有行情、账户和统计表均为 Parquet（Zstandard 压缩）。TOML 用于人工编辑参数；
`CURRENT` 只是原子切换快照的文本指针。报告和图像用于展示，不是数据存储格式。

## 开发与验证

```bash
make install     # 依据 uv.lock 安装
make check       # Ruff、格式校验、严格 mypy、pytest 和覆盖率
make demo        # Parquet 分析及 paper 账户
make research-demo # 多标的离线研究及完整复现
make forward-demo # 持续账户与合成故障演练
make build       # wheel 与源码包
```

`uv run` 自动使用 `.venv/`。修改依赖使用 `uv add` / `uv add --dev`，并一起提交
`pyproject.toml` 和 `uv.lock`。CI 运行相同检查，不依赖外部行情或凭据。
测试覆盖决策与成交时序、账目守恒、跳空、成本、风险退出、分红拆股、重启幂等及写入失败。

本地行情放在 `data/`，账户及研究输出放在 `reports/`，均默认忽略；公开合成样例放在
`examples/`。笔记本只用于探索，可复用逻辑放在 `src/invest/`。
