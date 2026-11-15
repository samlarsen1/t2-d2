"""Render T2-D2's systemd units: the session service, and one timer per enabled session.

Run by t2-hq's bin/t2-deploy with the deployed app's Python:

    .venv/bin/python deploy/systemd/render.py OUT_DIR APP_DIR

Timers come from ``config/schedules.yaml``, so a schedule change takes effect at the next deploy.
"""

from __future__ import annotations

import sys
from pathlib import Path

import yaml

TIMER = """\
# Rendered by deploy/systemd/render.py from config/schedules.yaml; don't edit.
[Unit]
Description=T2-D2 {session} session

[Timer]
OnCalendar={schedule}
Unit=t2d2@{session}.service
AccuracySec=1s
# A session missed while the machine was off or asleep is skipped, not fired late.
Persistent=false

[Install]
WantedBy=timers.target
"""


def render(out_dir: Path, app_dir: Path) -> list[Path]:
    """Write the units into ``out_dir`` and return their paths."""
    here = Path(__file__).resolve().parent
    out_dir.mkdir(parents=True, exist_ok=True)
    service = (here / "t2d2@.service").read_text().replace("@APP_DIR@", str(app_dir))
    written = [out_dir / "t2d2@.service"]
    written[0].write_text(service)

    schedules = yaml.safe_load((app_dir / "config" / "schedules.yaml").read_text())
    for session, cfg in schedules["sessions"].items():
        if not cfg.get("enabled", True):
            continue
        timer = out_dir / f"t2d2-{session}.timer"
        timer.write_text(TIMER.format(session=session, schedule=cfg["schedule"]))
        written.append(timer)
    return written


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("usage: render.py OUT_DIR APP_DIR", file=sys.stderr)
        return 2
    for path in render(Path(argv[0]), Path(argv[1]).resolve()):
        print(path)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
