"""三个研究入口的统一中文报告；只展示正式 Parquet，不创建第二套计算口径。"""

from datetime import datetime
from html import escape
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import pyarrow.parquet as pq
from matplotlib.figure import Figure


def _value(value: Any) -> str:
    if value is None:
        return "缺失"
    if isinstance(value, datetime):
        return value.astimezone(ZoneInfo("Asia/Shanghai")).isoformat(timespec="seconds")
    if isinstance(value, float):
        return f"{value:.6g}"
    return str(value)


def _table(directory: Path, name: str, columns: list[tuple[str, str]], limit: int = 100) -> str:
    path = directory / f"{name}.parquet"
    if not path.exists():
        return "<p>尚无此项结果。</p>"
    table = pq.read_table(path)
    columns = [(key, label) for key, label in columns if key in table.column_names]
    heads = "".join(f"<th>{escape(label)}</th>" for _, label in columns)
    rows = "".join(
        "<tr>" + "".join(f"<td>{escape(_value(row[key]))}</td>" for key, _ in columns) + "</tr>"
        for row in table.slice(0, limit).to_pylist()
    )
    note = f"共 {table.num_rows} 行，显示前 {min(limit, table.num_rows)} 行。"
    return (
        f'<p>{note} <a href="{name}.parquet">完整 Parquet</a></p>'
        f'<div class="scroll"><table><thead><tr>{heads}</tr></thead>'
        f"<tbody>{rows}</tbody></table></div>"
    )


def _equity_chart(directory: Path) -> str:
    if not (directory / "equity.parquet").is_file():
        return ""
    figure = Figure(figsize=(10, 5), layout="constrained")
    axes = figure.subplots(2, 1, sharex=True)
    for scenario, prefix in (
        ("strategy", ""),
        ("equal_weight", "equal_weight_"),
        ("cash", "cash_"),
        ("double_cost", "double_cost_"),
    ):
        rows = pq.read_table(directory / f"{prefix}equity.parquet").to_pylist()
        dates = [row["date"] for row in rows]
        axes[0].plot(dates, [float(row["equity"]) for row in rows], label=scenario)
        axes[1].plot(dates, [float(row["drawdown"]) * 100 for row in rows])
    axes[0].set_ylabel("Equity (USD)")
    axes[1].set_ylabel("Drawdown (%)")
    axes[0].legend()
    for axis in axes:
        axis.grid(alpha=0.2)
    figure.savefig(directory / "equity.png", dpi=130)
    return (
        "<p>strategy：策略；equal_weight：同风险规则等权参考；cash：现金；"
        'double_cost：双倍费用与滑点。</p><img src="equity.png" alt="净值与回撤">'
    )


