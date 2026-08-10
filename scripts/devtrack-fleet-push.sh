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

# Un fallo de CONFIGURACIÓN no es lo mismo que un fallo de RED. La red se cae
# sola y se arregla sola: ahí el silencio es correcto (ver cabecera). Pero una
# variable sin definir no se arregla nunca — y saliendo con 0, launchd reporta
# éxito para siempre. Pasó: 15 horas de corridas "exitosas" cada 30 min sin
# enviar un byte, mientras el panel de flota mostraba esta máquina como "sin
# actividad". Salir != 0 hace que `launchctl list` muestre el código y que el
# problema sea visible sin leer este log.
if [ -z "$REMOTE_HOST" ]; then
  echo "$(date -Iseconds) ERROR: DEVTRACK_FLEET_REMOTE no está configurado — nada que sincronizar" >> "$LOG_FILE"
  echo "devtrack-fleet-push: DEVTRACK_FLEET_REMOTE no está configurado" >&2
  exit 78  # EX_CONFIG (sysexits.h): error de configuración, no transitorio
fi

if [ ! -f "$DEVTRACK_DB" ]; then
  echo "$(date -Iseconds) ERROR: no existe $DEVTRACK_DB" >> "$LOG_FILE"
  echo "devtrack-fleet-push: no existe $DEVTRACK_DB" >&2
  exit 66  # EX_NOINPUT: falta el origen; tampoco se arregla solo
fi

ssh -o ConnectTimeout=8 -o BatchMode=yes "$REMOTE_HOST" "mkdir -p $REMOTE_DIR" >/dev/null 2>&1

# Snapshot consistente ANTES de transferir. Rsyncar la .sqlite3 viva falla con
# "failed verification -- update discarded": DevTrack escribe mientras rsync
# copia, el checksum del final no coincide con el del principio y la
# transferencia se descarta entera. Con 121MB de DB eso son minutos de red
# tirados cada 30 min, y el destino quedándose con el snapshot viejo.
# `.backup` de sqlite3 produce una copia coherente (respeta el WAL, mismo
# criterio que ya se usa para los .db del backlog) y, al ser un archivo
# estático, rsync sí puede verificarla.
SNAPSHOT="$(mktemp -t devtrack-snapshot)" || exit 74  # EX_IOERR
trap 'rm -f "$SNAPSHOT" "$SNAPSHOT-wal" "$SNAPSHOT-shm"' EXIT

# `.timeout` NO es opcional (2026-08-10): sin el busy timeout, `.backup` falla con
# "Error: database is locked" en cuanto DevTrack esté escribiendo — que es SIEMPRE, porque
# el daemon escribe de forma continua sobre estos 138MB. El timer corrió durante días
# devolviendo `sqlite3 .backup falló` y dejando un snapshot de CERO bytes, mientras
# `launchctl list` mostraba exit 0 y nadie miraba /tmp/devtrack-fleet-sync.err.
#
# El comentario de arriba decía "mismo criterio que ya se usa para los .db del backlog", y
# ahí estaba la trampa: el del backlog lo hace con `Connection.backup()` de Python, que
# aplica el busy timeout del driver. El CLI no hereda nada — hay que pedírselo.
if ! sqlite3 -cmd ".timeout 30000" "$DEVTRACK_DB" ".backup '$SNAPSHOT'" 2>>"$LOG_FILE"; then
  echo "$(date -Iseconds) ERROR: no se pudo generar el snapshot consistente" >> "$LOG_FILE"
  echo "devtrack-fleet-push: sqlite3 .backup falló" >&2
  exit 74  # EX_IOERR: problema local, no transitorio de red
fi

if rsync -az --timeout=15 -e "ssh -o ConnectTimeout=8 -o BatchMode=yes" \
    "$SNAPSHOT" "$REMOTE_HOST:$REMOTE_DIR/$LOCAL_HOSTNAME.sqlite3" 2>>"$LOG_FILE"; then
  echo "$(date -Iseconds) ok: sync $LOCAL_HOSTNAME -> $REMOTE_HOST ($(wc -c <"$SNAPSHOT") bytes)" >> "$LOG_FILE"
else
  # Acá sí el silencio es correcto: la red se cae sola y se arregla sola.
  echo "$(date -Iseconds) warn: rsync fallido (remoto inalcanzable o red caída) — reintenta en el próximo ciclo" >> "$LOG_FILE"
fi

exit 0
