#!/usr/bin/env bash
# Push periódico de la devtrack.sqlite3 local hacia tentomon (el "cerebro" de
# la flota), como snapshot por-host bajo hosts/<hostname>.sqlite3.
#
# Por qué push y no pull: tentomon no puede iniciar SSH hacia el Mac (no hay
# sshd escuchando ahí), pero el Mac SÍ puede alcanzar a tentomon vía Tailscale.
# Este script corre en la máquina ORIGEN (Mac u otro nodo dev) e ignora
# fallos de red de forma silenciosa — si tentomon está offline o el Mac está
# dormido cuando el LaunchAgent debería disparar, simplemente no hay sync en
# ese ciclo y el próximo intento (siguiente StartInterval) lo retoma. Nunca
# debe fallar de forma ruidosa: es un job de fondo, no un servicio crítico.
#
# Ver Engram architecture/devtrack-fleet.
set -uo pipefail

DEVTRACK_DB="$HOME/.local/share/devtrack/devtrack.sqlite3"
REMOTE_HOST="${DEVTRACK_FLEET_REMOTE:-ultragresion@100.112.158.14}"
REMOTE_DIR="~/.local/share/devtrack/hosts"
LOCAL_HOSTNAME="$(hostname)"
LOG_FILE="$HOME/.local/share/devtrack/fleet-sync.log"

mkdir -p "$(dirname "$LOG_FILE")"

if [ ! -f "$DEVTRACK_DB" ]; then
  echo "$(date -Iseconds) skip: no existe $DEVTRACK_DB" >> "$LOG_FILE"
  exit 0
fi

ssh -o ConnectTimeout=8 -o BatchMode=yes "$REMOTE_HOST" "mkdir -p $REMOTE_DIR" >/dev/null 2>&1

if rsync -az --timeout=15 -e "ssh -o ConnectTimeout=8 -o BatchMode=yes" \
    "$DEVTRACK_DB" "$REMOTE_HOST:$REMOTE_DIR/$LOCAL_HOSTNAME.sqlite3" 2>>"$LOG_FILE"; then
  echo "$(date -Iseconds) ok: sync $LOCAL_HOSTNAME -> $REMOTE_HOST" >> "$LOG_FILE"
else
  echo "$(date -Iseconds) warn: sync fallido (tentomon offline o inalcanzable) — reintenta en el próximo ciclo" >> "$LOG_FILE"
fi

exit 0
