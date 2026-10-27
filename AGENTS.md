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
- Research and backtests cover U.S. stocks and ETFs and calculate all amounts in
  USD. Missing provider currency fields are not an admission blocker in this
  scope; normalized research data may declare USD as a project convention without
  an additional currency lookup. Preserve raw fields and historical records;
  do not describe the convention as a provider-returned currency. Foreign-exchange
  conversion and multi-currency research are out of scope.
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
- IBKR is the authoritative source for broker accounts, orders, fills, costs and
  execution market data. Alpaca SIP history is explicitly permitted for offline
  quantitative research and backtests, with issuer dividend evidence and recorded
  corporate-action coverage. Keep its source as alpaca and its exploratory scope;
  do not substitute or merge it into IBKR records or broker execution. Freeze raw
  captures and validation evidence with research results. Preserve all legacy
  provenance, registrations, journals and out-of-sample status.
- The SPY or SPY/QQQ funnel is a preliminary price-based research watchlist. It may
  retain unverified dividend, corporate-action, valuation and earnings-event
  coverage as explicit limitations. Its FOCUS/WATCH rows must remain
  trade_eligible=false and must not replace a validated factor pool, backtest
  execution inputs or broker actions. Keep full trading admission unchanged.
- Full stock-selection backtests use the weekly union of contemporaneously known
  SPY and QQQ holdings. Never substitute current constituents for historical ones.
  Evaluate weekly candidates together with existing holdings, pending orders and
  corporate-action entitlements in one continuous account. Preserve capital,
  costs, settlement, cooldown and risk state across weeks and validation windows.
  Delistings, trading halts, splits, mergers and spinoffs require explicit event
  treatment; missing evidence must not become a fabricated fill or a silently
  removed security. Historical walk-forward replay of already inspected data
  remains known-history research. See docs/research/weekly-dynamic-backtest.md.
- The weekly rank-rotation versus hold-until-exit comparison uses free data only.
  Keep the two policies explicit and all other inputs and costs identical. A
  ranking dropout is distinct from an independent technical or risk exit. Do not
  substitute current membership or an index proxy to hide missing ETF history.
- The user explicitly changed the 2026-10-26 experiment to the current fixed
  513-stock universe. Freeze that exact list and rerun the weekly funnel inside
  it; do not require historical ETF membership for this experiment. Label it as
  current-universe, known-history research with survivorship bias, not the
  historical-membership backtest above. Preserve original membership dates,
  provider provenance and all earlier research records.
- QQQ buy-and-hold is the primary benchmark for the fixed-universe experiment.
  Report after-cost excess return against QQQ explicitly; lower drawdown alone
  does not satisfy the user's return objective. Compare frozen initial holdings,
  entry/exit-only management and prespecified rebalance frequencies without
  changing the screening thresholds after inspecting the results. Preserve all
  attempted configurations and label comparisons on inspected history accordingly.
- The user's live capital is USD 5,000 under W-8BEN as a mainland China tax
  resident. Count U.S.-side tax only: no U.S. tax on stock or ETF price gains;
  cash dividends net of the 10% treaty withholding (30% without the treaty
  claim), confirmed against IBKR withholding records. Use the principal ladder
  for new research and accounts: below principal stop new or larger stock
  positions while keeping QQQ and existing stock exits; at or below half of
  principal liquidate next session and terminate permanently. Gains above
  principal carry no account-level drawdown lock. Keep the legacy peak-drawdown
  rule unchanged for existing accounts and frozen studies. See
  docs/research/principal-risk-and-tax.md.
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
