"""Run the shared M4 implementation with the isolated broker dependency lock."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from invest.ibkr_cli import main  # noqa: E402

if __name__ == "__main__":
    main()