def write_quant_report(directory: Path, kind: str, record: dict[str, Any]) -> None:
    titles = {"mining": "因子挖掘", "backtest": "策略回测", "decision": "选股与动作"}
    title = titles[kind]
    source = pq.read_schema(directory / "run.parquet").metadata or {}
    scope = record.get("scope") or source.get(b"scope", b"unknown").decode()
    provider = record.get("source") or source.get(b"source", b"unknown").decode()
    history = record.get("history_status", record.get("holdout_status", "unknown"))
    limitations = list(
        dict.fromkeys(
            [
                *record.get("limitations", []),
                *record.get("source_limitations", []),
            ]
        )
    )
    body = (
        f'<p class="eyebrow">量化研究 · {escape(str(record["status"]))}</p><h1>{title}</h1>'
        '<p class="notice">研究用途。工程流程完成不表示策略有效或盈利；'
        "建议不是已提交订单，模拟成交不是券商确认。数据资格、策略证据与工程状态分别判断。</p>"
        f"<p>来源：{escape(str(provider))} · 数据范围：{escape(str(scope))} · "
        f"历史状态：{escape(str(history))}</p>"
        f"<p>运行：<code>{escape(str(record['run_id']))}</code> · "
        '<a href="run.parquet">运行记录 Parquet</a> · <a href="config.toml">冻结配置</a></p>'
        "<p>金额为美元，股数为整股，收益率与覆盖率为比例；0.1 表示 10%。"
        "表中时刻显示为北京时间（UTC+8），Parquet 保存 UTC。评分是排名组合，不是获利概率。</p>"
    )
    if record.get("error"):
        body += f'<p class="notice">失败：{escape(record["error"])}</p>'
    if kind == "mining":
        body += (
            f"<h2>筛选结果</h2><p>{record.get('candidates', 0)} 个候选，"
            f"{record.get('selected', 0)} 个入池。</p>"
        )
        if not record.get("selected"):
            body += '<p class="notice">没有合格因子；不生成买入计划。保留全部淘汰原因。</p>'
        body += _table(
            directory,
            "trials",
            [
                ("trial_id", "试验"),
                ("factor", "因子"),
                ("expression", "表达式"),
                ("status", "结果"),
                ("reason", "原因"),
                ("train_ic", "训练 RankIC"),
                ("validation_ic", "验证 RankIC"),
                ("validation_coverage", "验证覆盖"),
                ("max_correlation", "最大相关"),
                ("incremental_ic", "组合增量"),
            ],
        )
        body += "<h2>冻结因子池</h2>" + _table(
            directory,
            "factor_pool",
            [
                ("factor", "因子"),
                ("expression", "表达式"),
                ("direction", "方向"),
                ("weight", "权重"),
            ],
        )
        body += (
            '<p><a href="diagnostics.parquet">Alphalens 分组收益、换手与稳定性诊断 Parquet</a></p>'
        )
    elif kind == "backtest":
        body += (
            "<h2>成本后评价与参考组合</h2>"
            + _table(
                directory,
                "metrics",
                [
                    ("scenario", "情景"),
                    ("final_equity", "期末净值"),
                    ("total_return", "净收益率"),
                    ("max_drawdown", "最大回撤"),
                    ("sharpe_zero_rf", "Sharpe（无风险率 0）"),
                    ("commissions", "佣金"),
                    ("two_way_turnover", "双边换手"),
                    ("closed_cycles", "完整交易"),
                    ("wins", "胜"),
                    ("losses", "负"),
                    ("win_rate", "胜率"),
                    ("average_r", "平均 R"),
                ],
            )
            + _equity_chart(directory)
        )
        body += (
            "<p>胜负按从空仓到再次空仓的完整周期评定，含费用和分红权益。"
            "未平仓计入净值，不计胜率。R 是净损益除以事前止损风险预算；跳空损失可能超过 1R。</p>"
        )
        body += "<h2>分年结果</h2>" + _table(
            directory,
            "yearly",
            [
                ("year", "年份"),
                ("total_return", "策略收益"),
                ("market_return", "等权参考收益"),
                ("observations", "会话数"),
            ],
        )
        body += "<h2>完整交易</h2>" + _table(
            directory,
            "round_trips",
            [
                ("symbol", "证券"),
                ("opened_on", "入场"),
                ("date", "离场"),
                ("realized_pnl", "净损益"),
                ("outcome", "胜负"),
                ("r_multiple", "R"),
            ],
        )
        checks = pq.read_table(directory / "checks.parquet")
        body += (
            f"<p>独立对账：{checks.num_rows} 项，错误 "
            f"{checks['status'].to_pylist().count('error')} 项。"
            '<a href="checks.parquet">对账 Parquet</a></p>'
        )
    if kind == "decision":
        body += (
            f"<p>决策会话：{escape(str(record['as_of']))} · "
            f"账户：{escape(str(record['account_id']))} · "
            f"状态来源：{escape(str(record['context_kind']))}</p>"
        )
        body += "<h2>股票排名与覆盖</h2>" + _table(
            directory,
            "rankings",
            [
                ("symbol", "证券"),
                ("rank", "排名"),
                ("score", "评分"),
                ("selected", "目标持有"),
                ("coverage", "因子覆盖"),
                ("action", "动作"),
                ("reason", "原因"),
                ("exit_reason", "未完成退出需求"),
            ],
        )
        body += "<h2>因子贡献</h2>" + _table(
            directory,
            "contributions",
            [
                ("instrument", "证券"),
                ("factor", "因子"),
                ("value", "原值"),
                ("scaled_rank", "横截面秩"),
                ("weight", "权重"),
                ("direction", "方向"),
                ("contribution", "评分贡献"),
                ("admitted", "时点准入"),
            ],
        )
    if kind in {"decision", "backtest"}:
        body += "<h2>动作与退出条件</h2>" + _table(
            directory,
            "actions",
            [
                ("date", "决策日"),
                ("instrument", "证券"),
                ("action", "动作"),
                ("current_quantity", "当前股数"),
                ("target_quantity", "目标股数"),
                ("quantity", "变动股数"),
                ("reference_price", "参考原价"),
                ("stop_price", "止损参考"),
                ("take_profit_price", "止盈参考"),
                ("max_holding_sessions", "最长持有会话"),
                ("exit_mode", "退出模式"),
                ("effective_at", "生效"),
                ("expires_at", "到期"),
                ("reason", "原因"),
                ("exit_reason", "退出需求"),
                ("cancel_pending", "需取消待处理单"),
            ],
        )
        body += (
            "<p>BUY/ADD 为买入/加仓，TRIM/SELL 为减仓/卖出，HOLD 为持有，WAIT 为等待。"
            "WAIT 不表示风险已经处理。待处理订单需要另行确认；本工具不会取消或提交订单。"
            "价格为决策时参考，下一会话开盘可能跳空；新仓止损止盈须按实际成交更新。"
            "close 在收盘确认后下一开盘退出；protective 的保护规则是假设，不代表券商已挂单。</p>"
        )
    body += (
        "<h2>证据范围与限制</h2><ul>"
        + "".join(f"<li>{escape(str(item))}</li>" for item in limitations)
        + "</ul><p>真实数据准入需分别证明 IBKR 来源、历史可得时点、股票池、原价与企业行动、"
        "股数单位和账户快照来源。本报告不以声明代替外部验证，不修改既有样本外状态。</p>"
    )
    document = (
        '<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        f"<title>{title}</title><style>"
        "body{font:16px/1.65 system-ui,sans-serif;color:#21313b;background:#f5f4ef;margin:0}"
        "main{max-width:1180px;margin:auto;padding:48px 28px}h1{font-size:36px;margin:4px 0 20px}"
        "h2{font-size:23px;margin-top:40px}a{color:#176d68}.eyebrow{letter-spacing:.1em;color:#176d68}"
        ".notice{border-left:4px solid #ac672a;background:#fff4e3;padding:14px 18px}"
        ".scroll{overflow:auto;background:white}table{border-collapse:collapse;width:100%}"
        "th,td{padding:10px 13px;text-align:left;border-bottom:1px solid #dde3df;"
        "white-space:nowrap}"
        "th{background:#e6ede9}code{word-break:break-all}img{max-width:100%;background:white}"
        "</style></head><body><main>" + body + "</main></body></html>"
    )
    (directory / "report.html").write_text(document, encoding="utf-8")
