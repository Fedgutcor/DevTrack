# Changelog

All notable changes to DevTrack are documented here.

## [Unreleased]

### Fixed
- `devtrack week` showed `?` for all dates — field name was `date` but API returns `local_date`

### Added
- CSV export via `--csv` / `-c` flag on all `devtrack export` scopes (day, week, all)
- `daily_aggregates` table now populated automatically on every incoming event
- `POST /aggregate` endpoint for historical backfill of all recorded dates
- `GET /aggregate` endpoint to inspect current aggregate state
- `devtrack aggregate` CLI command to trigger backfill manually
- `devtrack report` and `devtrack range` commands documented in README

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
