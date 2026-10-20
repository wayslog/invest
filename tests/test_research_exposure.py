"""Known data remains exploratory even if a newly downloaded study looks profitable."""

import json
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from invest.alpaca import FetchSpec
from invest.datasets import fetch_dataset
from invest.forward import _qualify
from invest.forward_config import parse_observation
from invest.research import GATE_SCHEMA, run_study, verify_study
from invest.research_registry import (
    V2_REGISTRATION_SCHEMA,
    read_registration,
    register_study,
    registration_known_history,
)
from invest.storage import engine_digest
from invest.study_config import parse_study
from tests.test_dividends import source_capture
from tests.test_forward import setup


def test_known_history_cannot_qualify_even_when_all_performance_gates_pass(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, inputs, _ = setup(tmp_path)
    body = (tmp_path / "policy.toml").read_text()
    replacements = {
        '["SPY", "XLF", "XLK"]': '["SPY", "XLF"]',
        "2022-01-03": "2024-01-08",
        "2023-12-29": "2024-01-09",
        "2024-01-02": "2024-01-10",
        "2024-12-31": "2024-01-11",
        "2025-01-02": "2024-01-12",
        "2025-12-31": "2024-01-16",
        "2026-01-02": "2024-01-17",
        "2026-06-30": "2024-01-18",
        "[2023, 2024, 2025]": "[]",
    }
    for old, new in replacements.items():
        body = body.replace(old, new)
    policy = tmp_path / "new-policy.toml"
    policy.write_text(body)
    registration = tmp_path / "registration.parquet"
    register_study(policy, registration, known_history=True)
    sources = {}

    for symbol, table in inputs.items():

        def get(
            endpoint: str, query: dict[str, str], symbol: str = symbol, table: pa.Table = table
        ) -> bytes:
            if endpoint == "/v2/stocks/bars":
                values = [
                    {
                        "t": f"{r['date']}T05:00:00Z",
                        "v": 1000,
                        **{
                            short: str(r[long])
                            for short, long in [
                                ("o", "open"),
                                ("h", "high"),
                                ("l", "low"),
                                ("c", "close"),
                            ]
                        },
                    }
                    for r in table.to_pylist()
                ]
                return json.dumps({"bars": {symbol: values}, "next_page_token": None}).encode()
            return json.dumps(
                {
                    "corporate_actions": {
                        "cash_dividends": [
                            {
                                "symbol": symbol,
                                "rate": "1",
                                "ex_date": "2024-01-05",
                                "payable_date": "2024-01-09",
                                "foreign": False,
                                "special": False,
                            }
                        ]
                    },
                    "next_page_token": None,
                }
            ).encode()

        sources[symbol] = fetch_dataset(
            FetchSpec(symbol, table["date"][0].as_py(), table["date"][-1].as_py(), "sip"),
            tmp_path / "data",
            get,
        )
    issuer = source_capture(
        tmp_path,
        [
            ["Test fund", s, "test", "01/05/2024", "01/05/2024", "01/09/2024", "1", "", ""]
            for s in inputs
        ],
    )
    monkeypatch.setattr(
        "invest.research.eligibility",
        lambda *args: pa.Table.from_pylist(
            [{"check": "performance_fixture", "passed": True, "detail": "positive fixture"}],
            schema=GATE_SCHEMA,
        ),
    )
    study = run_study(registration, sources, tmp_path / "study", issuer=issuer)
    assert verify_study(study) == 32
    manifest = pq.read_table(study / "manifest.parquet").to_pylist()[0]
    assert manifest["scope"] == "known_history_research_only"
    assert not manifest["m3_research_eligible"]
    assert pq.read_table(study / "eligibility.parquet")["passed"].to_pylist() == [True, False]
    assert "本研究登记为已知历史" in (study / "report.html").read_text()
    plan_body = (
        (tmp_path / "observation.toml")
        .read_text()
        .replace('mode="drill"', 'mode="shadow_research"')
        .replace("start_session=2024-01-08", "start_session=2024-01-19")
        .replace('candidate="trend-2"', f'candidate="{manifest["selected_candidate"]}"')
    )
    plan = parse_observation(plan_body.encode())
    staging = tmp_path / "shadow"
    staging.mkdir()
    _qualify(study, staging, parse_study(policy.read_bytes()), plan)
    formal = parse_observation(
        plan_body.replace('mode="shadow_research"', 'mode="qualified_strategy"').encode()
    )
    rejected = tmp_path / "formal"
    rejected.mkdir()
    with pytest.raises(ValueError, match="did not pass"):
        _qualify(study, rejected, parse_study(policy.read_bytes()), formal)


def test_v2_registration_remains_readable_without_inventing_exposure_flags(tmp_path: Path) -> None:
    setup(tmp_path)
    new = tmp_path / "new.parquet"
    register_study(tmp_path / "policy.toml", new, known_history=True)
    table = pq.read_table(new)
    old = pa.Table.from_pylist(table.to_pylist(), schema=V2_REGISTRATION_SCHEMA)
    output = tmp_path / "v2.parquet"
    pq.write_table(old, output)
    assert read_registration(output, required_engine=engine_digest())
    assert not registration_known_history(output.read_bytes())
    assert registration_known_history(new.read_bytes())
