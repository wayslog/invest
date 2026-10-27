"""两轮股票关注列表：原始证据、Qlib 因子、解释性评分与拒绝原因统一冻结。"""

from __future__ import annotations

import html
import shutil
import tomllib
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from invest.contracts import UNIVERSE, SnapshotSpec, research_schema
from invest.engine import engine_digest
from invest.qlib_adapter import calculate_factors
from invest.quality import regular_sessions
from invest.research_artifacts import (
    freeze_engine,
    protect_inputs,
    seal_artifacts,
    verify_artifacts,
)
from invest.research_data import create_snapshot, digest, identity
from invest.spy_data import read_spy_inputs

EXPRESSIONS = {
    "momentum_63": "$close/Ref($close,63)-1",
    "momentum_126": "$close/Ref($close,126)-1",
    "momentum_252": "Ref($close,21)/Ref($close,252)-1",
    "trend": "$close/Mean($close,200)-1",
    "volatility": "Std($close/Ref($close,1)-1,63)",
}
METRICS = ("momentum_126", "momentum_252", "trend", "volatility", "drawdown", "liquidity")
METRIC_LABELS = dict(
    zip(METRICS, ("半年强度", "一年强度", "趋势", "波动风险", "回撤风险", "流动性"), strict=True)
)
REASON_LABELS = {
    "cash_or_unsupported_security": "现金或暂不支持的特殊权益",
    "incomplete_recent_history": "最近253个交易会话行情不完整",
    "invalid_prices": "价格字段无效",
    "invalid_price_bounds": "日线高低价关系异常",
    "invalid_volume": "成交量字段无效",
    "adjustment_after_price_cutoff": "最新价格存在尚未核实的拆股调整差异",
    "missing_finite_features": "缺少可计算的指标",
    "return_outlier_or_constant_prices": "存在大幅单日跳变或价格不变，需要核查",
    "price_or_liquidity_below_threshold": "价格或流动性低于初筛门槛",
    "trend_or_relative_strength_below_threshold": "趋势或相对SPY强度未达初筛门槛",
    "stage_one_rank_cutoff": "初筛排名未进入前50",
    "score_below_threshold": "精筛总分未达门槛",
    "risk_above_threshold": "波动或回撤超过门槛",
    "correlated_with_higher_ranked_focus": "与更高排名关注股票高度相关",
    "focus_rank_cutoff": "合格但排名在本轮关注名额之后",
    "relative_strength_with_controlled_price_risk": "相对强度和价格风险条件均满足，进入重点研究",
}
LIMITATIONS = [
    "current_fund_holdings_not_historical_membership",
    "historical_availability_unknown",
    "split_adjusted_price_returns_exclude_cash_dividends",
    "issuer_dividend_and_corporate_action_validation_pending",
    "heuristic_score_not_return_probability_or_validated_alpha",
    "cost_backtest_and_broker_execution_admission_pending",
    "fundamentals_valuation_and_earnings_event_review_pending",
    "sector_classification_may_be_missing",
]
RANK_SCHEMA = research_schema(
    "stock_funnel",
    [(name, pa.string()) for name in ("instrument", "symbol", "name", "sector", "reason", "action")]
    + [("funds", pa.list_(pa.field("element", pa.string())))]
    + [("membership_as_of", pa.date32()), ("price_as_of", pa.date32())]
    + [
        (name, pa.float64())
        for name in (
            "close",
            "momentum_63",
            "momentum_126",
            "momentum_252",
            "trend",
            "volatility",
            "drawdown",
            "liquidity",
            "excess_126",
            "excess_252",
            "stage_one_score",
            "score",
            *[f"{name}_points" for name in METRICS],
        )
    ]
    + [("stage_one", pa.bool_()), ("focus", pa.bool_()), ("trade_eligible", pa.bool_())],
)


