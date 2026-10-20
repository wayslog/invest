UV ?= uv
DEMO_ACCOUNT ?= reports/paper-demo
M2_DEMO_DIR ?= reports/m2-demo
M3_DEMO_DIR ?= reports/m3-demo

.PHONY: install check lint typecheck test format build demo research-demo forward-demo

install:
	$(UV) sync --locked --python 3.12

check: lint typecheck test

lint:
	$(UV) run --locked ruff check .
	$(UV) run --locked ruff format --check .

typecheck:
	$(UV) run --locked mypy

test:
	$(UV) run --locked pytest --cov=invest --cov-report=term-missing

format:
	$(UV) run --locked ruff check --fix .
	$(UV) run --locked ruff format .

build:
	$(UV) build

demo:
	$(UV) run --locked invest analyze examples/prices.parquet
	$(UV) run --locked invest paper --data examples/paper_bars.parquet --config configs/demo.toml --account $(DEMO_ACCOUNT)

research-demo:
	$(UV) run --locked python examples/generate_research.py --output $(M2_DEMO_DIR)/inputs
	$(UV) run --locked invest research-register --config configs/m2.toml --output $(M2_DEMO_DIR)/registration.parquet
	$(UV) run --locked invest research --registration $(M2_DEMO_DIR)/registration.parquet --synthetic --input SPY=$(M2_DEMO_DIR)/inputs/SPY.parquet --input XLF=$(M2_DEMO_DIR)/inputs/XLF.parquet --input XLK=$(M2_DEMO_DIR)/inputs/XLK.parquet --output $(M2_DEMO_DIR)/study
	$(UV) run --locked invest verify-study --study $(M2_DEMO_DIR)/study

forward-demo:
	$(UV) run --locked python examples/forward_drill.py --output $(M3_DEMO_DIR)
