# T2-D2

uv workspace (Python 3.12): `packages/` (t2d2-client, market-data, algo, notifier) + `services/scheduler`.

## Commands

```bash
.venv/bin/pytest                         # tests (packages/, services/)
.venv/bin/pre-commit run --all-files     # detect-secrets, ruff, mypy --strict, pytest
uv sync                                  # install/update deps (uv.lock)
.venv/bin/python services/scheduler/src/scheduler/main.py --session <session>
```

Sessions: `eu_morning`, `eu_afternoon`, `us_morning`, `us_afternoon`, `daily_close_wrap`. Dry-run by default (`DRY_RUN=true`).

## Rules

- **README.md is the developer entry point**: any new run/setup/test/lint command or env var must be documented there with copy-paste-ready commands (Quick Start, Local Setup, Tests, Scheduler, Services, Linters, Env Vars table, Troubleshooting).
- **Never commit secrets.** Secrets live in `.env` (gitignored); document vars in `.env.example` with placeholders. Don't log exception messages that may contain sensitive data.
- Keep the webhook SSRF guard and `.dockerignore` exclusions intact.
- Style: ruff (line length 100), full type hints passing `mypy --strict`, Google-style docstrings on public APIs, structured logging, specific exceptions — never swallow silently.
- Tests: add for every feature/fix, colocated under each package's `tests/`. Mock all external APIs with realistic payloads, including error cases (timeouts, 5xx, rate limits).
- Git: atomic commits, clear messages, no force-push to shared branches.
- Keep changes scoped — no unrelated refactors alongside fixes.
