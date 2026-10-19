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
- Keep credentials, downloaded datasets and private reports out of Git. Use the
  ignored `data/` and `reports/` directories for generated research artifacts.
- README and research documentation are written in Chinese; code identifiers are
  English. Keep the initial framework small and add integrations when requested.
