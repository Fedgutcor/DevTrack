#!/usr/bin/env bash
# Wrapper de arranque para el daemon DevTrack en nodos de tu flota. Pensado
# para invocarse desde systemd (Linux) o launchd (macOS) — ver
# scripts/devtrack.service.example para el unit systemd.
set -euo pipefail
export PATH="$HOME/.local/bin:$PATH"
DEVTRACK_DIR="$HOME/projects/devtrack"
cd "$DEVTRACK_DIR"
exec "$DEVTRACK_DIR/.venv/bin/python" -m devtrack.main
