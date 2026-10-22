"""Observe the M3 host from Actions and publish an operational Parquet report."""

import io
import json
import os
import subprocess
import time
from contextlib import redirect_stdout
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq
from github_actions import execute

from invest.notifications import send_telegram

STAMP = pa.timestamp("us", tz="UTC")
REPORT_SCHEMA = pa.schema(
    [
        ("recorded_at", STAMP),
        ("host_observed_at", STAMP),
        ("release", pa.string()),
        ("healthy", pa.bool_()),
        ("issues", pa.list_(pa.field("element", pa.string()))),
        ("notification", pa.string()),
        ("operations", pa.string()),
        ("risk_status", pa.string()),
        ("sessions", pa.int64()),
        ("registered_sessions", pa.int64()),
        ("decision_sessions", pa.int64()),
        ("last_session", pa.date32()),
        ("observation_end_session", pa.date32()),
        ("next_capture_after", STAMP),
        ("decision_deadline", STAMP),
        ("missing_sessions", pa.int64()),
        ("accounting_verified", pa.bool_()),
        ("backup_matches_current", pa.bool_()),
        ("last_run_finished_at", STAMP),
        ("last_run_outcome", pa.string()),
        ("last_health_at", STAMP),
        ("daily_timer_active", pa.bool_()),
        ("health_timer_active", pa.bool_()),
        ("runs_24h", pa.int64()),
        ("updated_runs_24h", pa.int64()),
        ("failed_runs_24h", pa.int64()),
        ("systemd_failures_24h", pa.int64()),
        ("health_failures_24h", pa.int64()),
        ("notification_failures_24h", pa.int64()),
    ],
    metadata={b"schema_version": b"invest.operations.report.v1"},
)


def parse_inspection(output: str) -> dict[str, Any]:
    report: dict[str, Any] = {}
    for line in output.splitlines():
        name, separator, body = line.partition(": ")
        if name == "Release" and separator:
            report["release"] = body
        elif name in {"Account", "Timers", "runs", "health", "Backup", "Window"} and separator:
            report[name] = json.loads(body)
    return report


def probe() -> dict[str, Any]:
    # A scheduled read can overlap the single writer. Retry after it has had time to finish.
    for attempt in range(2):
        try:
            output = io.StringIO()
            with redirect_stdout(output):
                execute("inspect", None)
            result = parse_inspection(output.getvalue())
            if not attempt and result.get("Account", {}).get("accounting_verified") is False:
                time.sleep(20)
                continue
            return result
        except (OSError, ValueError, RuntimeError, subprocess.TimeoutExpired):
            if attempt:
                raise
            time.sleep(20)
    raise AssertionError("unreachable")


def timestamp(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value).astimezone(UTC) if value else None


def assess(snapshot: dict[str, Any], now: datetime) -> dict[str, Any]:
    account, timers = snapshot["Account"], snapshot["Timers"]
    run, health, backup = snapshot["runs"], snapshot["health"], snapshot["Backup"]
    issues = []
    finished = timestamp(run.get("finished_at"))
    checked = timestamp(health.get("recorded_at"))
    capture = timestamp(account.get("next_capture_after"))
    completed = account["operations"] == "completed" and account["coverage_met"]
    if not account["accounting_verified"]:
        issues.append("账户对账未通过")
    if not account["engine_matches"]:
        issues.append("账户引擎与运行版本不一致")
    if not backup["present"] or not backup["matches_current"]:
        issues.append("当前账户缺少对应的本机备份")
    if not completed:
        if account["operations"] != "active":
            issues.append("账户未处于运行状态")
        if account["risk_status"] != "active":
            issues.append("账户风险状态需要处理")
        for name, label in (("daily", "日结"), ("health", "健康检查")):
            if not timers[name + "_active"] or not timers[name + "_enabled"]:
                issues.append(label + "定时器未启用")
        if finished is None or not timedelta(0) <= now - finished <= timedelta(minutes=150):
            issues.append("日结心跳超时或时间异常")
        if run["outcome"] != "ok":
            issues.append("最近一次日结失败或需要处理")
        if checked is None or not timedelta(0) <= now - checked <= timedelta(minutes=45):
            issues.append("健康检查记录过期或时间异常")
        if not health["healthy"]:
            issues.append("主机健康检查未通过")
        # The first worker runs shortly after the provider cutoff; pending data is not a miss.
        if account["missing_sessions"] and (
            capture is None or now - capture > timedelta(minutes=20)
        ):
            issues.append("日结仍有到期未核算会话")
    window = snapshot["Window"]
    return {
        "recorded_at": now,
        "host_observed_at": timestamp(account.get("observed_at")),
        "release": snapshot["release"],
        "healthy": not issues,
        "issues": issues,
        "operations": account["operations"],
        "risk_status": account["risk_status"],
        "sessions": account["sessions"],
        "registered_sessions": account["registered_sessions"],
        "decision_sessions": account["decision_sessions"],
        "last_session": date.fromisoformat(account["last_session"]),
        "observation_end_session": date.fromisoformat(account["observation_end_session"]),
        "next_capture_after": capture,
        "decision_deadline": timestamp(account.get("decision_deadline")),
        "missing_sessions": account["missing_sessions"],
        "accounting_verified": account["accounting_verified"],
        "backup_matches_current": backup["matches_current"],
        "last_run_finished_at": finished,
        "last_run_outcome": run["outcome"],
        "last_health_at": checked,
        "daily_timer_active": timers["daily_active"],
        "health_timer_active": timers["health_active"],
        **{
            name + "_24h": window[name]
            for name in (
                "runs",
                "updated_runs",
                "failed_runs",
                "systemd_failures",
                "health_failures",
                "notification_failures",
            )
        },
    }


