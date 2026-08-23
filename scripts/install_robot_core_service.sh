#!/usr/bin/env bash
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_DIR=/etc/cotyaka
ENV_FILE="$ENV_DIR/robot-core.env"
UNIT_DST=/etc/systemd/system/cotyaka-robot-core.service

if [[ ${EUID} -ne 0 ]]; then
  echo "Run with sudo: sudo bash scripts/install_robot_core_service.sh" >&2
  exit 1
fi

mkdir -p "$ENV_DIR"
if [[ ! -f "$ENV_FILE" ]]; then
  cp "$REPO_DIR/systemd/robot-core.env.example" "$ENV_FILE"
  sed -i "s|^COTYAKA_REPO_DIR=.*$|COTYAKA_REPO_DIR=$REPO_DIR|" "$ENV_FILE"
  echo "Created $ENV_FILE"
else
  echo "Keeping existing $ENV_FILE"
fi

cp "$REPO_DIR/systemd/cotyaka-robot-core.service" "$UNIT_DST"
systemctl daemon-reload
systemctl enable cotyaka-robot-core.service

echo "Installed and enabled cotyaka-robot-core.service"
echo "Start now with: sudo systemctl start cotyaka-robot-core"
