# T2-D2

## Local Execution Instructions

**All local run and execute instructions must be clearly documented in README.md** — not just in CLAUDE.md. README.md is the entry point for developers, and should contain complete, copy-paste-ready commands.

### Required README.md sections:
- **Quick Start** — Prerequisites, Python version, key dependencies
- **Local Setup** — Initial environment configuration (virtualenv, dependencies, .env)
- **Running Tests** — Full test command with coverage options
- **Running the Scheduler** — How to run locally with all session options
- **Running Services** — Any other local services (API server, workers, etc.)
- **Running Linters & Checks** — Pre-commit, type checking, formatting
- **Environment Variables** — Complete table with all required/optional vars
- **Troubleshooting** — Common issues and solutions

Keep commands in README.md DRY by referencing CLAUDE.md for detailed explanations, but all commands should work when copy-pasted directly.

---

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

## Pre-commit hooks

Run pre-commit locally before pushing:

```bash
.venv/bin/pre-commit run --all-files
```

Pre-commit checks for:
- Secret scanning (credentials, API keys, tokens)
- Code formatting and linting
- Type checking
- Dependency vulnerabilities

Enable automatic checks on every commit:

```bash
.venv/bin/pre-commit install
```

## Credential & Security

- **Never commit secrets**: API keys, auth tokens, database credentials, or private data
- All secrets go in `.env` or environment variables (excluded from git via `.gitignore`)
- Use `.env.example` to document required env vars (with placeholder values only)
- Pre-commit hooks scan for common secret patterns and will block commits containing credentials
- Webhook SSRF guard is enabled to prevent exfiltration attacks
- `.dockerignore` excludes secrets and dev files from image builds

## Python & Dependency Management

Keep the environment up-to-date:

```bash
# Upgrade Python interpreter (use pyenv or similar)
# Ensure .python-version or pyproject.toml specifies the version

# Upgrade pip, setuptools, wheel
.venv/bin/pip install --upgrade pip setuptools wheel

# Upgrade production dependencies
.venv/bin/pip install --upgrade -r requirements.txt

# Upgrade development dependencies
.venv/bin/pip install --upgrade -r requirements-dev.txt
```

Lock dependencies for reproducibility:

```bash
pip-compile requirements.in
pip-compile requirements-dev.in
```

## Vulnerability Scanning

Scan dependencies for known vulnerabilities:

```bash
# Using safety
.venv/bin/safety check

# Using pip-audit
.venv/bin/pip-audit
```

Pre-commit runs vulnerability checks automatically. Fix vulnerabilities promptly and document reasons if not immediately patched.

## Unit Tests

Write unit tests for all new features and bug fixes:

```bash
.venv/bin/pytest -v
.venv/bin/pytest --cov=src tests/
```

Test structure:
- `tests/` directory mirrors `src/` structure
- Test files: `test_*.py` or `*_test.py`
- Use fixtures for setup/teardown
- Aim for >80% code coverage on critical paths
- Mock external dependencies (see below)

## Mocking Dependency APIs

Mock external services for local testing:

```python
from unittest.mock import Mock, patch

# Mock API responses
with patch('requests.get') as mock_get:
    mock_get.return_value.status_code = 200
    mock_get.return_value.json.return_value = {'result': 'data'}
    # Test code here
```

Use factories/fixtures for reusable test data:

```python
@pytest.fixture
def sample_order(db):
    return Order.objects.create(user_id=1, amount=100.00)
```

Keep mocks close to reality:
- Mock response structures match actual API responses
- Mock error cases (timeouts, 5xx, rate limits)
- Use `responses` library for HTTP mocking or `factory_boy` for ORM objects

## Industry Standards & Best Practices

- **Code style**: Follow PEP 8 with Black formatter, isort for imports
- **Type hints**: Use type annotations throughout; mypy for type checking
- **Logging**: Structured logging with appropriate levels (DEBUG, INFO, WARNING, ERROR)
- **Error handling**: Specific exceptions, meaningful error messages; don't suppress exceptions silently
- **Documentation**: Docstrings for modules, classes, public functions (Google/Numpy style)
- **Git practices**: Atomic commits, clear messages, no force pushes to shared branches
- **API design**: RESTful conventions, semantic HTTP status codes, versioning strategy
- **Environment parity**: Dev, staging, and production use the same code and minimal config differences

## Token Consumption Optimization

When working with Claude Code or LLM-based tools:

- **Be specific**: Clear, detailed commit messages and PR descriptions reduce back-and-forth
- **Provide context**: Link to issues, related PRs, and failing tests in prompts
- **Batch changes**: Group related edits in one request rather than multiple small requests
- **Review before asking**: Ensure code compiles and tests pass before asking for help
- **Use git context**: Reference specific line numbers and file paths for precision
- **Cache code patterns**: Document common patterns once (in CLAUDE.md or README) and reference instead of re-explaining
- **Minimize side work**: Don't ask for refactoring, documentation, or cleanup alongside bug fixes—separate concerns
