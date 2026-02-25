# duf-monitor

A web dashboard companion for [duf](https://github.com/muesli/duf) — the popular disk usage tool. Adds what duf has always been missing: **historical tracking, threshold alerts, and a web UI.**

![duf-monitor Dashboard](docs/screenshots/dashboard.png)

## Features

- **Real disk data** — Uses psutil or duf's JSON output for accurate readings
- **Historical tracking** — SQLite stores snapshots at configurable intervals
- **Mini-charts** — 24h usage history sparklines per disk
- **Threshold alerts** — Configurable alerts when disks exceed capacity
- **WebSocket live updates** — Dashboard updates in real-time
- **Multi-host ready** — Architecture supports monitoring multiple hosts
- **Zero config** — Works out of the box with sensible defaults
- **Lightweight** — Single Python file, no heavy dependencies

## Quick Start

```bash
pip install fastapi "uvicorn[standard]" psutil websockets

git clone https://github.com/pueblokc/duf.git
cd duf
python -m uvicorn duf_monitor.app:app --host 0.0.0.0 --port 8503
```

Open `http://localhost:8503`

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `DUF_PORT` | `8503` | Server port |
| `DUF_DB_PATH` | `./duf_monitor.db` | SQLite database path |
| `DUF_POLL_INTERVAL` | `300` | Seconds between snapshots |
| `DUF_ALERT_THRESHOLD` | `90` | Disk usage % to trigger alerts |
| `DUF_WEBHOOK_URL` | _(empty)_ | Webhook URL for alert notifications |

## API

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/` | Web Dashboard |
| `GET` | `/api/current` | Current disk usage |
| `GET` | `/api/history/{mountpoint}?hours=24` | Usage history |
| `GET` | `/api/alerts` | Recent alerts |
| `POST` | `/api/alerts/{id}/acknowledge` | Acknowledge alert |
| `WS` | `/ws` | Real-time updates |

## License

MIT — same as the original duf project.
