🇺🇸 [English](README.md) | 🇨🇴 Español

# DevTrack

[![PyPI version](https://img.shields.io/pypi/v/devtrack-local.svg)](https://pypi.org/project/devtrack-local/)
[![Python versions](https://img.shields.io/pypi/pyversions/devtrack-local.svg)](https://pypi.org/project/devtrack-local/)
[![License](https://img.shields.io/badge/License-Apache%202.0-blue.svg)](LICENSE)

Tracker de actividad de desarrollo, local-first. Registra líneas escritas, archivos editados, sesiones y comandos Bash — con dashboard web y resúmenes opcionales de productividad vía Ollama.

**No envía datos a ningún servidor. Sin cuentas. Sin API keys.**

---

## Instalación rápida

```bash
pip install devtrack-local
devtrack start
```

El dashboard abre en `http://127.0.0.1:17321`.

Para una guía de instalación más detallada (incluyendo Windows), ver [docs/es/instalacion.md](docs/es/instalacion.md).

---

## Requisitos

- Python 3.11 o superior
- macOS (integración con LaunchAgent) o Linux (inicio manual)
- [Ollama](https://ollama.com) — opcional, para resúmenes IA locales

---

## Uso

```bash
devtrack start        # Inicia el daemon + abre el dashboard en el browser
devtrack stop         # Detiene el daemon y elimina el LaunchAgent
devtrack open         # Abre el dashboard (el daemon debe estar corriendo)
devtrack status       # Estado del daemon + URL del dashboard

devtrack              # Resumen del día en terminal
devtrack week         # Historial de los últimos 14 días
devtrack files        # Archivos editados hoy
devtrack help         # Lista completa de comandos
```

---

## Dashboard

Dashboard web en `http://127.0.0.1:17321`:

- Métricas del día: líneas escritas, archivos editados, sesiones, comandos Bash
- Gráfica de barras de los últimos 7 días
- Tabla de archivos más editados con detección automática de proyecto y lenguaje
- Heatmap de contribuciones estilo GitHub (últimas 8 semanas)
- Resumen IA de productividad (requiere Ollama)

Se auto-refresca cada 30 segundos.

---

## Resúmenes IA con Ollama (opcional)

Sin internet. Sin API keys. Todo corre en tu máquina.

```bash
brew install ollama
ollama pull qwen2.5-coder:3b
# Opcional: perfil personalizado para DevTrack
ollama create qwen-dev -f Modelfile.qwen-dev
```

Una vez que Ollama esté corriendo, el bloque "Resumen del día" en el dashboard se activa automáticamente.

---

## Datos y privacidad

Todos los datos se almacenan localmente en:

```
~/.local/share/devtrack/devtrack.sqlite3
```

El daemon escucha en `127.0.0.1:17321` y NO está expuesto a la red.

---

## Desinstalación

```bash
devtrack stop
pip uninstall devtrack-local
rm -rf ~/.local/share/devtrack/
```

---

## Contribuir

Ver la guía completa en [docs/es/contribuir.md](docs/es/contribuir.md).

---

## Creado por

Hecho por [Ultragresion](https://ultragresion.com) — porque decir *"hoy programé un montón"* suena muy diferente cuando tienes el heatmap para demostrarlo.
