# GoTTY Manager

A Python-based management layer for [GoTTY](https://github.com/yudai/gotty) — the terminal-sharing tool with 22K stars that lets you share any terminal command over a web browser.

GoTTY's original Go server is read-only/abandoned. **GoTTY Manager** adds a full session-management API, persistent history, token-based auth, and an interactive xterm.js terminal — all in ~300 lines of FastAPI.

## Features

| Feature | Details |
|---|---|
| **Session management** | Create, list, and kill terminal sessions via REST API |
| **Token auth** | Each session gets a unique 256-bit token; WebSocket connections require it |
| **Session history** | All sessions logged to SQLite with start/end times and exit codes |
| **xterm.js terminal** | Full-featured browser terminal loaded from CDN (no bundler needed) |
| **Admin dashboard** | Live-updating session table, stats, kill buttons, one-click new session |
| **WebSocket proxy** | Browser ↔ subprocess stdin/stdout via binary WebSocket frames |
| **Rate limiting** | Max 10 session creations per minute per IP (via SlowAPI) |
| **Dark theme** | GitHub-dark colour palette throughout |

## Quick Start

```bash
# Install dependencies (uses sherlock's venv or any Python 3.11+ env)
pip install fastapi uvicorn[standard] aiosqlite slowapi

# Run the manager
python -m uvicorn gotty_manager.app:app --host 0.0.0.0 --port 8507

# Or via the module directly
python gotty_manager/app.py
```

Open **http://localhost:8507** to see the admin dashboard.

## API Reference

### Sessions

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/api/sessions` | List all active sessions |
| `POST` | `/api/sessions` | Create a new terminal session |
| `DELETE` | `/api/sessions/{id}` | Terminate a session |
| `GET` | `/api/history` | Session history from SQLite |
| `GET` | `/api/health` | Health check + active session count |

### Create Session Body

```json
{
  "command": ["powershell.exe", "-NoLogo"],
  "label": "My Terminal"
}
```

Both fields are optional. `command` defaults to the system shell (`powershell.exe` on Windows, `$SHELL` on Linux/macOS).

### WebSocket

```
ws://localhost:8507/ws/{session_id}?token={token}
```

Binary frames: raw bytes forwarded to/from the subprocess stdin/stdout.
Text frames: JSON control messages (`{"type": "exit", "code": 0}`).

## Pages

| URL | Description |
|---|---|
| `/` | Admin dashboard |
| `/terminal/{session_id}?token={token}` | xterm.js terminal for a session |

## Architecture

```
Browser (xterm.js)
     ↕ WebSocket (binary)
FastAPI app (port 8507)
     ↕ asyncio subprocess pipes
System Shell (powershell / bash)
     ↕
SQLite (session_history table)
```

## Rate Limits

- Session creation: **10 per minute per IP**
- All other endpoints: **200 per minute per IP**

## Security Notes

- Tokens are 256-bit URL-safe random strings (`secrets.token_urlsafe(32)`)
- WebSocket connections are rejected without a valid token
- For production: add TLS termination (nginx/caddy) and restrict the admin dashboard behind authentication

## Dependencies

- `fastapi` — web framework
- `uvicorn[standard]` — ASGI server with WebSocket support
- `aiosqlite` — async SQLite for session history
- `slowapi` — rate limiting middleware
- `xterm.js 5.3.0` — browser terminal (CDN, no install)
- `xterm-addon-fit` — responsive terminal sizing
- `xterm-addon-web-links` — clickable URLs in terminal

---

Developed by **[KCCS](https://kccsonline.com)** — [kccsonline.com](https://kccsonline.com)
