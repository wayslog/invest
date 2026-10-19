"""Allow running the CLI with python -m invest."""

from invest.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