def markdown(row: dict[str, Any]) -> str:
    from zoneinfo import ZoneInfo

    def local(value: datetime | None) -> str:
        return (
            value.astimezone(ZoneInfo("Asia/Shanghai")).strftime("%Y-%m-%d %H:%M:%S")
            if value
            else "—"
        )

    lines = [
        "# M3 运行日报",
        "",
        "时间均为北京时间。每次检查保留实际采样时间。",
        "",
        "| 项目 | 状态 |",
        "| --- | --- |",
        f"| 检查时间 | {local(row['recorded_at'])} |",
        f"| 运行状态 | {'正常' if row['healthy'] else '需要处理'} |",
    ]
    if row.get("sessions") is not None:
        lines += [
            f"| 观察进度 | {row['sessions']}/{row['registered_sessions']} 个交易日 |",
            f"| 最新核算交易日 | {row['last_session']} |",
            f"| 观察结束交易日 | {row['observation_end_session']} |",
            *(
                ["| 观察窗口 | 已结束 |"]
                if row["operations"] == "completed"
                else [
                    f"| 下次数据可采集时间 | {local(row['next_capture_after'])} |",
                    f"| 未核算会话 | {row['missing_sessions']} |",
                ]
            ),
            f"| 最新日结完成时间 | {local(row['last_run_finished_at'])} |",
            f"| 本机备份 | {'对应当前账户' if row['backup_matches_current'] else '需要处理'} |",
            f"| 过去 24 小时运行 / 新日结 | {row['runs_24h']} / {row['updated_runs_24h']} |",
            (
                f"| 过去 24 小时日结异常 / systemd 故障通知 | {row['failed_runs_24h']} / "
                f"{row['systemd_failures_24h']} |"
            ),
            (
                f"| 过去 24 小时健康检查异常 / 通知失败 | {row['health_failures_24h']} / "
                f"{row['notification_failures_24h']} |"
            ),
            f"| 主机代码 | `{row['release']}` |",
        ]
    lines += [
        "",
        *[f"- {issue}" for issue in row["issues"]],
        "",
        "现金观察记录运行可靠性；策略资格继续独立验证。",
        "",
    ]
    return "\n".join(lines)


def previous_failure() -> bool:
    repository = os.environ.get("GITHUB_REPOSITORY")
    if not repository or not os.environ.get("GH_TOKEN"):
        return False
    try:
        result = subprocess.run(
            [
                "gh",
                "api",
                f"repos/{repository}/actions/workflows/monitor.yml/runs?status=completed&per_page=10",
            ],
            capture_output=True,
            timeout=20,
            check=False,
        )
        if result.returncode:
            return False
        runs = json.loads(result.stdout)["workflow_runs"]
        latest = next((run for run in runs if run["conclusion"] in {"success", "failure"}), None)
        return latest is not None and latest["conclusion"] == "failure"
    except (OSError, subprocess.TimeoutExpired, ValueError, KeyError, TypeError):
        return False


def run_monitor(output: Path) -> int:
    try:
        snapshot = probe()
        row = assess(snapshot, datetime.now(UTC))
    except (OSError, ValueError, RuntimeError, KeyError, TypeError, subprocess.TimeoutExpired):
        # SSH failure must still notify from the runner while the entire host is offline.
        row = {
            "recorded_at": datetime.now(UTC),
            "healthy": False,
            "issues": ["主机状态读取失败，请检查 SSH 与主机运行状态"],
        }
    notice = None
    row["notification"] = "not_needed"
    if not row["healthy"]:
        notice = "Invest M3 主机外监控异常：" + "；".join(row["issues"])
    elif previous_failure():
        notice = "Invest M3：主机外监控已恢复，日结、账户对账及本机备份正常。"
    elif os.environ.get("GITHUB_EVENT_NAME") == "workflow_dispatch":
        notice = "Invest M3：主机外监控通道自检通过，定时检查和运行日报已接通。"
    if notice is not None:
        try:
            link = os.environ.get("GITHUB_SERVER_URL", "https://github.com")
            repository, run = os.environ.get("GITHUB_REPOSITORY"), os.environ.get("GITHUB_RUN_ID")
            if repository and run:
                notice += f"\n{link}/{repository}/actions/runs/{run}"
            send_telegram(notice, "INVEST_TELEGRAM_BOT_TOKEN", "INVEST_TELEGRAM_ALLOWED_UID")
            row["notification"] = "sent"
        except ValueError:
            row["notification"] = "failed"
            row["healthy"] = False
            row["issues"].append("主机外 Telegram 通知未送达")
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("xb") as stream:
        pq.write_table(
            pa.Table.from_pylist([row], schema=REPORT_SCHEMA), stream, compression="zstd"
        )
    summary = markdown(row)
    destination = os.environ.get("GITHUB_STEP_SUMMARY")
    if destination:
        with Path(destination).open("a") as stream:
            stream.write(summary)
    print(summary)
    return 0 if row["healthy"] else 1


if __name__ == "__main__":
    raise SystemExit(run_monitor(Path("reports/operations/m3-status.parquet")))
