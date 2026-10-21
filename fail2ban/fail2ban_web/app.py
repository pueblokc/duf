"""fail2ban Web Dashboard — FastAPI backend.

Connects to fail2ban via either:
1. fail2ban-client CLI (requires root/sudo access)
2. fail2ban socket directly
3. SSH to remote server (for remote monitoring)

Provides REST API + WebSocket for real-time ban events.
"""

import asyncio
import json
import os
import re
import subprocess
import sys
import sqlite3
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException, Query, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

app = FastAPI(title="fail2ban Web Dashboard", version="1.0.0")

static_dir = Path(__file__).parent / "static"
if static_dir.exists():
    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

# Configuration
F2B_CLIENT = os.environ.get("F2B_CLIENT", "fail2ban-client")
F2B_USE_SUDO = os.environ.get("F2B_USE_SUDO", "true").lower() == "true"
F2B_SSH_HOST = os.environ.get("F2B_SSH_HOST", "")  # If set, connect via SSH
F2B_SSH_USER = os.environ.get("F2B_SSH_USER", "root")
F2B_SSH_KEY = os.environ.get("F2B_SSH_KEY", "")
DB_PATH = os.environ.get("F2B_DB_PATH", str(Path(__file__).parent / "f2b_dashboard.db"))

# Demo mode — if fail2ban-client is not available, serve demo data
DEMO_MODE = os.environ.get("F2B_DEMO", "auto")  # "auto", "true", "false"


