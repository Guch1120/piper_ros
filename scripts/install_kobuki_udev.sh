#!/usr/bin/env bash
set -euo pipefail

REPO_DIR="${COTYAKA_REPO_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
RULE_SRC="$REPO_DIR/udev/60-kobuki.rules"
RULE_DST="/etc/udev/rules.d/60-kobuki.rules"

log() { echo "[cotyaka-kobuki-udev] $*"; }

[[ -f "$RULE_SRC" ]] || { log "Rule file not found: $RULE_SRC"; exit 1; }
command -v udevadm >/dev/null || { log "udevadm not found"; exit 1; }

if [[ $EUID -eq 0 ]]; then
  SUDO=()
else
  command -v sudo >/dev/null || { log "sudo is required"; exit 1; }
  SUDO=(sudo)
fi

log "Installing Kobuki udev rule to $RULE_DST"
"${SUDO[@]}" install -m 0644 "$RULE_SRC" "$RULE_DST"
"${SUDO[@]}" udevadm control --reload-rules
"${SUDO[@]}" udevadm trigger --subsystem-match=tty

if [[ -e /dev/kobuki ]]; then
  log "Ready: /dev/kobuki -> $(readlink -f /dev/kobuki)"
else
  log "/dev/kobuki is not present yet. Unplug/replug the Kobuki USB cable, then check: ls -l /dev/kobuki"
fi
