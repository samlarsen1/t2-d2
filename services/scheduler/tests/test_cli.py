"""Tests for scheduler CLI argument parsing."""
from __future__ import annotations

import pytest
from scheduler.main import parse_args


@pytest.mark.parametrize(
    ("env_value", "flags", "expected"),
    [
        (None, [], True),
        ("true", [], True),
        ("false", [], False),
        ("FALSE", [], False),
        ("true", ["--no-dry-run"], False),
        ("false", ["--dry-run"], True),
        (None, ["--no-dry-run"], False),
    ],
)
def test_dry_run_resolution(
    monkeypatch: pytest.MonkeyPatch, env_value: str | None, flags: list[str], expected: bool
) -> None:
    if env_value is None:
        monkeypatch.delenv("DRY_RUN", raising=False)
    else:
        monkeypatch.setenv("DRY_RUN", env_value)

    args = parse_args(["--session", "us_morning", *flags])

    assert args.session == "us_morning"
    assert args.dry_run is expected


def test_invalid_session_rejected() -> None:
    with pytest.raises(SystemExit):
        parse_args(["--session", "asia_morning"])
