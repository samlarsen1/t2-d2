FROM python:3.12-slim

# Install uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app

# Copy workspace definition and all packages
COPY pyproject.toml pyproject.toml
COPY packages/ packages/
COPY services/scheduler/ services/scheduler/
COPY config/ config/

# Install the scheduler and all workspace dependencies
RUN uv sync --package t2d2-scheduler --no-dev

ENV PYTHONUNBUFFERED=1

ENTRYPOINT ["uv", "run", "--package", "t2d2-scheduler", "python", "-m", "scheduler.main"]
