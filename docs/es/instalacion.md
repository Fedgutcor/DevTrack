# Guía de instalación — DevTrack

> Para la versión en inglés ver el [README principal](../../README.md).

---

## Requisitos

- Python 3.11 o superior
- pip (incluido con Python)
- Terminal (macOS/Linux) o PowerShell (Windows)
- [Ollama](https://ollama.com) — opcional, para resúmenes de IA

### Verificar tu versión de Python

```bash
python --version
# o
python3 --version
```

Si tienes una versión menor a 3.11, descarga Python desde https://www.python.org/downloads/

---

## Instalación en macOS

```bash
# 1. Instala DevTrack
pip install devtrack-local

# 2. Inicia el tracker
devtrack start
```

`devtrack start` instala el daemon como LaunchAgent (se inicia automáticamente con macOS) y abre el dashboard en `http://127.0.0.1:17321`.

### Usando uv (recomendado para desarrollo)

```bash
# Instala uv si no lo tienes
curl -LsSf https://astral.sh/uv/install.sh | sh

# Instala DevTrack con uv
uv tool install devtrack-local

devtrack start
```

---

## Instalación en Linux

```bash
pip install devtrack-local
```

En Linux no hay integración con LaunchAgent. Inicia el servidor manualmente:

```bash
devtrack-server &
```

Para iniciarlo automáticamente con el sistema, puedes crear un servicio systemd:

```ini
# ~/.config/systemd/user/devtrack.service
[Unit]
Description=DevTrack daemon

[Service]
ExecStart=devtrack-server
Restart=always

[Install]
WantedBy=default.target
```

```bash
systemctl --user enable --now devtrack
```

---

## Instalación en Windows

```powershell
pip install devtrack-local
```

El dashboard funciona igual en `http://127.0.0.1:17321`. Para iniciar el servidor:

```powershell
devtrack-server
```

Para dejarlo corriendo en segundo plano, puedes usar una tarea programada en el Programador de tareas de Windows o correrlo en una terminal separada.

---

## Primer uso

```bash
devtrack start        # Inicia daemon + abre dashboard
devtrack              # Resumen del día en terminal
devtrack week         # Historial de 14 días
devtrack help         # Todos los comandos
```

---

## Resúmenes IA con Ollama (opcional)

Ollama corre modelos de lenguaje localmente — sin internet, sin API keys.

```bash
# macOS
brew install ollama

# Linux / Windows: descarga desde https://ollama.com

# Descarga el modelo
ollama pull qwen2.5-coder:3b

# Opcional: perfil personalizado para DevTrack
ollama create qwen-dev -f Modelfile.qwen-dev
```

Una vez que Ollama esté corriendo, el bloque "Resumen del día" en el dashboard se activa automáticamente.

---

## Desinstalación

```bash
devtrack stop
pip uninstall devtrack-local
rm -rf ~/.local/share/devtrack/    # macOS / Linux
```

En Windows:
```powershell
pip uninstall devtrack-local
Remove-Item -Recurse "$env:LOCALAPPDATA\devtrack"
```

---

## Problemas comunes

### `devtrack: command not found`

El script no está en el PATH. Prueba:

```bash
python -m devtrack.cli
```

O reinstala asegurándote que `~/.local/bin` esté en tu PATH:

```bash
echo 'export PATH="$HOME/.local/bin:$PATH"' >> ~/.zshrc
source ~/.zshrc
```

### El dashboard no carga

Verifica que el daemon esté corriendo:

```bash
devtrack status
```

Si no está corriendo:

```bash
devtrack start
```

### Puerto 17321 ocupado

Otro proceso usa el puerto. Identifícalo:

```bash
lsof -i :17321
```

---

¿Encontraste un problema? Abre un issue en https://github.com/Fedgutcor/DevTrack/issues
