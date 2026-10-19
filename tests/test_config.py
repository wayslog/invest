from pathlib import Path

import pytest

from invest.config import load_config


@pytest.mark.parametrize(
    "contents",
    [
        "lookback = true",
        "lookback = 1",
        'allocation = "1.1"',
        'commission = "-1"',
        'account_drawdown = "NaN"',
        'slippage_bps = "10000"',
        "unknown = 1",
        'initial_cash = "0"',
        'stop_loss = "0.0000001"',
    ],
)
def test_invalid_config_fails_closed(tmp_path: Path, contents: str) -> None:
    path = tmp_path / "config.toml"
    path.write_text(contents, encoding="utf-8")
    with pytest.raises(ValueError):
        load_config(path)