def init_db():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS ban_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,
            jail TEXT NOT NULL,
            ip TEXT NOT NULL,
            action TEXT NOT NULL DEFAULT 'ban',
            country TEXT,
            hostname TEXT
        );
        CREATE TABLE IF NOT EXISTS snapshots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,
            jail TEXT NOT NULL,
            banned_count INTEGER NOT NULL,
            total_failed INTEGER,
            total_banned INTEGER
        );
        CREATE INDEX IF NOT EXISTS idx_ban_log_ts ON ban_log(timestamp);
        CREATE INDEX IF NOT EXISTS idx_ban_log_jail ON ban_log(jail);
        CREATE INDEX IF NOT EXISTS idx_ban_log_ip ON ban_log(ip);
    """)
    conn.commit()
    conn.close()


def run_f2b_command(args: list[str]) -> tuple[str, int]:
    """Execute a fail2ban-client command."""
    cmd = []
    if F2B_SSH_HOST:
        cmd = ["ssh"]
        if F2B_SSH_KEY:
            cmd += ["-i", F2B_SSH_KEY]
        cmd += [f"{F2B_SSH_USER}@{F2B_SSH_HOST}"]
    if F2B_USE_SUDO and not F2B_SSH_HOST:
        cmd.append("sudo")
    cmd.append(F2B_CLIENT)
    cmd.extend(args)

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        return result.stdout.strip(), result.returncode
    except FileNotFoundError:
        return "", -1
    except subprocess.TimeoutExpired:
        return "timeout", -2


def is_f2b_available() -> bool:
    """Check if fail2ban-client is accessible."""
    output, code = run_f2b_command(["status"])
    return code == 0


def get_demo_data():
    """Generate realistic demo data for testing the dashboard without fail2ban."""
    import random
    jails = ["sshd", "nginx-http-auth", "postfix", "dovecot", "apache-auth", "recidive"]
    demo_jails = {}
    for jail in jails:
        banned_ips = []
        for _ in range(random.randint(0, 8)):
            banned_ips.append(f"{random.randint(1,223)}.{random.randint(0,255)}.{random.randint(0,255)}.{random.randint(1,254)}")
        demo_jails[jail] = {
            "currently_banned": len(banned_ips),
            "total_banned": len(banned_ips) + random.randint(5, 50),
            "total_failed": random.randint(100, 5000),
            "banned_ips": banned_ips,
            "filter": {
                "currently_failed": random.randint(0, 10),
                "total_failed": random.randint(100, 5000),
            },
        }

    # Generate ban timeline for last 24h
    timeline = []
    now = datetime.now(timezone.utc)
    for h in range(24):
        ts = now - timedelta(hours=23 - h)
        for jail in jails:
            count = random.randint(0, 15) if jail == "sshd" else random.randint(0, 5)
            if count > 0:
                timeline.append({
                    "hour": ts.strftime("%H:00"),
                    "jail": jail,
                    "count": count,
                })

    # Top banned IPs
    top_ips = []
    for _ in range(10):
        ip = f"{random.randint(1,223)}.{random.randint(0,255)}.{random.randint(0,255)}.{random.randint(1,254)}"
        countries = ["CN", "RU", "US", "BR", "IN", "KR", "DE", "FR", "VN", "ID"]
        top_ips.append({
            "ip": ip,
            "ban_count": random.randint(3, 25),
            "country": random.choice(countries),
            "last_seen": (now - timedelta(minutes=random.randint(1, 1440))).isoformat(),
            "jails": random.sample(jails, random.randint(1, 3)),
        })
    top_ips.sort(key=lambda x: x["ban_count"], reverse=True)

    return {
        "jails": demo_jails,
        "timeline": timeline,
        "top_ips": top_ips,
        "total_banned_now": sum(j["currently_banned"] for j in demo_jails.values()),
        "total_jails": len(jails),
    }


def parse_jail_status(jail_name: str) -> dict:
    """Parse fail2ban-client status <jail> output."""
    output, code = run_f2b_command(["status", jail_name])
    if code != 0:
        return {"error": f"Failed to get status for {jail_name}"}

    result = {
        "name": jail_name,
        "currently_failed": 0,
        "total_failed": 0,
        "currently_banned": 0,
        "total_banned": 0,
        "banned_ips": [],
    }

    for line in output.split("\n"):
        line = line.strip()
        if "Currently failed:" in line:
            result["currently_failed"] = int(re.search(r"\d+", line.split(":")[-1]).group())
        elif "Total failed:" in line:
            result["total_failed"] = int(re.search(r"\d+", line.split(":")[-1]).group())
        elif "Currently banned:" in line:
            result["currently_banned"] = int(re.search(r"\d+", line.split(":")[-1]).group())
        elif "Total banned:" in line:
            result["total_banned"] = int(re.search(r"\d+", line.split(":")[-1]).group())
        elif "Banned IP list:" in line:
            ip_str = line.split(":")[-1].strip()
            if ip_str:
                result["banned_ips"] = [ip.strip() for ip in ip_str.split() if ip.strip()]

    return result


def get_all_jails() -> list[str]:
    """Get list of all jail names."""
    output, code = run_f2b_command(["status"])
    if code != 0:
        return []

    for line in output.split("\n"):
        if "Jail list:" in line:
            jails_str = line.split(":")[-1].strip()
            return [j.strip() for j in jails_str.split(",") if j.strip()]
    return []


# Determine mode at startup
_demo_mode = False


@app.on_event("startup")
async def startup():
    global _demo_mode
    init_db()
    if DEMO_MODE == "true":
        _demo_mode = True
    elif DEMO_MODE == "false":
        _demo_mode = False
    else:  # auto
        _demo_mode = not is_f2b_available()
    if _demo_mode:
        print("Running in DEMO mode (fail2ban-client not available)")
    else:
        print("Connected to fail2ban")


@app.get("/", response_class=HTMLResponse)
async def index():
    html_file = Path(__file__).parent / "static" / "index.html"
    return HTMLResponse(content=html_file.read_text(encoding="utf-8"))


@app.get("/api/status")
async def get_status():
    """Get overall fail2ban status with all jails."""
    if _demo_mode:
        return get_demo_data()

    jails = get_all_jails()
    jail_data = {}
    total_banned = 0

    for jail in jails:
        status = parse_jail_status(jail)
        jail_data[jail] = status
        total_banned += status.get("currently_banned", 0)

    return {
        "jails": jail_data,
        "total_banned_now": total_banned,
        "total_jails": len(jails),
        "demo": False,
    }


@app.get("/api/jail/{jail_name}")
async def get_jail(jail_name: str):
    """Get detailed status for a specific jail."""
    if _demo_mode:
        data = get_demo_data()
        if jail_name in data["jails"]:
            return data["jails"][jail_name]
        raise HTTPException(404, f"Jail '{jail_name}' not found")

    status = parse_jail_status(jail_name)
    if "error" in status:
        raise HTTPException(500, status["error"])
    return status


@app.post("/api/jail/{jail_name}/unban/{ip}")
async def unban_ip(jail_name: str, ip: str):
    """Unban an IP from a specific jail."""
    if _demo_mode:
        return {"status": "ok", "message": f"[DEMO] Would unban {ip} from {jail_name}"}

    output, code = run_f2b_command(["set", jail_name, "unbanip", ip])
    if code != 0:
        raise HTTPException(500, f"Failed to unban {ip}: {output}")

    # Log the unban
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        "INSERT INTO ban_log (timestamp, jail, ip, action) VALUES (?, ?, ?, 'unban')",
        (datetime.now(timezone.utc).isoformat(), jail_name, ip),
    )
    conn.commit()
    conn.close()

    return {"status": "ok", "message": f"Unbanned {ip} from {jail_name}"}


@app.post("/api/jail/{jail_name}/ban/{ip}")
async def ban_ip(jail_name: str, ip: str):
    """Manually ban an IP in a specific jail."""
    if _demo_mode:
        return {"status": "ok", "message": f"[DEMO] Would ban {ip} in {jail_name}"}

    output, code = run_f2b_command(["set", jail_name, "banip", ip])
    if code != 0:
        raise HTTPException(500, f"Failed to ban {ip}: {output}")

    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        "INSERT INTO ban_log (timestamp, jail, ip, action) VALUES (?, ?, ?, 'ban')",
        (datetime.now(timezone.utc).isoformat(), jail_name, ip),
    )
    conn.commit()
    conn.close()

    return {"status": "ok", "message": f"Banned {ip} in {jail_name}"}


@app.get("/api/log")
async def get_ban_log(limit: int = Query(100, ge=1, le=1000)):
    """Get recent ban/unban actions."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT * FROM ban_log ORDER BY id DESC LIMIT ?", (limit,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


@app.get("/api/mode")
async def get_mode():
    """Check if running in demo or live mode."""
    return {"demo": _demo_mode}


if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("F2B_PORT", 8502))
    uvicorn.run(app, host="0.0.0.0", port=port)
