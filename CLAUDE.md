# T2-D2

uv workspace (Python 3.12): `packages/` (t2d2-client, market-data, algo) + `services/scheduler`.

## System context

Part of the T2 droid system. The hub repo is `../t2-hq`:
read its `ARCHITECTURE.md` and `PLAN.md` before changing how this repo interacts with the others.
Repos sit side by side in one development directory (`$T2_SRC`) and one apps directory (`$T2_APPS`).

- `../t2-k2`: harvests gains from overbought holdings; places sell orders
- `../t2-bb8`: harvests the Trading212 instrument list; metadata only
- `../t2-3po`: advisory council; reviews theses, strategy and configuration; read-only
- `../t2-hq`: hub; plan, architecture, orchestrator and Telegram interface (planned)

T2-D2 is the buy side of the execution layer. It trades by the rules in `config/`, with no LLM and no approval step in the order path. `t2-3po` reads `config/stocks.yaml` and `config/strategy.yaml` to suggest changes; a suggestion only takes effect as a reviewed change to those files.
This repo must keep working standalone: never import a sibling repo's code. Changes to the
shared droid contract (run reports, exit codes, locks) are agreed in `t2-hq` first.

## Commands

```bash
.venv/bin/pytest                         # tests (packages/, services/)
.venv/bin/pre-commit run --all-files     # detect-secrets, ruff, bandit, semgrep, pip-audit, mypy --strict, pytest
uv sync                                  # install/update deps (uv.lock)
.venv/bin/t2d2 --session <session>             # always writes a run report (var/runs)
```

Sessions: `eu_morning`, `eu_afternoon`, `us_morning`, `us_afternoon`, `deep_value_midweek`, `daily_close_wrap`. Dry-run by default (`DRY_RUN=true`).

## Rules

- **README.md is the developer entry point**: any new run/setup/test/lint command or env var must be documented there with copy-paste-ready commands (Quick Start, Local Setup, Tests, Scheduler, Services, Linters, Env Vars table, Troubleshooting).
- **Never commit secrets.** Secrets live in `.env` (gitignored); document vars in `.env.example` with placeholders. Don't log exception messages that may contain sensitive data.
- **Follow the T2 droid contract** (t2-hq `CONTRACT.md`): every run writes a run report and exits 0/1/2/3, runs take the run lock and, before any Trading212 call, the shared `t212_lock()`. `t2contract.py` is vendored from t2-hq: never edit it here; change it in t2-hq and run `bin/t2-contract sync`.
- Style: ruff (line length 100), full type hints passing `mypy --strict`, Google-style docstrings on public APIs, structured logging, specific exceptions — never swallow silently.
- Tests: add for every feature/fix, colocated under each package's `tests/`. Mock all external APIs with realistic payloads, including error cases (timeouts, 5xx, rate limits).
- Git: atomic commits, clear messages, no force-push to shared branches. Commit only on `feature/<name>`, `bug/<name>`, `task/<name>` or `hotfix/<name>` branches (lowercase-with-hyphens); never directly on `main`.
- Keep changes scoped — no unrelated refactors alongside fixes.
