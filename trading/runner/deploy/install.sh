#!/usr/bin/env bash
# Install the runner as systemd *user* units (no root needed).
#
#   runner/deploy/install.sh                # install + enable timers
#   runner/deploy/install.sh --uninstall    # disable + remove
#
# Env overrides: TRADING_DIR (default: this repo's trading/), PYTHON (default:
# trading/.venv/bin/python, else python3 on PATH), UNIT_DIR (default:
# ~/.config/systemd/user), NO_SYSTEMCTL=1 (only write the unit files).
#
# To keep running while you are logged out: loginctl enable-linger "$USER"
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TRADING_DIR="${TRADING_DIR:-$(cd "$HERE/../.." && pwd)}"
UNIT_DIR="${UNIT_DIR:-${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user}"
UNITS=(trading-runner.service trading-runner.timer trading-health.service trading-health.timer)
TIMERS=(trading-runner.timer trading-health.timer)

systemctl_user() {
  if [[ "${NO_SYSTEMCTL:-0}" == "1" ]]; then
    echo "skip: systemctl --user $*"
  else
    systemctl --user "$@"
  fi
}

if [[ "${1:-}" == "--uninstall" ]]; then
  systemctl_user disable --now "${TIMERS[@]}" || true
  for u in "${UNITS[@]}"; do rm -f "$UNIT_DIR/$u"; done
  systemctl_user daemon-reload
  echo "removed units from $UNIT_DIR (logs and trader/ state are kept)"
  exit 0
fi

if [[ -z "${PYTHON:-}" ]]; then
  if [[ -x "$TRADING_DIR/.venv/bin/python" ]]; then
    PYTHON="$TRADING_DIR/.venv/bin/python"
  else
    PYTHON="$(command -v python3)"
  fi
fi

[[ -f "$TRADING_DIR/runner/__main__.py" ]] || { echo "not a trading/ folder: $TRADING_DIR" >&2; exit 1; }
[[ -f "$TRADING_DIR/trader/runner.json" ]] || {
  echo "missing $TRADING_DIR/trader/runner.json: cp config/runner.example.json trader/runner.json" >&2; exit 1; }
case "$TRADING_DIR$PYTHON" in *"|"*|*$'\n'*) echo "path contains | or a newline" >&2; exit 1;; esac

"$PYTHON" -c "import numpy" || { echo "numpy missing for $PYTHON: pip install -r requirements.txt" >&2; exit 1; }
(cd "$TRADING_DIR" && "$PYTHON" -m runner --quiet tick --dry-run >/dev/null) || {
  echo "dry-run tick failed: fix trader/runner.json first" >&2; exit 1; }

mkdir -p "$UNIT_DIR"
for u in "${UNITS[@]}"; do
  sed -e "s|@TRADING_DIR@|$TRADING_DIR|g" -e "s|@PYTHON@|$PYTHON|g" "$HERE/$u" > "$UNIT_DIR/$u"
done
systemctl_user daemon-reload
systemctl_user enable --now "${TIMERS[@]}"
echo "installed to $UNIT_DIR"
echo "  trading dir: $TRADING_DIR"
echo "  python:      $PYTHON"
echo "check:  systemctl --user list-timers 'trading-*'"
echo "logs:   journalctl --user -u trading-runner -f   and   $TRADING_DIR/logs/runner/runner.jsonl"