RUN_SCHEMA = research_schema(
    "funnel_run",
    [
        (name, pa.string())
        for name in (
            "run_id",
            "status",
            "scope",
            "score_version",
            "config_sha256",
            "input_manifest_sha256",
            "engine_digest",
            "snapshot_id",
            "universe_name",
            "error",
        )
    ]
    + [
        ("as_of", pa.date32()),
        ("membership_as_of", pa.date32()),
        ("membership_through", pa.date32()),
        ("created_at", pa.timestamp("us", tz="UTC")),
    ]
    + [(name, pa.int64()) for name in ("members", "stage_one", "focus")]
    + [("trade_eligible", pa.bool_()), ("limitations", pa.list_(pa.field("element", pa.string())))],
)


def load_funnel_config(path: Path) -> dict[str, Any]:
    values = tomllib.loads(path.read_text())
    names = {
        "stage_one_size",
        "focus_size",
        "min_price",
        "min_dollar_volume",
        "min_score",
        "max_volatility",
        "max_drawdown",
        "max_correlation",
        "weights",
    }
    if set(values) != names or set(values["weights"]) != set(METRICS):
        raise ValueError("Invalid funnel configuration fields")
    if (
        any(type(values[k]) is not int for k in ("stage_one_size", "focus_size"))
        or not 3 <= values["focus_size"] <= 5
        or not values["focus_size"] <= values["stage_one_size"] <= 100
    ):
        raise ValueError("Funnel must target three to five from at most one hundred candidates")
    numbers = [values[k] for k in names - {"stage_one_size", "focus_size", "weights"}] + list(
        values["weights"].values()
    )
    if any(type(v) not in (float, int) or not np.isfinite(v) or v <= 0 for v in numbers):
        raise ValueError("Funnel thresholds must be positive finite numbers")
    if (
        not np.isclose(sum(values["weights"].values()), 1)
        or values["min_score"] > 100
        or not 0 < values["max_correlation"] < 1
        or values["max_drawdown"] > 1
    ):
        raise ValueError("Invalid funnel weights or risk bounds")
    return values


def percentile(values: pd.Series[Any], *, lower: bool = False) -> pd.Series[Any]:
    if len(values) < 2 or values.nunique() == 1:
        return pd.Series(0.5, index=values.index)
    ranks = (values.rank(method="average") - 1) / (len(values) - 1)
    return 1 - ranks if lower else ranks


def select_focus(
    frame: pd.DataFrame, returns: pd.DataFrame, config: dict[str, Any]
) -> pd.DataFrame:
    """只按事先固定的分值和相关性筛选；不补足名额，不将未知指标填零。"""
    frame = frame.copy()
    eligible = frame.loc[frame["reason"] == ""].copy()
    frame["stage_one"] = False
    frame["focus"] = False
    if eligible.empty:
        return frame
    eligible["stage_one_score"] = 50 * (
        percentile(eligible["excess_126"]) + percentile(eligible["excess_252"])
    )
    frame.loc[eligible.index, "stage_one_score"] = eligible["stage_one_score"]
    selected = eligible.sort_values(
        ["stage_one_score", "instrument"], ascending=[False, True]
    ).head(config["stage_one_size"])
    frame.loc[eligible.index, "reason"] = "stage_one_rank_cutoff"
    frame.loc[selected.index, "stage_one"] = True
    frame.loc[selected.index, "reason"] = ""
    total = pd.Series(0.0, index=selected.index)
    for name in METRICS:
        points = (
            100
            * config["weights"][name]
            * percentile(selected[name], lower=name in {"volatility", "drawdown"})
        )
        frame.loc[selected.index, f"{name}_points"] = points
        total += points
    frame.loc[selected.index, "score"] = total
    focus: list[str] = []
    for index, row in (
        frame.loc[selected.index]
        .sort_values(["score", "instrument"], ascending=[False, True])
        .iterrows()
    ):
        instrument = row["instrument"]
        if row["score"] < config["min_score"]:
            reason = "score_below_threshold"
        elif (
            row["volatility"] > config["max_volatility"] or row["drawdown"] > config["max_drawdown"]
        ):
            reason = "risk_above_threshold"
        elif any(
            abs(float(returns[instrument].corr(returns[other]))) > config["max_correlation"]
            for other in focus
        ):
            reason = "correlated_with_higher_ranked_focus"
        elif len(focus) >= config["focus_size"]:
            reason = "focus_rank_cutoff"
        else:
            reason = "relative_strength_with_controlled_price_risk"
            focus.append(instrument)
            frame.loc[index, "focus"] = True
        frame.loc[index, "reason"] = reason
    return frame


