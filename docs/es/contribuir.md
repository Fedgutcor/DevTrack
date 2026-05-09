# Cómo contribuir a DevTrack

Gracias por tu interés en contribuir. DevTrack es una herramienta local-first — la mantenemos simple y con pocas dependencias.

---

## Setup local

**Requisitos:** Python 3.11+, [uv](https://docs.astral.sh/uv/)

```bash
# Clona el repositorio
git clone https://github.com/Fedgutcor/DevTrack
cd DevTrack

# Instala dependencias (incluyendo dev)
uv sync --extra dev
```

## Correr el servidor

```bash
uv run devtrack-server
# Dashboard en http://localhost:17321
```

## Correr los tests

```bash
uv run pytest
```

## Linter

```bash
uv run ruff check .
```

---

## Cómo hacer una contribución

1. Haz fork del repositorio en GitHub
2. Crea una rama: `git checkout -b feat/mi-feature`
3. Haz tus cambios
4. Corre `ruff check .` y `pytest` — ambos deben pasar
5. Abre un Pull Request con una descripción clara

---

## Política de idiomas

| Elemento | Idioma |
|----------|--------|
| Código (funciones, variables, clases) | Inglés |
| Commits y PR titles | Inglés |
| Issues | Inglés preferido, español aceptado |
| Documentación | Inglés o español, ambos bienvenidos |
| Tests | Inglés |

**Por qué inglés en el código:** mantiene el proyecto accesible a contributors externos y evita mezclar idiomas en el mismo archivo, lo que complica el mantenimiento a largo plazo.

---

## Reportar bugs

Abre un issue en https://github.com/Fedgutcor/DevTrack/issues con:

- Tu sistema operativo y versión de Python
- Pasos para reproducir el problema
- Comportamiento esperado vs. lo que pasó
- Output del error si aplica

---

## Filosofía del proyecto

- **local-first**: sin nube, sin telemetría, los datos quedan en tu máquina
- **privacy-first**: sin cuentas, sin API keys requeridas
- **instalación simple**: `pip install devtrack-local` debe funcionar en un Python 3.11+ limpio
- **sin sobreingeniería**: resolver el problema, no abstraer para necesidades hipotéticas futuras
