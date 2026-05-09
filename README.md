# DevTrack

[![PyPI version](https://img.shields.io/pypi/v/devtrack.svg)](https://pypi.org/project/devtrack/)
[![Python versions](https://img.shields.io/pypi/pyversions/devtrack.svg)](https://pypi.org/project/devtrack/)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![CI](https://github.com/ultragresion/devtrack/actions/workflows/ci.yml/badge.svg)](https://github.com/ultragresion/devtrack/actions/workflows/ci.yml)

Local-first development activity tracker. Tracks lines written, files edited, sessions, and Bash commands — with a web dashboard and optional AI summaries via Ollama.

**No data leaves your machine. No accounts. No API keys.**

---

## Quick install

```bash
pip install devtrack
devtrack start
```

Dashboard opens at `http://127.0.0.1:17321`.

---

## Requirements

- Python 3.11+
- macOS (LaunchAgent integration) or Linux (manual start)
- [Ollama](https://ollama.com) — optional, for local AI summaries

---

## Usage

```bash
devtrack start        # Start daemon + open dashboard in browser
devtrack stop         # Stop daemon and remove LaunchAgent
devtrack open         # Open dashboard (if daemon is already running)
devtrack status       # Show running status + dashboard URL

devtrack              # Today's summary in terminal
devtrack week         # Last 14 days history
devtrack files        # Files edited today
devtrack help         # Full command list
```

---

## Dashboard

Web dashboard at `http://127.0.0.1:17321`:

- Daily metrics: lines written, files edited, sessions, Bash commands
- Bar chart for the last 7 days
- Most-edited files table with project + language detection
- Contribution heatmap (GitHub-style, last 8 weeks)
- AI productivity summary (requires Ollama)

Auto-refreshes every 30 seconds.

---

## Optional: AI summaries with Ollama

No internet required. No API keys.

```bash
brew install ollama
ollama pull qwen2.5-coder:3b
# Optional: use the DevTrack Modelfile
ollama create qwen-dev -f Modelfile.qwen-dev
```

Once Ollama is running, the "Day Summary" block in the dashboard activates automatically.

---

## Data

All data is stored locally:

```
~/.local/share/devtrack/devtrack.sqlite3
```

The daemon listens on `127.0.0.1:17321` and is NOT exposed to the network.

---

## Uninstall

```bash
devtrack stop
pip uninstall devtrack
rm -rf ~/.local/share/devtrack/
```

---

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md).

---

---

# DevTrack — Español

Tracker de actividad de desarrollo, local-first. Registra líneas escritas, archivos editados, sesiones y comandos Bash — con dashboard web y resúmenes opcionales vía Ollama.

**No envía datos a ningún servidor. Sin cuentas. Sin API keys.**

## Instalación rápida

```bash
pip install devtrack
devtrack start
```

El dashboard abre en `http://127.0.0.1:17321`.

## Requisitos

- Python 3.11+
- macOS (integración LaunchAgent) o Linux (inicio manual)
- [Ollama](https://ollama.com) — opcional, para resúmenes IA locales

## Uso

```bash
devtrack start        # Inicia el daemon + abre el dashboard en el browser
devtrack stop         # Detiene el daemon y elimina el LaunchAgent
devtrack open         # Abre el dashboard (si el daemon ya corre)
devtrack status       # Estado del daemon + URL del dashboard

devtrack              # Resumen del día en terminal
devtrack week         # Historial de los últimos 14 días
devtrack files        # Archivos editados hoy
devtrack help         # Lista completa de comandos
```

## Resúmenes IA con Ollama (opcional)

```bash
brew install ollama
ollama pull qwen2.5-coder:3b
ollama create qwen-dev -f Modelfile.qwen-dev  # opcional
```

## Desinstalación

```bash
devtrack stop
pip uninstall devtrack
rm -rf ~/.local/share/devtrack/
```