def focus_changes(current: pa.Table, previous: pa.Table | None, comparable: bool) -> pa.Table:
    """分数只在规则相同且两轮都有分值时相减；移出股票也保留，不丢历史。"""
    old = {r["instrument"]: r for r in previous.to_pylist()} if previous is not None else {}
    new = {r["instrument"]: r for r in current.to_pylist()}
    rows = []
    for key in sorted(old.keys() | new.keys()):
        before, after = old.get(key, {}), new.get(key, {})
        left, right = before.get("focus", False), after.get("focus", False)
        a, b = before.get("score"), after.get("score")
        rows.append(
            {
                "instrument": key,
                "previous_focus": left,
                "current_focus": right,
                "previous_score": a,
                "current_score": b,
                "score_delta": b - a if comparable and a is not None and b is not None else None,
                "change": "first_observation"
                if previous is None
                else "entered_focus"
                if right and not left
                else "left_focus"
                if left and not right
                else "still_focus"
                if right
                else "not_focused",
                "comparable_rules": comparable,
            }
        )
    schema = research_schema(
        "focus_changes",
        [
            ("instrument", pa.string()),
            ("previous_focus", pa.bool_()),
            ("current_focus", pa.bool_()),
            ("previous_score", pa.float64()),
            ("current_score", pa.float64()),
            ("score_delta", pa.float64()),
            ("change", pa.string()),
            ("comparable_rules", pa.bool_()),
        ],
    )
    return pa.Table.from_pylist(rows, schema=schema)


