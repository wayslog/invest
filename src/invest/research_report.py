"""Chinese research report: complete comparisons, attribution and net-equity charts."""

from html import escape
from pathlib import Path
from typing import Any

import pyarrow.parquet as pq
from matplotlib.figure import Figure

from invest.research_registry import read_registration


def _table(rows: list[dict[str, Any]], columns: list[tuple[str, str]]) -> str:
    header = "".join(f"<th>{escape(label)}</th>" for _, label in columns)
    body = []
    for row in rows:
        cells = []
        for key, _ in columns:
            value = row[key]
            if isinstance(value, float):
                value = f"{value:.4f}"
            cells.append(f"<td>{escape(str(value))}</td>")
        body.append("<tr>" + "".join(cells) + "</tr>")
    return "<div class='scroll'><table><tr>" + header + "</tr>" + "".join(body) + "</table></div>"


def render_study(directory: Path) -> None:
    manifest = pq.read_table(directory / "manifest.parquet").to_pylist()[0]
    config, _, _ = read_registration(
        directory / "registration.parquet", required_engine=manifest["engine_sha256"]
    )
    initial = format(config.initial_cash.normalize(), "f")
    allocation = format((config.allocation * 100).normalize(), "f")
    position_cap = format((config.position_cap * 100).normalize(), "f")
    rows = pq.read_table(directory / "comparison.parquet").to_pylist()
    selected = manifest["selected_candidate"]
    admission = pq.read_table(directory / "admission.parquet").to_pylist()
    gates = pq.read_table(directory / "eligibility.parquet").to_pylist()
    charts = []
    for phase in ["validation", "holdout"]:
        figure = Figure(figsize=(11, 9), layout="constrained")
        axes = figure.subplots(3, 1, sharex=True)
        for row in rows:
            if row["phase"] != phase or row["candidate"] not in {
                selected,
                "equal_weight",
                "buy_hold",
                "market",
                "cash",
            }:
                continue
            equity = pq.read_table(directory / row["run"] / "equity.parquet").to_pylist()
            dates = [r["date"] for r in equity]
            axes[0].plot(dates, [float(r["equity"]) for r in equity], label=row["candidate"])
            axes[1].plot(dates, [r["drawdown"] * 100 for r in equity])
            axes[2].plot(dates, [r["gross_exposure"] * 100 for r in equity])
        for axis, label in zip(axes, ["Equity (USD)", "Drawdown (%)", "Exposure (%)"], strict=True):
            axis.set_ylabel(label)
            axis.grid(alpha=0.2)
        axes[0].legend(loc="best")
        figure.savefig(directory / f"{phase}.png", dpi=130)
        charts.append(
            f'<h2>{phase}</h2><img src="{phase}.png" '
            f'alt="{phase} net equity, drawdown and exposure">'
        )
    attribution_rows: list[dict[str, Any]] = []
    period_rows: list[dict[str, Any]] = []
    for row in rows:
        if (
            row["phase"] in {"train", "validation", "reused", "holdout"}
            and row["candidate"] == selected
        ):
            attribution = pq.read_table(directory / row["run"] / "attribution.parquet").to_pylist()
            final_date = max(r["date"] for r in attribution)
            attribution_rows.extend(
                {"phase": row["phase"], **r} for r in attribution if r["date"] == final_date
            )
            period_rows.extend(
                {"phase": row["phase"], **r}
                for r in pq.read_table(directory / row["run"] / "periods.parquet").to_pylist()
            )
    metrics = _table(
        rows,
        [
            ("phase", "区间/用途"),
            ("candidate", "候选"),
            ("cost_multiplier", "成本倍数"),
            ("gap_bps", "不利成交 bps"),
            ("total_return", "净收益率"),
            ("max_drawdown", "最大回撤"),
            ("annualized_volatility", "年化波动"),
            ("sharpe_zero_rf", "Sharpe (rf=0)"),
            ("max_underwater_sessions", "最长未创新高交易日"),
            ("unrecovered_at_end", "期末仍未恢复"),
            ("two_way_turnover", "双边换手"),
            ("average_exposure", "平均股票敞口"),
            ("trade_count", "成交数"),
            ("top3_positive_realized_share", "前三盈利平仓占盈利总额"),
            ("status", "账户状态"),
        ],
    )
    eligibility = (
        "通过研究门槛；仍须 M3 前向协议"
        if manifest["m3_research_eligible"]
        else "未通过进入 M3 的研究门槛"
    )
    body = (
        '<!doctype html><html lang="zh-CN"><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        "<title>M2 投资框架研究</title><style>"
        "body{font:16px/1.6 system-ui;max-width:1300px;margin:32px auto;"
        "padding:0 20px;color:#1a2836}"
        "table{border-collapse:collapse;font-size:14px}"
        "th,td{padding:7px;border:1px solid #ccd4db;white-space:nowrap}"
        "th{background:#edf2f5}.scroll{overflow:auto}img{width:100%;max-width:1100px}code{overflow-wrap:anywhere}"
        "</style><h1>M2 多标的投资研究</h1>"
        f"<p>研究：{escape(manifest['study_id'])}；范围：{escape(manifest['scope'])}。"
        f"按验证净收益选出 <b>{escape(selected)}</b>。<b>{eligibility}</b>。</p>"
        f"<p>所有账户独立从登记本金 {initial} 美元起步。train/validation/reused 是已知历史；"
        "holdout 在保存选择后才计算。walk 每折仅用上一年选参，不能拼接成连续实盘收益。"
        "成本压力同时倍增佣金和滑点；gap 是验证期每笔成交买入 +5%、卖出 −5% 的价格压力，"
        "不是市场发生该路径的概率。现金基准收益设为零，未计税与利息。</p>"
        f"<p>策略目标 {allocation}% 总敞口、{position_cap}% 单仓；"
        f"等权与买入持有基准的目标总敞口同为 {allocation}%，"
        "市场基准为 100% SPY。策略退出及相关筛查会降低实际平均敞口；应结合敞口图比较，"
        "不可把仓位差异称为 alpha。全部标的属于美国股票风险组，"
        "有成分重叠和固定存续 ETF 选择偏差。</p>"
        "<p>信号只用当日及以前的价格和行动；开盘成交是日线代理。发行方分红核对不等于完整历史"
        "point-in-time 数据，公告时点未知；历史留出结果不替代未来观察。合成结果只证明工程行为。</p>"
        "<h2>准入</h2>"
        + _table(admission, [("symbol", "标的"), ("admitted", "准入"), ("reason", "原因")])
        + "<h2>研究门槛</h2>"
        + _table(gates, [("check", "检查"), ("passed", "通过"), ("detail", "证据")])
        + "".join(charts)
        + "<h2>全部候选、基准与压力结果</h2><p>比率使用小数；0.10 表示 10%。"
        "最长未创新高交易日包含未恢复的尾段；前三盈利平仓占比只以正的已实现利润为分母，"
        "不能表示对总净利润的贡献；未平仓部分另列。</p>"
        + metrics
        + "<h2>选定候选按标的利润归因（含未平仓）</h2>"
        + _table(
            attribution_rows,
            [
                ("phase", "区间"),
                ("symbol", "标的"),
                ("shares", "期末股数"),
                ("realized_pnl", "已实现净利润"),
                ("unrealized_pnl", "未实现利润"),
                ("dividend_income", "已获得分红权益"),
                ("total_pnl", "总利润"),
                ("fees", "佣金"),
            ],
        )
        + "<h2>年度表现及预定义市场环境</h2>"
        + _table(
            period_rows,
            [
                ("phase", "用途"),
                ("year", "年份"),
                ("total_return", "策略净收益率"),
                ("market_return", "SPY 净收益率"),
                ("market_regime", "SPY 涨跌环境"),
            ],
        )
        + "<p>每次运行的 Parquet 保存净值、持仓、订单、成交、事件、相关筛查、独立对账、"
        "逐日利润归因、平仓利润和指标。files.parquet 覆盖输入与输出；"
        "engine-source.parquet 保存引擎代码。"
        "所有失败批次、负收益和停用状态保留。详情见项目 M2 研究方案。</p>"
        f"<p>引擎 SHA-256：<code>{manifest['engine_sha256']}</code><br>"
        f"配置 SHA-256：<code>{manifest['config_sha256']}</code></p></html>"
    )
    (directory / "report.html").write_text(body, encoding="utf-8")
