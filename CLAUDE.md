# T2-D2

## Running tests

```bash
.venv/bin/pytest
```

## Running the scheduler locally

```bash
.venv/bin/python services/scheduler/src/scheduler/main.py --session <session>
```

Available sessions: `eu_morning`, `eu_afternoon`, `us_morning`, `us_afternoon`, `daily_close_wrap`

Runs in dry-run mode by default (`DRY_RUN=true`).