def run_funnel(
    inputs: Path, config_path: Path, output: Path, as_of: date, *, previous: Path | None = None
) -> dict[str, Any]:
    """每轮写新目录；成员日期、行情截点、规则和来源随报告保留。"""
    config = load_funnel_config(config_path)
    holdings, market = read_spy_inputs(inputs, as_of)
    funds = sorted({fund for values in holdings["funds"].to_pylist() for fund in values})
    universe_name = "SPY_QQQ" if "QQQ" in funds else "SPY"
    membership_days = [
        day
        for name in ("spy_membership_as_of", "qqq_membership_as_of")
        for day in holdings[name].to_pylist()
        if day is not None
    ]
    protect_inputs((output,), (inputs, config_path, *((previous,) if previous else ())))
    if previous is not None:
        verify_artifacts(previous)
        previous_record = pq.read_table(previous / "run.parquet").to_pylist()[0]
        if previous_record["status"] != "completed" or previous_record["as_of"] >= as_of:
            raise ValueError("Previous funnel must be completed before the current price session")
    output.mkdir(parents=True, exist_ok=False)
    record: dict[str, Any] = {
        "status": "running",
        "as_of": as_of,
        "created_at": datetime.now(UTC),
        "scope": "exploratory",
        "score_version": "spy_price_funnel_v1",
        "universe_name": universe_name,
        "config_sha256": digest(config_path),
        "input_manifest_sha256": digest(inputs / "artifacts.parquet"),
        "members": sum(holdings["eligible"].to_pylist()),
        "stage_one": 0,
        "focus": 0,
        "trade_eligible": False,
        "limitations": LIMITATIONS,
        "error": "",
        "snapshot_id": None,
        "membership_as_of": min(membership_days),
        "membership_through": max(membership_days),
        "engine_digest": engine_digest(),
    }
    try:
        shutil.copytree(inputs, output / "inputs")
        shutil.copy2(config_path, output / "config.toml")
        pq.write_table(holdings, output / "holdings.parquet", compression="zstd")
        calendar = regular_sessions(as_of - timedelta(days=730), as_of).to_pylist()[-253:]
        days = [r["date"] for r in calendar]
        frames = {kind: table.to_pandas(date_as_object=True) for kind, table in market.items()}
        symbols = {row["instrument"]: row for row in holdings.to_pylist()}
        symbols["SPY"] = {"instrument": "SPY", "symbol": "SPY", "eligible": True}
        admitted: list[str] = []
        reasons: dict[str, str] = {}
        for instrument, member in symbols.items():
            if not member["eligible"]:
                reasons[instrument] = member["exclusion_reason"]
                continue
            for data in frames.values():
                selected = data.loc[(data.instrument == instrument) & data.date.isin(days)]
                if set(selected.date) != set(days):
                    reasons[instrument] = "incomplete_recent_history"
                    break
                if any(
                    not np.isfinite(float(v)) or float(v) <= 0
                    for key in ("open", "high", "low", "close")
                    for v in selected[key]
                ):
                    reasons[instrument] = "invalid_prices"
                    break
                if any(float(v) < 0 for v in selected.volume):
                    reasons[instrument] = "invalid_volume"
                    break
                if any(
                    not row.low <= min(row.open, row.close) <= max(row.open, row.close) <= row.high
                    for row in selected.itertuples()
                ):
                    reasons[instrument] = "invalid_price_bounds"
                    break
            if instrument not in reasons:
                raw_last = (
                    frames["raw"]
                    .loc[(frames["raw"].instrument == instrument) & (frames["raw"].date == as_of)]
                    .iloc[0]
                )
                split_last = (
                    frames["split"]
                    .loc[
                        (frames["split"].instrument == instrument) & (frames["split"].date == as_of)
                    ]
                    .iloc[0]
                )
                if raw_last.close != split_last.close or raw_last.volume != split_last.volume:
                    reasons[instrument] = "adjustment_after_price_cutoff"
                else:
                    admitted.append(instrument)
        if "SPY" not in admitted:
            raise ValueError("Benchmark lacks complete verified daily prices")
        data = frames["split"].loc[
            frames["split"].instrument.isin(admitted) & frames["split"].date.isin(days)
        ]
        snapshot = create_snapshot(
            pa.Table.from_pandas(data, schema=market["split"].schema, preserve_index=False),
            pa.Table.from_pylist(
                [
                    {
                        "instrument": i,
                        "symbol": symbols[i]["symbol"],
                        "start": days[0],
                        "end": as_of,
                        "available_at": None,
                    }
                    for i in admitted
                ],
                schema=UNIVERSE,
            ),
            output / "snapshot",
            SnapshotSpec(
                "alpaca",
                str((output / "inputs").resolve()),
                "split_adjusted",
                "provider_reported",
                "current_sample",
            ),
            allow_exploratory=True,
        )
        factors = calculate_factors(snapshot, EXPRESSIONS, start=as_of, end=as_of)
        pq.write_table(factors.table, output / "factors.parquet", compression="zstd")
        factor_frame = factors.table.to_pandas().pivot(
            index="instrument", columns="factor", values="value"
        )
        prices = (
            data.pivot(index="date", columns="instrument", values="close")
            .astype(float)
            .sort_index()
        )
        returns = prices.pct_change(fill_method=None).iloc[1:]
        rows = []
        for member in holdings.to_pylist():
            instrument = member["instrument"]
            row = {
                k: member[k]
                for k in ("instrument", "symbol", "name", "sector", "membership_as_of", "funds")
            }
            row.update(
                price_as_of=as_of,
                reason=reasons.get(instrument, ""),
                trade_eligible=False,
                action="EXCLUDED",
            )
            if not row["reason"]:
                values = factor_frame.loc[instrument]
                recent = (
                    frames["raw"]
                    .loc[frames["raw"].instrument == instrument]
                    .sort_values("date")
                    .tail(20)
                )
                history = prices[instrument]
                row.update({name: float(values[name]) for name in EXPRESSIONS})
                row.update(
                    close=float(recent.iloc[-1].close),
                    liquidity=float((recent.close * recent.volume).mean()),
                    volatility=float(values.volatility * np.sqrt(252)),
                    drawdown=float(-(history / history.cummax() - 1).min()),
                    excess_126=float(values.momentum_126 - factor_frame.loc["SPY", "momentum_126"]),
                    excess_252=float(values.momentum_252 - factor_frame.loc["SPY", "momentum_252"]),
                )
                if not all(
                    np.isfinite(row[k]) for k in (*METRICS, "close", "excess_126", "excess_252")
                ):
                    row["reason"] = "missing_finite_features"
                elif returns[instrument].abs().max() > 0.35 or returns[instrument].std() <= 0:
                    row["reason"] = "return_outlier_or_constant_prices"
                elif (
                    row["close"] < config["min_price"]
                    or row["liquidity"] < config["min_dollar_volume"]
                ):
                    row["reason"] = "price_or_liquidity_below_threshold"
                elif (
                    min(row["trend"], row["momentum_126"], row["excess_126"], row["excess_252"])
                    <= 0
                ):
                    row["reason"] = "trend_or_relative_strength_below_threshold"
            rows.append(row)
        frame = pd.DataFrame(rows).reindex(columns=RANK_SCHEMA.names)
        ranked = select_focus(frame, returns.tail(126), config)
        ranked.loc[ranked.stage_one, "action"] = "WATCH"
        ranked.loc[ranked.focus, "action"] = "FOCUS"
        table = pa.Table.from_pandas(ranked, schema=RANK_SCHEMA, preserve_index=False)
        metadata = {
            **snapshot.metadata(RANK_SCHEMA),
            b"input_manifest_sha256": record["input_manifest_sha256"].encode(),
            b"config_sha256": record["config_sha256"].encode(),
            b"score_version": b"spy_price_funnel_v1",
            b"universe_name": universe_name.encode(),
            b"trade_eligible": b"false",
        }
        table = table.replace_schema_metadata(metadata)
        pq.write_table(table, output / "rankings.parquet", compression="zstd")
        focus = table.filter(pa.array(ranked.focus.tolist())).sort_by(
            [("score", "descending"), ("instrument", "ascending")]
        )
        pq.write_table(focus, output / "focus.parquet", compression="zstd")
        prior = pq.read_table(previous / "rankings.parquet") if previous is not None else None
        comparable = (
            previous is not None
            and previous_record["config_sha256"] == record["config_sha256"]
            and previous_record["score_version"] == record["score_version"]
            and previous_record.get("universe_name", "SPY") == universe_name
        )
        pq.write_table(
            focus_changes(table, prior, comparable), output / "changes.parquet", compression="zstd"
        )
        if previous is not None:
            shutil.copy2(previous / "rankings.parquet", output / "previous-rankings.parquet")
            shutil.copy2(previous / "run.parquet", output / "previous-run.parquet")
        record.update(
            status="completed",
            stage_one=int(ranked.stage_one.sum()),
            focus=focus.num_rows,
            snapshot_id=snapshot.snapshot_id,
        )
        if engine_digest() != record["engine_digest"]:
            raise ValueError("Engine changed during funnel run")
        write_report(output, record, table, config)
        freeze_engine(output)
    except Exception as exc:
        record.update(status="failed", error=f"{type(exc).__name__}: {exc}")
        raise
    finally:
        # 小型运行记录使用明确标量与字符串列表类型，失败结果同样封存。
        record["run_id"] = identity(
            {
                "inputs": record["input_manifest_sha256"],
                "config": record["config_sha256"],
                "as_of": str(as_of),
                "engine": record["engine_digest"],
            }
        )
        pq.write_table(
            pa.Table.from_pylist([record], schema=RUN_SCHEMA),
            output / "run.parquet",
            compression="zstd",
        )
        seal_artifacts(output)
    return {
        "directory": output,
        "status": record["status"],
        "stage_one": record["stage_one"],
        "focus": record["focus"],
        "trade_eligible": False,
    }


