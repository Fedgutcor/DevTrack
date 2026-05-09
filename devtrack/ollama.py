"""devtrack.ollama — Optional Ollama integration for productivity summaries."""
import httpx
import logging

logger = logging.getLogger("devtrack.ollama")

OLLAMA_URL = "http://localhost:11434/api/generate"
MODEL = "qwen2.5-coder:3b"


async def generate_summary(stats: dict) -> str | None:
    """Call local Ollama to generate a natural-language productivity summary.

    Returns None silently if Ollama is not available.
    """
    lines_added = stats.get("lines_added", 0)
    lines_deleted = stats.get("lines_deleted", 0)
    files_touched = stats.get("files_touched", 0)
    sessions = stats.get("sessions", 0)
    projects = stats.get("projects", [])
    languages = stats.get("languages", [])

    project_list = ", ".join(p["project"] for p in projects if p.get("project")) or "ninguno"
    lang_list = ", ".join(lang["language"] for lang in languages if lang.get("language")) or "ninguno"

    prompt = (
        f"Eres un asistente de productividad para desarrolladores. "
        f"Resume en 2-3 oraciones directas y técnicas la sesión de hoy:\n"
        f"- Líneas escritas: {lines_added}\n"
        f"- Líneas eliminadas: {lines_deleted}\n"
        f"- Archivos editados: {files_touched}\n"
        f"- Sesiones: {sessions}\n"
        f"- Proyectos: {project_list}\n"
        f"- Lenguajes: {lang_list}\n"
        f"Sin preámbulos. Directo al punto. En español."
    )

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(
                OLLAMA_URL,
                json={"model": MODEL, "prompt": prompt, "stream": False},
            )
            response.raise_for_status()
            return response.json().get("response", "").strip()
    except Exception as e:
        logger.debug(f"Ollama not available: {e}")
        return None
