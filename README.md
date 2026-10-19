# invest

个人美股投资研究框架，使用 **Python 3.12 + uv**。
当前提供可复现的开发环境、CSV 数据校验、单资产区间收益/最大回撤计算和命令行入口。

## 快速开始

先安装 [uv](https://docs.astral.sh/uv/getting-started/installation/)；本项目验证版本为
`0.12.23`。在仓库根目录运行：

```bash
uv sync --locked --python 3.12
uv run --locked invest analyze examples/prices.csv
```

`uv` 会使用 Python 3.12 创建本地 `.venv/`，安装项目和开发依赖。
不需要手动激活环境；IDE 选择 `.venv/bin/python`（Windows 为 `.venv/Scripts/python.exe`）。
云环境已经提供 Python 3.12 和 uv；如其缓存目录不可写，可先设置
`export UV_CACHE_DIR=/workspace/.cache/uv-invest`。

`examples/prices.csv` 是人工构造的演示数据，不代表任何股票的实际行情。
输出包含 5 个观测点、区间收益约 `0.03`（3%）、最大回撤约 `-0.029412`（-2.94%）。
也可以使用 `uv run --locked python -m invest analyze examples/prices.csv`。

## 数据约定

每个 CSV 代表一个资产的日线价格，至少两行，必需列为：

```csv
date,adjusted_close
2024-01-02,100.00
2024-01-03,102.00
```

日期必须是唯一、递增的 `YYYY-MM-DD`；价格必须是有限正数。缺失交易日不会自动补齐。
区间收益 = 末值 / 初值 − 1；最大回撤 = 各观测点价格相对历史峰值跌幅的最小值。
输出是比例，不是百分数；回撤为负数或零。输入价格的复权口径由数据提供者负责。
当前功能无需密钥、数据库或外部服务。

## 开发

```bash
make install     # 根据 uv.lock 安装依赖
make check       # Ruff 检查和格式校验、mypy、pytest（含覆盖率）
make demo        # 离线示例
make build       # 构建 wheel 和源码包到 dist/
```

不使用 Make 时，可运行对应命令：

```bash
uv run --locked ruff check .
uv run --locked ruff format --check .
uv run --locked mypy
uv run --locked pytest --cov=invest --cov-report=term-missing
uv build
```

修改依赖使用 `uv add <package>` / `uv add --dev <package>`；升级时运行
`uv lock --upgrade` 并验证完整检查。依赖声明和 `uv.lock` 一起提交，日常安装使用
`--locked`，避免无意更新锁文件。推送和 Pull Request 会触发相同的 GitHub Actions 检查。

## 目录

```text
src/invest/    可安装的 Python 包与命令行
tests/        数据边界、计算结果及命令行集成测试
examples/     可提交的离线示例数据
data/         本地数据（默认忽略）
reports/      分析输出（默认忽略）
notebooks/    探索性研究说明
docs/         架构与研究约定
```

后续模块划分与统计口径见 [架构说明](docs/architecture.md)。
