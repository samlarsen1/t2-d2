"""The T2 droid contract: run reports, exit codes and locks around a session."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from scheduler import main, t2contract
from test_order_expiry import FakeNotifier, notifier  # noqa: F401 - pytest fixture


def only_report(base: Path) -> dict[str, Any]:
    reports = list((base / "runs").glob("*-session-eu-morning.json"))
    assert len(reports) == 1
    return json.loads(reports[0].read_text())  # type: ignore[no-any-return]


def test_session_writes_a_contract_report(
    notifier: FakeNotifier,  # noqa: F811
    t2_contract_dirs: Path,
) -> None:
    assert main.main(["--session", "eu_morning", "--dry-run"]) == 0

    report = only_report(t2_contract_dirs)
    assert report["schema"] == "t2.run-report/1"
    assert (report["droid"], report["command"]) == ("t2-d2", "session eu_morning")
    assert (report["status"], report["dry_run"]) == ("ok", True)
    assert report["result"]["session"] == "eu_morning"
    assert report["result"]["trades"] == []
    assert "trades simulated" in report["summary"]


def test_missing_keys_exit_2(
    notifier: FakeNotifier,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
    t2_contract_dirs: Path,
) -> None:
    monkeypatch.delenv("T212_API_KEY")

    assert main.main(["--session", "eu_morning"]) == 2
    report = only_report(t2_contract_dirs)
    assert report["status"] == "config_error"
    assert report["errors"] == ["Missing environment variables: T212_API_KEY"]


def test_blackout_day_is_skipped(
    notifier: FakeNotifier,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
    t2_contract_dirs: Path,
) -> None:
    monkeypatch.setattr(main, "is_blackout", lambda *_: True)

    assert main.main(["--session", "eu_morning"]) == 3
    assert only_report(t2_contract_dirs)["status"] == "skipped"
    assert notifier.messages == []


@pytest.mark.parametrize("lock", ["run", "t212"])
def test_held_lock_skips_without_touching_the_account(
    notifier: FakeNotifier,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
    t2_contract_dirs: Path,
    lock: str,
) -> None:
    monkeypatch.setenv("T2_T212_LOCK_TIMEOUT", "0")
    holder = t2contract.run_lock("t2-d2") if lock == "run" else t2contract.t212_lock(0)
    # flock locks belong to an open file, so the run's own open conflicts with this one.
    with holder:
        assert main.main(["--session", "eu_morning"]) == 3
    assert only_report(t2_contract_dirs)["status"] == "skipped"
    assert notifier.messages == []


def test_crash_is_reported_then_raised(
    notifier: FakeNotifier,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
    t2_contract_dirs: Path,
) -> None:
    from test_order_expiry import FakeProvider

    monkeypatch.setattr(FakeProvider, "fetch_error", TimeoutError("timed out"))

    with pytest.raises(TimeoutError):
        main.main(["--session", "eu_morning"])
    report = only_report(t2_contract_dirs)
    assert (report["status"], report["errors"]) == ("failed", ["TimeoutError"])
