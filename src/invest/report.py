"""Standalone HTML report backed by Parquet account tables."""

from html import escape
from pathlib import Path

from matplotlib.figure import Figure

from invest.paper import PaperResult


def write_report(result: PaperResult, output: Path) -> None:
    frame = result.equity.to_pandas()
    metrics = result.metrics.to_pylist()[0]
    figure = Figure(figsize=(10, 7), layout="constrained")
    axes = figure.subplots(2, 1, sharex=True)
    axes[0].plot(frame["date"], frame["equity"].astype(float), label="Paper strategy")
    axes[0].plot(frame["date"], frame["benchmark_equity"].astype(float), label="Buy and hold")
    initial = float(metrics["initial_cash"])
    axes[0].axhline(initial * 0.8, linestyle="--", color="orange", label="Capital warning")
    axes[0].axhline(initial * 0.5, linestyle="--", color="red", label="Termination trigger")
    axes[0].set_ylabel("Account equity (USD)")
    axes[0].legend()
    axes[1].plot(frame["date"], frame["drawdown"] * 100, color="red")
    axes[1].set_ylabel("Drawdown (%)")
    figure.savefig(output / "equity.png", dpi=120)
    rows = "".join(
        f"<tr><th>{escape(str(key))}</th><td>{escape(str(value))}</td></tr>"
        for key, value in metrics.items()
    )
    source = escape(str(metrics["data_source"]))
    dividend_status = (
        "Issuer cash dividends matched; see dividends.parquet and dividend-source.parquet. "
        "Other corporate actions and historical publication times remain outside that check. "
        if (output / "dividends.parquet").exists()
        else "Historical publication times and action completeness still need external review. "
    )
    (output / "report.html").write_text(
        '<!doctype html><html lang="zh-CN"><meta charset="utf-8">'
        "<title>Invest paper account</title>"
        "<style>body{font:16px sans-serif;max-width:1000px;margin:32px auto;padding:0 16px}"
        "table{border-collapse:collapse}th,td{border:1px solid #ddd;padding:6px;text-align:left}"
        "img{max-width:100%}</style><h1>Local paper account</h1>"
        f"<p>Data source: {source}. "
        "Synthetic data validates software, not investment performance.</p>"
        "<p>Signals and position exits include cash dividends when earned. "
        "Orders are valid only at the next session open, using the provider's daily-open proxy. "
        "No real order book, tax or broker simulation. The benchmark uses the same warm-up, "
        "allocation cap and costs, without strategy exits.</p>"
        f'<table>{rows}</table><img src="equity.png" alt="Net asset value and drawdown">'
        "<p>Data quality and independent cash-flow reconciliation passed before publication. "
        "See quality.parquet and reconciliation.parquet; source captures are retained. "
        f"{dividend_status}"
        "Ledgers: equity.parquet, trades.parquet, events.parquet. "
        "Unfilled final orders remain pending for the next update.</p></html>",
        encoding="utf-8",
    )
