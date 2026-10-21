# Sherlock Web UI

A self-hosted web interface for [Sherlock](https://github.com/sherlock-project/sherlock) — the popular OSINT tool that finds usernames across 400+ social networks.

**No more CLI.** Search usernames, stream results in real-time, export reports, and keep a searchable history — all from your browser.

![Sherlock Web - Search Complete](docs/screenshots/search-complete.png)

## Features

- **Real-time streaming** — Results appear as they're found via WebSocket, not after the full scan
- **449+ sites** — All sites from the official Sherlock database
- **Search history** — Every search is saved to SQLite with full results
- **Filter & sort** — Filter by Found/Not Found/Errors, search by site name
- **Export** — CSV, JSON, or copy all found URLs to clipboard
- **Dark OSINT theme** — Because you're not doing this in a bright IDE
- **Docker ready** — One command to deploy
- **NSFW toggle** — Include or exclude adult sites
- **Configurable timeout** — Adjust per-site timeout from the UI

## Screenshots

| Landing Page | Search Results | Found Filter |
|:---:|:---:|:---:|
| ![Landing](docs/screenshots/landing.png) | ![Results](docs/screenshots/search-complete.png) | ![Found](docs/screenshots/found-filter.png) |

## Quick Start

### Option 1: Docker (Recommended)

```bash
docker compose -f docker-compose.web.yml up -d
```

Open `http://localhost:8501`

### Option 2: Local Install

```bash
# Clone
git clone https://github.com/pueblokc/sherlock.git
cd sherlock

# Create venv & install
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate
pip install -e .
pip install fastapi "uvicorn[standard]" websockets

# Run
python -m uvicorn sherlock_web.app:app --host 0.0.0.0 --port 8501
```

Open `http://localhost:8501`

### Option 3: Python Module

```bash
pip install sherlock-project fastapi "uvicorn[standard]" websockets
python -m sherlock_web.app
```

## API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/` | Web UI |
| `WS` | `/ws/search` | WebSocket for real-time search |
| `GET` | `/api/sites` | List all searchable sites |
| `GET` | `/api/history` | Search history |
| `GET` | `/api/search/{id}` | Get search results |
| `GET` | `/api/search/{id}/export/csv` | Export results as CSV |
| `GET` | `/api/search/{id}/export/json` | Export results as JSON |

### WebSocket Protocol

Connect to `/ws/search` and send:

```json
{
  "username": "target_username",
  "timeout": 60,
  "nsfw": false,
  "sites": null
}
```

Receive streamed results:

```json
{"type": "started", "search_id": 1, "username": "target_username"}
{"type": "result", "site_name": "GitHub", "url_user": "https://github.com/target_username", "status": "CLAIMED", "response_time_ms": 234.5}
{"type": "result", "site_name": "Twitter", "url_user": "https://twitter.com/target_username", "status": "AVAILABLE", "response_time_ms": 456.7}
{"type": "done"}
```

Status values: `CLAIMED` (found), `AVAILABLE` (not found), `UNKNOWN` (error), `WAF` (blocked), `ILLEGAL` (invalid username for site)

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `SHERLOCK_PORT` | `8501` | Server port |
| `SHERLOCK_DB_PATH` | `./sherlock_web.db` | SQLite database path |

## Architecture

```
sherlock_web/
├── app.py          # FastAPI backend with WebSocket streaming
├── database.py     # SQLite for search history & results
├── __init__.py
├── requirements.txt
└── static/
    └── index.html  # Single-file dark-theme frontend
```

The web UI wraps the existing `sherlock_project` core without modifying it. The `WebSocketNotifier` extends `QueryNotify` to stream results in real-time via WebSocket instead of printing to terminal.

## Credits

- Original [Sherlock Project](https://github.com/sherlock-project/sherlock) by the Sherlock Project contributors
- Web UI by [@pueblokc](https://github.com/pueblokc)

## License

MIT — same as the original Sherlock project.

---

Developed by **[KCCS](https://kccsonline.com)** — [kccsonline.com](https://kccsonline.com)
