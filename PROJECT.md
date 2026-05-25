# DevTrack

> Tracker local de actividad de desarrollo — publicado en PyPI como `devtrack-local`.
> Última actualización: 2026-05-23

---

## Filosofía

DevTrack es el espejo honesto de cómo trabaja un desarrollador. No juzga, no prescribe — solo registra. Líneas escritas, archivos editados, sesiones de trabajo, uso de IA. Esa data es el insumo para entender si el trabajo está rindiendo, qué proyectos están recibiendo atención real, y dónde hay deuda oculta.

**Principio:** No data leaves your machine. No accounts. No API keys.

---

## Stack

| Capa | Tecnología |
|------|-----------|
| Runtime | Python 3.11+ |
| Gestión | `uv` |
| Storage | SQLite (`~/.local/share/devtrack/devtrack.sqlite3`) |
| API | FastAPI + uvicorn, puerto 17321 |
| CLI | Click (`devtrack <comando>`) |
| File watching | watchdog |
| AI summaries | Ollama (opcional, local) |
| Deploy | PyPI como `devtrack-local` |
| CI | GitHub Actions |

### Schema SQLite
- `sessions` — sesiones de trabajo (start/end)
- `file_events` — archivos tocados por sesión
- `loc_deltas` — líneas agregadas/eliminadas por archivo
- `ai_usage` — uso de modelos IA (Claude, Ollama, etc.)

---

## Estado actual

**Versión:** 0.1.0 (Alpha) | **PyPI:** `pip install devtrack-local`

### Qué funciona
- Daemon en background con LaunchAgent (macOS)
- Dashboard web en puerto 17321
- CLI: `devtrack`, `devtrack week`, `devtrack files`, `devtrack report DATE`
- Tracking automático de archivos editados, líneas, sesiones
- AI summaries opcionales via Ollama
- Publicado y funcional en PyPI

### Oportunidad de integración
El SQLite de DevTrack tiene datos valiosos que el CC puede leer para:
- Reportes automáticos de progreso por proyecto
- Detectar qué proyectos llevan semanas sin actividad
- Alimentar el backlog con insights de productividad

---

## Próximos 3 pasos

1. **Integrar con CC** — agente en CC que lea `devtrack.sqlite3` y genere reporte semanal por proyecto
2. **Tracking de uso de IA más granular** — registrar tiempo con Claude Code vs trabajo manual
3. **Publicar v0.2.0** — estabilidad del daemon y mejor display del dashboard

---

## Comandos clave

```bash
devtrack start              # Inicia daemon + abre dashboard
devtrack stop               # Detiene daemon
devtrack                    # Resumen de hoy en terminal
devtrack week               # Últimos 14 días
devtrack files              # Archivos editados hoy
devtrack report 2026-05-23  # Reporte de un día específico
```

---

## Archivos de referencia

- `devtrack/cli.py` — toda la lógica del CLI
- `devtrack/main.py` — servidor FastAPI + daemon
- `devtrack/db.py` — schema SQLite y operaciones
- `devtrack/ollama.py` — integración con Ollama para summaries
- `pyproject.toml` — configuración de publicación PyPI
