# sampler — Web Companion

A browser-based dashboard companion for [sampler](https://github.com/sqshq/sampler),
the YAML-configured terminal visualization tool.

Serves the same data your `sampler` config defines — gauge, sparkline, bar chart,
text, and ASCII widgets — as a live web dashboard with WebSocket real-time updates.
No terminal required.

---

## Features

- **Reads your existing `sampler.yml`** — no config changes needed
- **Demo mode** — starts instantly with a system monitoring dashboard (CPU, memory,
  disk, per-core CPU, network KB/s, top processes) if no config is provided
- **WebSocket real-time updates** — 2 Hz broadcast rate, sub-second latency
- **Widget types**: sparkline, gauge (arc), bar chart, run chart, textbox, ASCII box
- **Terminal aesthetic** — dark green phosphor theme, scan-line overlay, canvas charts
- **REST API** — `/api/widgets` and `/api/status` endpoints
- **Multi-client** — any number of browsers can watch the same dashboard simultaneously

---

## Quickstart

### Requirements

- Python 3.10+
- `fastapi`, `uvicorn`, `psutil`, `pyyaml`, `websockets`

```bash
pip install fastapi uvicorn psutil pyyaml websockets
```

### Demo mode (no config needed)

```bash
cd /path/to/sampler
uvicorn sampler_web.app:app --host 0.0.0.0 --port 8506
```

Open http://localhost:8506 — you'll see a live system metrics dashboard.

### Load your sampler config

```bash
SAMPLER_CONFIG=example.yml uvicorn sampler_web.app:app --host 0.0.0.0 --port 8506
```

Or pass the config path as the first argument:

```bash
python -m sampler_web.app myconfig.yml
```

---

## API

| Endpoint          | Method | Description                              |
|-------------------|--------|------------------------------------------|
| `/`               | GET    | Web dashboard (HTML)                     |
| `/api/widgets`    | GET    | Current widget state (JSON)              |
| `/api/status`     | GET    | Server status, demo mode, widget count   |
| `/ws`             | WS     | Real-time widget data stream             |

### Widget JSON shape

```json
{
  "id": "w0",
  "type": "sparkline",
  "title": "CPU Usage %",
  "position": [[0, 0], [30, 8]],
  "items": [
    {
      "label": "cpu",
      "history": [12.4, 13.1, 14.0, ...],
      "current": 14.0,
      "color": "#00ff88"
    }
  ],
  "min": 0,
  "max": 100,
  "thresholds": [
    { "value": 70, "color": "#ffaf00" },
    { "value": 90, "color": "#ff4444" }
  ]
}
```

---

## Widget Support Matrix

| sampler type | Web type     | Notes                                    |
|-------------|--------------|------------------------------------------|
| `sparklines`  | `sparkline`  | Canvas line chart with gradient fill     |
| `runcharts`   | `runchart`   | Multi-series canvas line chart + legend  |
| `gauges`      | `gauge`      | Arc gauge with needle and colour thresholds |
| `barcharts`   | `barchart`   | Horizontal bar chart, auto-scaled        |
| `textboxes`   | `textbox`    | Pre-formatted scrollable text output     |
| `asciiboxes`  | `asciibox`   | Large monospace ASCII art display        |

---

## Demo Mode Widgets

| Widget             | Type      | Data source                       |
|--------------------|-----------|-----------------------------------|
| CPU Usage %        | Sparkline | `psutil.cpu_percent()`            |
| Memory Usage %     | Sparkline | `psutil.virtual_memory().percent` |
| CPU Gauge          | Gauge     | `psutil.cpu_percent()`            |
| Disk Usage %       | Gauge     | `psutil.disk_usage("/").percent`  |
| Per-Core CPU %     | Bar chart | `psutil.cpu_percent(percpu=True)` |
| Network KB/s       | Bar chart | `psutil.net_io_counters()`        |
| Top Processes      | Textbox   | `psutil.process_iter()`           |
| System Info        | Textbox   | Platform + psutil metadata        |

---

## Configuration Notes

### Position

The `position` key from sampler YAML is preserved in the API response but the web
dashboard uses a CSS auto-grid layout rather than character-cell positioning.
Future versions may support pixel-accurate layout replication.

### Colour codes

Sampler uses 256-colour ANSI codes (e.g. `color: 178`). The web companion maps the
most common codes to CSS hex. Unknown codes fall back to `#00ff88`.

### Command execution

Shell commands from `sample:` keys are run on the server via `asyncio.create_subprocess_shell`.
Commands that produce non-numeric output are displayed as text in textbox/asciibox widgets.

---

## Architecture

```
Browser ──WS──► FastAPI /ws  ◄── broadcast loop (0.5s)
                     │
              WidgetStore
                     │
              Sampler (background tasks, one per widget)
                     │
          ┌──────────┴──────────┐
     shell commands         demo_fn callbacks
     (asyncio subprocess)   (psutil, direct)
```

---

## Files

```
sampler/
├── sampler_web/
│   ├── __init__.py          version string
│   ├── app.py               FastAPI application
│   └── static/
│       └── index.html       Single-page dashboard
├── COMPANION_README.md      This file
└── docs/
    └── screenshots/
        └── dashboard.png    Dashboard screenshot
```

---

## License

MIT — same as the original sampler project.
Web companion additions by [pueblokc](https://github.com/pueblokc).

---

Developed by **[KCCS](https://kccsonline.com)** — [kccsonline.com](https://kccsonline.com)
