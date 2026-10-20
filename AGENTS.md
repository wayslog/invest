# Development instructions

- Use Python 3.12 and uv. Work from the existing checkout; cloud tasks are already
  isolated. Do not create a Git worktree unless the user asks for one.
- Install with `uv sync --locked --python 3.12`. If the default cache is not
  writable in the cloud environment, export `UV_CACHE_DIR=/workspace/.cache/uv-invest`.
- Run `make check` for lint, formatting, types and tests. Use `make demo` for the
  offline CLI and `make build` to verify packaging. Keep checks independent of
  external market APIs or account credentials.
- Put reusable logic in `src/invest/`. Add behavioral tests for new calculations
  and data validation. State units, date conventions and adjustment assumptions.
- Keep `pyproject.toml` and `uv.lock` consistent when changing dependencies.
- Market data, ledgers and result tables use typed Parquet with Zstandard compression.
  Configuration is TOML; do not add text-table data paths.
- Paper fills must follow the decision session. Preserve Decimal accounting,
  append-only history and restart idempotency. Keep synthetic and real data explicit.
- Account snapshots are tied to engine source and parameters. After changing engine
  code, use a new M1 demo directory: `make demo DEMO_ACCOUNT=reports/<new-name>`.
  M3 forward capital accounts keep their identity and risk history; never replace
  them with fresh capital to bypass a frozen engine or a paused/risk-halted state.
  Run `make forward-demo M3_DEMO_DIR=reports/<new-name>` for forward-engine changes.
- In cloud sessions, set `MPLCONFIGDIR=/workspace/.cache/invest-matplotlib` if needed
  for Matplotlib's writable font cache.
- Keep credentials, downloaded datasets and private reports out of Git. Use the
  ignored `data/` and `reports/` directories for generated research artifacts.
- README and research documentation are written in Chinese; code identifiers are
  English. Keep the initial framework small and add integrations when requested.
