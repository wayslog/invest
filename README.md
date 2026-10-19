# invest

个人美股投资研究框架，使用 **Python 3.12 + uv + Parquet**。
当前提供单标的日线 paper 账户：均线信号、次日模拟成交、资金核算、风险退出、
买入持有基准，以及可持久化的账本与图表报告。运行无需券商账户或密钥。

项目建设顺序、阶段验收和近期任务见 [项目总路线图](docs/roadmap.md)。
当前已完成工程原型，下一阶段优先接入真实数据并核对单标的账户行为。

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
开发中修改引擎后，应使用新的账户目录，例如 `make demo DEMO_ACCOUNT=reports/paper-v2`。

## 自有 paper 账户

首版是一套离线日线撮合和账户账本，可以回放历史，也可以在日线收齐后逐日追加更新。
更新时输入截至当日的**完整累计历史**；系统校验已处理部分没有变化，再重放计算并保存
新的完整快照。首版以正确性优先，没有引入单独的增量会计实现。

- 单账户单标的、美元、整股、多头与现金；当前不支持多标的组合、空头或杠杆。
- 收盘生成订单，后续交易日开盘模拟成交，计入固定每单费用和双向滑点。
- 现金不足会缩减买单；无成交量时保留待成交订单，不凭空成交。
- 分红先计应收，在支付日才成为现金；支持整数倍正向拆股。
- 趋势退出、单仓止损、单仓利润回撤、账户高点回撤，以及本金警戒/终止。
- 账户状态和待成交订单跨运行保留；停用后不会因重启或价格反弹自行恢复。
- 基准使用相同预热期、仓位上限、成交费用和企业行动，随后持续持有。

这些是日线模拟假设，不代表真实成交。没有实时行情采集、交易日完整性验证、订单簿、
税费或券商订单状态处理，不能把模拟数据直接解释为实盘收益。

Alpaca 暂不作为依赖。下一步先接入经过校验的真实日线数据，再做前向 paper 观察；
需要验证外部订单提交、撤单、部分成交和核对时，再增加券商 paper 适配器。

## 数据、参数和输出

- 数据格式及复权/分红口径：[Parquet 数据约定](docs/data.md)。
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
make build       # wheel 与源码包
```

`uv run` 自动使用 `.venv/`。修改依赖使用 `uv add` / `uv add --dev`，并一起提交
`pyproject.toml` 和 `uv.lock`。CI 运行相同检查，不依赖外部行情或凭据。
测试覆盖决策与成交时序、账目守恒、跳空、成本、风险退出、分红拆股、重启幂等及写入失败。

本地行情放在 `data/`，账户及研究输出放在 `reports/`，均默认忽略；公开合成样例放在
`examples/`。笔记本只用于探索，可复用逻辑放在 `src/invest/`。