def write_report(
    output: Path, record: dict[str, Any], table: pa.Table, config: dict[str, Any]
) -> None:
    """理由由实际指标生成；分值不是收益概率，缺失项和拒绝项均可见。"""
    rows = sorted(
        table.to_pylist(), key=lambda r: (not r["focus"], -(r["score"] or -1), r["symbol"])
    )
    body = []
    for row in rows:
        score = "—" if row["score"] is None else f"{row['score']:.1f}"
        explanation = REASON_LABELS[row["reason"]]
        if row["stage_one"]:
            explanation = (
                f"半年相对 SPY {row['excess_126'] * 100:+.1f} 个百分点；"
                f"一年剔除最近一月价格收益 {row['momentum_252']:+.1%}；"
                f"高于200日均线 {row['trend']:.1%}；年化波动 {row['volatility']:.1%}；"
                f"区间最大回撤 {row['drawdown']:.1%}。{explanation}。"
            )
            explanation += "分项得分：" + "，".join(
                f"{METRIC_LABELS[name]} {row[f'{name}_points']:.1f}" for name in METRICS
            )
        body.append(
            "<tr>"
            + "".join(
                f"<td>{html.escape(str(v))}</td>"
                for v in (
                    row["symbol"],
                    row["name"],
                    "/".join(row["funds"]),
                    score,
                    "重点研究" if row["focus"] else "候选观察" if row["stage_one"] else "淘汰",
                    explanation,
                )
            )
            + "</tr>"
        )
    columns = "".join(
        f"<th>{v}</th>" for v in ("股票", "公司", "所属股票池", "系统评分", "结果", "理由与风险")
    )
    universe_label = record["universe_name"].replace("_", " + ")
    weights = "、".join(
        f"{METRIC_LABELS[name]} {weight:.0%}" for name, weight in config["weights"].items()
    )
    (output / "report.html").write_text(f"""<!doctype html><html lang="zh-CN"><meta charset="utf-8">
<title>{universe_label} 选股漏斗</title>
<style>body{{font:16px/1.6 system-ui;margin:40px auto;max-width:1300px;
color:#182c3a;background:#f6f8fa}}h1{{color:#154c58}}
table{{border-collapse:collapse;width:100%;background:white}}
td,th{{padding:12px;border-bottom:1px solid #dde5ea;text-align:left}}
th{{background:#e4eff1}}td:last-child{{max-width:650px}}
.note{{padding:18px;background:#fff4dc}}</style>
<h1>{universe_label} 选股漏斗</h1><p>成员披露日期
{record["membership_as_of"]} 至 {record["membership_through"]}；价格截点 {record["as_of"]}。
{record["members"]} 只普通股票 → {record["stage_one"]} 只初筛候选
→ {record["focus"]} 只重点研究。</p>
<p class="note">这是量价研究关注名单，尚无成本后回测、完整公司行动、基本面估值和财报事件验证，
不输出买入许可。
评分为固定规则下的横向优先级，不是上涨概率。当前持仓不能作为历史成分股库。现金和特殊权益逐项保留淘汰理由。
行业缺失时不编造行业约束；以126会话收益相关性去重。少于3只合格时不凑数。</p>
<p>第一轮：253个完整会话、价格≥{config["min_price"]} USD、
20日平均成交额≥{config["min_dollar_volume"]:,.0f} USD、半年正收益、趋势及相对SPY强度为正；
最多{config["stage_one_size"]}只。
第二轮权重：{html.escape(weights)}；分数≥{config["min_score"]}，波动≤{config["max_volatility"]:.0%}、回撤≤{config["max_drawdown"]:.0%}，两两绝对相关性≤{config["max_correlation"]}。</p>
<p>全部原始输入、Qlib因子、分项得分、规则和淘汰原因保存在同目录 Parquet 文件中。
价格收益不含现金分红；没有改变既有交易准入和账户。</p>
<table><thead><tr>{columns}</tr></thead><tbody>{"".join(body)}</tbody></table></html>""")
