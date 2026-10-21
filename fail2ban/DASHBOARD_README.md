# fail2ban Web Dashboard

A self-hosted web dashboard for [fail2ban](https://github.com/fail2ban/fail2ban) — the intrusion prevention tool used on virtually every Linux server.

**No more SSH just to check your bans.** See all jails, banned IPs, attack timelines, and top offenders — plus one-click unban and manual ban from your browser.

![fail2ban Dashboard](docs/screenshots/dashboard.png)

## Features

- **All jails at a glance** — See banned count, failed attempts, and totals per jail
- **Expandable jail details** — Click any jail to see all currently banned IPs
- **One-click unban** — Remove bans without touching the CLI
- **Manual ban** — Ban any IP in any jail from the UI
- **Top offenders** — See the most-banned IPs with country codes and affected jails
- **24h ban timeline** — Visual chart of ban activity over the last 24 hours
- **Auto-refresh** — Dashboard updates every 30 seconds
- **Demo mode** — Works without fail2ban installed for testing/development
- **Remote monitoring** — Monitor fail2ban on remote servers via SSH
- **REST API** — Full programmatic access to all data

## Screenshots

| Dashboard | Expanded Jail |
|:---:|:---:|
| ![Dashboard](docs/screenshots/dashboard.png) | ![Expanded](docs/screenshots/jail-expanded.png) |

## Quick Start

### On your Linux server (with fail2ban installed):

```bash
pip install fastapi "uvicorn[standard]"

# Clone and run
git clone https://github.com/pueblokc/fail2ban.git
cd fail2ban
python -m uvicorn fail2ban_web.app:app --host 0.0.0.0 --port 8502
```

Open `http://your-server:8502`

### Demo mode (no fail2ban needed):

```bash
F2B_DEMO=true python -m uvicorn fail2ban_web.app:app --host 0.0.0.0 --port 8502
```

### Remote monitoring (via SSH):

```bash
F2B_SSH_HOST=192.168.1.100 F2B_SSH_USER=root F2B_SSH_KEY=~/.ssh/id_rsa \
  python -m uvicorn fail2ban_web.app:app --host 0.0.0.0 --port 8502
```

## API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/` | Web Dashboard |
| `GET` | `/api/status` | All jails status + timeline + top offenders |
| `GET` | `/api/jail/{name}` | Specific jail details |
| `POST` | `/api/jail/{name}/ban/{ip}` | Ban an IP |
| `POST` | `/api/jail/{name}/unban/{ip}` | Unban an IP |
| `GET` | `/api/log` | Ban/unban action log |
| `GET` | `/api/mode` | Check if running in demo/live mode |

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `F2B_PORT` | `8502` | Server port |
| `F2B_DEMO` | `auto` | `auto` / `true` / `false` — auto-detects fail2ban |
| `F2B_CLIENT` | `fail2ban-client` | Path to fail2ban-client binary |
| `F2B_USE_SUDO` | `true` | Use sudo for fail2ban-client commands |
| `F2B_SSH_HOST` | _(empty)_ | SSH host for remote monitoring |
| `F2B_SSH_USER` | `root` | SSH username |
| `F2B_SSH_KEY` | _(empty)_ | SSH private key path |
| `F2B_DB_PATH` | `./f2b_dashboard.db` | SQLite database for action logs |

## Architecture

```
fail2ban_web/
├── app.py          # FastAPI backend (CLI wrapper + demo mode)
├── __init__.py
└── static/
    └── index.html  # Single-file dark security dashboard
```

The dashboard wraps `fail2ban-client` commands and parses their output. It does NOT modify fail2ban configuration — only reads status and issues ban/unban commands through the official client.

## Requirements

- Python 3.9+
- `fastapi` and `uvicorn`
- fail2ban installed on the target server (or use demo mode)
- Root/sudo access for fail2ban-client (or SSH access to remote server)

## Credits

- Original [fail2ban](https://github.com/fail2ban/fail2ban) by the fail2ban team
- Web Dashboard by [@pueblokc](https://github.com/pueblokc)

## License

GPL-2.0 — same as the original fail2ban project.

---

Developed by **[KCCS](https://kccsonline.com)** — [kccsonline.com](https://kccsonline.com)
