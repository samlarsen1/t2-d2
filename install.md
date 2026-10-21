# Installing T2-D2 on a Raspberry Pi

This guide installs T2-D2 from GitHub with [uv](https://github.com/astral-sh/uv) and runs every
trading session automatically with systemd timers. It works on any Debian-based Linux machine with
systemd; the examples assume a Raspberry Pi.

**How it works:** one systemd *service* (`t2d2@.service`) runs a single session, and one *timer*
per session starts it at the time set in [`config/schedules.yaml`](config/schedules.yaml). Times
are in each market's local time zone (Europe/London, America/New_York), so runs follow
daylight-saving changes automatically.

Why systemd timers rather than cron:

- **Time zones:** each timer states its own zone; Raspberry Pi OS's cron may not honour `CRON_TZ`.
- **No late runs:** if the Pi is off at a session's time, that run is skipped, not fired later.
- **Clock sync:** runs wait until the clock is synced after boot (the Pi has no clock battery).
- **Logs:** output goes to the system journal, which is searchable and rotated automatically.

All commands run **on the Pi, as your normal login user** (not root) unless stated otherwise.

---

## 1. Prerequisites

- Raspberry Pi 3, 4, 5 or Zero 2 W
- **64-bit** Raspberry Pi OS (Bookworm or later); Lite is fine. Pre-built pandas and numpy
  packages exist for 64-bit ARM but not for 32-bit, where they would have to be compiled.
- Network access and SSH to the Pi
- Read access to the GitHub repository
- Trading212 API key and secret (live or demo)

Python 3.12 is required. Raspberry Pi OS ships an older version, so uv installs 3.12 for you in
step 4.

Optionally, set the Pi's time zone so log timestamps show UK time (timers are unaffected):

```bash
sudo timedatectl set-timezone Europe/London
```

## 2. Install git and uv

```bash
sudo apt update && sudo apt install -y git
curl -LsSf https://astral.sh/uv/install.sh | sh
source ~/.local/bin/env
uv --version
```

## 3. Clone the repository

The repository is private, so give the Pi a read-only **deploy key** (an SSH key that can only
read this one repository):

```bash
ssh-keygen -t ed25519 -f ~/.ssh/t2d2_deploy -N "" -C "t2d2-pi"
cat ~/.ssh/t2d2_deploy.pub
```

1. On GitHub, open the repository's **Settings → Deploy keys → Add deploy key**.
2. Paste the public key and leave **Allow write access** unticked.
3. Point SSH at the key and clone:

```bash
cat >> ~/.ssh/config <<'EOF'
Host github.com
  IdentityFile ~/.ssh/t2d2_deploy
  IdentitiesOnly yes
EOF
git clone git@github.com:samlarsen1/t2-d2.git ~/t2-d2
```

## 4. Install Python and dependencies

```bash
cd ~/t2-d2
uv python install 3.12
uv sync --all-packages --no-dev --python 3.12
```

This creates `~/t2-d2/.venv` with everything needed to run the scheduler.

## 5. Configure secrets

```bash
cd ~/t2-d2
cp .env.example .env
chmod 600 .env
nano .env
```

Fill in `T212_API_KEY` and `T212_API_SECRET`, choose `T212_BASE_URL` (live or demo). Each ticker's
strategy is set in `config/stocks.yaml`, not `.env`. **Leave `DRY_RUN=true`** until you have checked a few days of runs (step 10).

The scheduler finds `.env` in the repository root automatically.

Optionally, add `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` to get a Telegram message for
every trade; see [Telegram Notifications](README.md#telegram-notifications).

## 6. Smoke-test by hand

```bash
cd ~/t2-d2
.venv/bin/python services/scheduler/src/scheduler/main.py --session daily_close_wrap
.venv/bin/python services/scheduler/src/scheduler/main.py --session eu_morning
```

`daily_close_wrap` is report-only: it reads your account and logs a summary, so it is the safest
first check. The second command runs a full trading cycle in dry-run mode. Each should finish by
printing a result summary.

## 7. Install the systemd service and timers

Create the service that runs one session (`%i` is replaced by the session name; `$USER` and
`$HOME` are filled in when you paste this):

```bash
sudo tee /etc/systemd/system/t2d2@.service >/dev/null <<EOF
[Unit]
Description=T2-D2 trading session %i
Wants=network-online.target
After=network-online.target time-sync.target

[Service]
Type=oneshot
User=$USER
WorkingDirectory=$HOME/t2-d2
ExecStart=$HOME/t2-d2/.venv/bin/python services/scheduler/src/scheduler/main.py --session %i
TimeoutStartSec=15min
EOF
```

`TimeoutStartSec` stops a hung run (e.g. a network stall) from blocking the next one.

Create one timer per session, reading the times from `config/schedules.yaml`:

```bash
cd ~/t2-d2
.venv/bin/python -c 'import yaml; [print(k, v["schedule"]) for k, v in yaml.safe_load(open("config/schedules.yaml"))["sessions"].items()]' |
while read -r session schedule; do
  sudo tee /etc/systemd/system/t2d2-$session.timer >/dev/null <<EOF
[Unit]
Description=T2-D2 $session session

[Timer]
OnCalendar=$schedule
Unit=t2d2@$session.service
AccuracySec=1s
Persistent=false

[Install]
WantedBy=timers.target
EOF
  echo "created t2d2-$session.timer ($schedule)"
done
```

Enable clock-sync waiting and start the timers:

```bash
sudo systemctl enable --now systemd-time-wait-sync.service
sudo systemctl daemon-reload
for t in /etc/systemd/system/t2d2-*.timer; do sudo systemctl enable --now "$(basename "$t")"; done
```

## 8. Check it is scheduled

```bash
systemctl list-timers 't2d2-*'
```

You should see five timers with their next run time. To see when a schedule fires in UTC:

```bash
systemd-analyze calendar "Mon..Fri 10:00 America/New_York"
```

## 9. Monitor runs

```bash
journalctl -u 't2d2@*' --since today       # all of today's runs
journalctl -u t2d2@us_morning -n 100       # last run of one session
journalctl -u 't2d2@*' -f                  # follow live
systemctl --failed                         # runs that exited with errors
sudo systemctl start t2d2@eu_morning       # run a session now
```

Keep logs across reboots (Raspberry Pi OS may otherwise keep them only in memory):

```bash
sudo mkdir -p /var/log/journal && sudo systemctl restart systemd-journald
```

## 10. Go live

Once the dry-run logs look right, set `DRY_RUN=false` in `~/t2-d2/.env`. Each run reads `.env`
fresh, so nothing needs restarting.

## Updating

```bash
cd ~/t2-d2
git pull
uv sync --all-packages --no-dev
```

If `config/schedules.yaml` changed its `schedule` times, re-run the timer step in step 7, then:

```bash
sudo systemctl daemon-reload
sudo systemctl restart 't2d2-*.timer'
```

## Changing the schedule

- **Change a time:** edit `schedule` in `config/schedules.yaml` (systemd
  [OnCalendar](https://www.freedesktop.org/software/systemd/man/latest/systemd.time.html) format),
  then follow "Updating" above. Check the format first with `systemd-analyze calendar "<schedule>"`.
- **Pause a session:** set `enabled: false` for it in `config/schedules.yaml`. It is read on every
  run, so the session exits straight away without touching the timers.
- **Add trading holidays:** add dates to `blackout_dates` in `config/schedules.yaml`.

## Uninstalling

```bash
for t in /etc/systemd/system/t2d2-*.timer; do sudo systemctl disable --now "$(basename "$t")"; done
sudo rm /etc/systemd/system/t2d2@.service /etc/systemd/system/t2d2-*.timer
sudo systemctl daemon-reload
rm -rf ~/t2-d2
```

## Troubleshooting

| Problem | Fix |
|---|---|
| `uv: command not found` | Run `source ~/.local/bin/env`, or open a new shell. |
| `git clone` fails with `Permission denied (publickey)` | Check the deploy key was added on GitHub and `~/.ssh/config` points at it; test with `ssh -T git@github.com`. |
| pandas or numpy tries to compile during `uv sync` | You are on 32-bit Raspberry Pi OS; reinstall with the 64-bit image. |
| A timer never fires | `systemctl list-timers 't2d2-*'` shows the next run; check the timer is enabled and `systemd-analyze calendar` accepts its schedule. |
| Run fails with `KeyError: 'T212_API_KEY'` | `.env` is missing or not in `~/t2-d2`; check step 5. |
| Runs fire at the wrong time after a reboot | Check `timedatectl` shows `System clock synchronized: yes`. |
