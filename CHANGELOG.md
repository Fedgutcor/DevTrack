# Changelog

All notable changes to DevTrack are documented here.

## [0.1.0] — 2025-05-08

### Initial release

- Local-first dev activity tracker (FastAPI server + CLI)
- Tracks file edits, lines added/deleted, Bash commands, sessions
- Dashboard at `localhost:17321` with Chart.js visualizations
- Contribution heatmap (GitHub-style)
- Hourly activity breakdown
- Streak tracking
- Project and language detection (auto-inferred from file paths)
- Optional AI summaries via Ollama (local, no cloud dependency)
- macOS LaunchAgent integration (`devtrack start` / `devtrack stop`)
- CLI gallery of Command Center agents
