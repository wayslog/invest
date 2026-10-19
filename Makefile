UV ?= uv
DEMO_ACCOUNT ?= reports/paper-demo

.PHONY: install check lint typecheck test format build demo

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
