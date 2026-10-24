# Development instructions

- Use Python 3.12 and uv. Work from the existing checkout; cloud tasks are already
  isolated. Do not create a Git worktree unless the user asks for one.
- Install with `uv sync --locked --python 3.12`. If the default cache is not
  writable in the cloud environment, export `UV_CACHE_DIR=/workspace/.cache/uv-invest`.
  Add `--group research` for Qlib and Alphalens; `make install` and `make test`
  include this group. Keep the independent IBKR SDK environment separate.
- Run `make check` for lint, formatting, types and tests. Use `make demo` for the
  offline CLI and `make build` to verify packaging. Keep checks independent of
  external market APIs or account credentials.
- Put reusable logic in `src/invest/`. Add behavioral tests for new calculations
  and data validation. State units, date conventions and adjustment assumptions.
- Keep `pyproject.toml` and `uv.lock` consistent when changing dependencies.
- Authoritative tabular data and formal result tables use typed Parquet with
  Zstandard compression, including market data, factor and signal tables, actions,
  and ledgers. Configuration is TOML; do not add CSV or other text-table business
  data paths.
- Third-party libraries such as Qlib may use rebuildable native-format caches,
  including binary features and text calendars or instrument lists. Derive them
  from authoritative Parquet snapshots and recorded configuration; keep them in
  isolated, Git-ignored directories under data/cache/. Record input snapshots,
  converter and library versions, relevant parameters, units and adjustment rules.
  Isolate caches when those inputs change. Caches are disposable derived data, not
  independent business records or a second authoritative store. Never reconstruct
  Decimal ledgers from floating-point research caches.
- Preserve historical accounts and research records, including their identity,
  registrations, provenance, journals, risk history, frozen inputs and results.
  Cache generation, cleanup or rebuilding must not overwrite, relabel or delete
  those records, reset capital or risk state, or alter out-of-sample status.
- IBKR is the sole authoritative external source for market data, accounts, orders,
  fills and costs. Keep other providers only as labeled historical/reference data;
  do not silently substitute or merge them into IBKR records. The existing Alpaca
  implementation and frozen observations are legacy evidence, not an implemented
  IBKR connection. Preserve their original provenance, registrations and journals.
- Paper fills must follow the decision session. Preserve Decimal accounting,
  append-only history and restart idempotency. Keep synthetic and real data explicit.
- Account snapshots are tied to engine source and parameters. After changing engine
  code, use a new M1 demo directory: `make demo DEMO_ACCOUNT=reports/<new-name>`.
  M3 forward capital accounts keep their identity and risk history; never replace
  them with fresh capital to bypass a frozen engine or a paused/risk-halted state.
  One explicit user-authorized exception is the 2026-10-23 replacement of the
  paused legacy cash observation: archive its account and operations unchanged,
  then register `m3-ibkr-cash-v1` as a new IBKR cash-only observation with a new ID,
  USD 5,000 and a new 60-session window. Do not carry over its old 2/60 count.
  This is not a migration or permission for later automatic account resets.
  Run `make forward-demo M3_DEMO_DIR=reports/<new-name>` for forward-engine changes.
  Version transitions use `forward-migrate` with the expected head, source engine,
  verified backup and actor/reason; only cash observations and drills support it.
  Do not rewrite registration or historical journal files. A deployed capital
  account has one authoritative writer; never update a stale local copy in parallel.
- In cloud sessions, set `MPLCONFIGDIR=/workspace/.cache/invest-matplotlib` if needed
  for Matplotlib's writable font cache.
- Keep credentials, downloaded datasets and private reports out of Git. Use the
  ignored `data/` and `reports/` directories for generated research artifacts.
- The user fully trusts the configured deployment host. Do not add host-key pinning,
  account-package signatures or certificates, or transport-checksum gates.
  Continue preserving account identity, financial reconciliation and history.
- Keep backups on the deployment host only, per the user decision. Do not add
  off-host backup storage, synchronization or related setup requirements.
- README and research documentation are written in Chinese; code identifiers are
  English. Keep the initial framework small and add integrations when requested.
