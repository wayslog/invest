import hashlib
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pyarrow.parquet as pq
import pytest

from invest.forward_engine import next_session
from invest.research import run_study
from invest.research_diagnostics import diagnose_study
from invest.research_proposals import register_proposal
from invest.research_registry import read_registration, verify_inventory
from invest.strategies import candidates
from invest.study_config import parse_study
from tests.test_research import experiment


def test_one_registered_family_does_not_silently_search_the_other_family() -> None:
    config = parse_study(Path("configs/r1-capital-budget.toml").read_bytes())
    assert [candidate.name for candidate in candidates(config)] == ["rotation-120"]
    legacy = parse_study(Path("configs/m2.toml").read_bytes())
    assert len(candidates(legacy)) == 6
    with pytest.raises(ValueError, match="families"):
        parse_study(
            Path("configs/r1-capital-budget.toml")
            .read_bytes()
            .replace(
                b'candidate_kinds = ["rotation"]', b'candidate_kinds = ["rotation", "rotation"]'
            )
        )


def test_future_proposal_freezes_protocol_exposure_and_source_without_relabelling_history(
    tmp_path: Path,
) -> None:
    config = tmp_path / "proposal.toml"
    future = next_session(datetime.now(UTC).date() + timedelta(days=365))["date"]
    body = Path("configs/r1-capital-budget.toml").read_text()
    config.write_text(
        body.replace("2026-10-21", str(future)).replace(
            "2027-04-20", str(future + timedelta(days=180))
        )
    )
    protocol = tmp_path / "protocol.md"
    protocol.write_text("A fixed hypothesis with exposed historical data and unopened future data.")
    output = tmp_path / "registered"
    register_proposal(config, protocol, output, date(2026, 10, 19))
    verify_inventory(output)
    row = pq.read_table(output / "proposal.parquet").to_pylist()[0]
    assert row["protocol_body"] == protocol.read_bytes()
    assert row["protocol_sha256"] == hashlib.sha256(protocol.read_bytes()).hexdigest()
    assert (
        row["registration_sha256"]
        == hashlib.sha256((output / "registration.parquet").read_bytes()).hexdigest()
    )
    frozen = read_registration(output / "registration.parquet")[0]
    assert frozen.holdout_start == future
    protocol.write_text("Changed protocol must not change the frozen hypothesis")
    assert pq.read_table(output / "proposal.parquet").to_pylist()[0] == row
    with pytest.raises(ValueError, match="new output"):
        register_proposal(config, protocol, output, date(2026, 10, 19))


def test_proposal_refuses_to_claim_known_history_as_future(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="future session"):
        register_proposal(
            Path("configs/r1-long-horizon.toml"),
            Path("docs/research/r1-long-horizon.md"),
            tmp_path / "invalid",
            date(2026, 10, 19),
        )
    assert not (tmp_path / "invalid").exists()


def test_diagnostics_explains_sealed_results_without_changing_the_original(tmp_path: Path) -> None:
    registration, inputs = experiment(tmp_path)
    study = run_study(registration, inputs, tmp_path / "study", synthetic=True)
    original = (study / "files.parquet").read_bytes()
    result = diagnose_study(study, tmp_path / "diagnostic")
    assert result["runs"] == 32 and result["reconciliation_errors"] == 0
    assert (study / "files.parquet").read_bytes() == original
    verify_inventory(tmp_path / "diagnostic")
    table = pq.read_table(tmp_path / "diagnostic" / "runs.parquet")
    assert all(row["sessions"] >= row["active_sessions"] for row in table.to_pylist())
    assert all(
        row["trades"] == int(row["commissions"])
        for row in table.to_pylist()
        if row["cost_multiplier"] == 1
    )
