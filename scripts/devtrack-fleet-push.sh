#!/usr/bin/env bash
# Push periódico de la devtrack.sqlite3 local hacia un host "cerebro" de tu
# flota (ej. un servidor propio siempre encendido), como snapshot por-host
# bajo hosts/<hostname>.sqlite3.
#
# Por qué push y no pull: si el host remoto no puede iniciar SSH hacia esta
# máquina (no hay sshd escuchando), pero esta máquina SÍ puede alcanzar al
# remoto (ej. vía Tailscale o tu VPN), conviene correr el push desde el
# origen. Este script corre en la máquina ORIGEN e ignora fallos de red de
# forma silenciosa — si el remoto está offline o esta máquina está dormida
# cuando el LaunchAgent debería disparar, simplemente no hay sync en ese
# ciclo y el próximo intento (siguiente StartInterval) lo retoma. Nunca debe
# fallar de forma ruidosa: es un job de fondo, no un servicio crítico.
#
# Configurar con la variable de entorno DEVTRACK_FLEET_REMOTE, ej.:
#   export DEVTRACK_FLEET_REMOTE="user@your-remote-host"
set -uo pipefail

DEVTRACK_DB="$HOME/.local/share/devtrack/devtrack.sqlite3"
REMOTE_HOST="${DEVTRACK_FLEET_REMOTE:-}"
REMOTE_DIR="~/.local/share/devtrack/hosts"
LOCAL_HOSTNAME="$(hostname)"
LOG_FILE="$HOME/.local/share/devtrack/fleet-sync.log"

mkdir -p "$(dirname "$LOG_FILE")"

if [ -z "$REMOTE_HOST" ]; then
  echo "$(date -Iseconds) skip: DEVTRACK_FLEET_REMOTE no está configurado" >> "$LOG_FILE"
  exit 0
fi

if [ ! -f "$DEVTRACK_DB" ]; then
  echo "$(date -Iseconds) skip: no existe $DEVTRACK_DB" >> "$LOG_FILE"
  exit 0
fi

ssh -o ConnectTimeout=8 -o BatchMode=yes "$REMOTE_HOST" "mkdir -p $REMOTE_DIR" >/dev/null 2>&1

if rsync -az --timeout=15 -e "ssh -o ConnectTimeout=8 -o BatchMode=yes" \
    "$DEVTRACK_DB" "$REMOTE_HOST:$REMOTE_DIR/$LOCAL_HOSTNAME.sqlite3" 2>>"$LOG_FILE"; then
  echo "$(date -Iseconds) ok: sync $LOCAL_HOSTNAME -> $REMOTE_HOST" >> "$LOG_FILE"
else
  echo "$(date -Iseconds) warn: sync fallido (remoto offline o inalcanzable) — reintenta en el próximo ciclo" >> "$LOG_FILE"
fi

exit 0
