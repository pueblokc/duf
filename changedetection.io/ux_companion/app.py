"""
UX Companion Dashboard for changedetection.io
Modern monitoring dashboard overlay with folder organization,
bulk operations, tag management, and diff viewer.
"""

import json
import random
import sqlite3
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException, Query
from fastapi.responses import HTMLResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

# ---------------------------------------------------------------------------
# App setup
# ---------------------------------------------------------------------------

app = FastAPI(title="changedetection.io UX Companion", version="1.0.0")

BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"
DB_PATH = BASE_DIR / "companion.db"

app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------


class WatchCreate(BaseModel):
    url: str
    title: Optional[str] = None
    check_interval: int = 3600  # seconds
    folder_id: Optional[str] = None
    tags: list[str] = []
    notes: Optional[str] = None


class WatchUpdate(BaseModel):
    title: Optional[str] = None
    url: Optional[str] = None
    check_interval: Optional[int] = None
    folder_id: Optional[str] = None
    tags: Optional[list[str]] = None
    notes: Optional[str] = None
    status: Optional[str] = None


class FolderCreate(BaseModel):
    name: str
    parent_id: Optional[str] = None
    color: Optional[str] = "#3b82f6"
    icon: Optional[str] = None


class BulkAction(BaseModel):
    watch_ids: list[str]
    action: str  # move_folder, add_tag, remove_tag, pause, resume, delete
    value: Optional[str] = None


# ---------------------------------------------------------------------------
# Database helpers
# ---------------------------------------------------------------------------


def get_db():
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db():
    conn = get_db()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS folders (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            parent_id TEXT,
            color TEXT DEFAULT '#3b82f6',
            icon TEXT,
            sort_order INTEGER DEFAULT 0,
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS watches (
            id TEXT PRIMARY KEY,
            url TEXT NOT NULL,
            title TEXT,
            check_interval INTEGER DEFAULT 3600,
            folder_id TEXT,
            tags TEXT DEFAULT '[]',
            notes TEXT DEFAULT '',
            status TEXT DEFAULT 'ok',
            last_checked TEXT,
            last_changed TEXT,
            change_count INTEGER DEFAULT 0,
            created_at TEXT NOT NULL,
            FOREIGN KEY (folder_id) REFERENCES folders(id) ON DELETE SET NULL
        );

        CREATE TABLE IF NOT EXISTS changes (
            id TEXT PRIMARY KEY,
            watch_id TEXT NOT NULL,
            timestamp TEXT NOT NULL,
            diff_text TEXT,
            snapshot_text TEXT,
            FOREIGN KEY (watch_id) REFERENCES watches(id) ON DELETE CASCADE
        );

        CREATE INDEX IF NOT EXISTS idx_watches_folder ON watches(folder_id);
        CREATE INDEX IF NOT EXISTS idx_changes_watch ON changes(watch_id);
    """)
    conn.commit()
    conn.close()


# ---------------------------------------------------------------------------
# Demo data generator
# ---------------------------------------------------------------------------

DEMO_FOLDERS = [
    {"name": "Price Tracking", "color": "#f59e0b", "icon": "dollar-sign"},
    {"name": "GitHub Releases", "color": "#8b5cf6", "icon": "github"},
    {"name": "News", "color": "#3b82f6", "icon": "newspaper"},
    {"name": "Government", "color": "#10b981", "icon": "landmark"},
    {"name": "Competitors", "color": "#ef4444", "icon": "eye"},
]

DEMO_WATCHES = [
    # Price Tracking
    {
        "url": "https://www.amazon.com/dp/B0DJDFHZ8S",
        "title": "AMD Ryzen 9 9950X — Amazon Price",
        "folder": "Price Tracking",
        "tags": ["cpu", "hardware", "amazon"],
        "check_interval": 1800,
    },
    {
        "url": "https://www.bestbuy.com/site/nvidia-geforce-rtx-5080/6601272.p",
        "title": "RTX 5080 — Best Buy Stock",
        "folder": "Price Tracking",
        "tags": ["gpu", "hardware", "bestbuy"],
        "check_interval": 900,
    },
    {
        "url": "https://www.newegg.com/p/pl?d=rx+9070+xt",
        "title": "RX 9070 XT Search — Newegg",
        "folder": "Price Tracking",
        "tags": ["gpu", "hardware", "newegg"],
        "check_interval": 900,
    },
    {
        "url": "https://camelcamelcamel.com/product/B0BSHF7WHW",
        "title": "Synology DS923+ Price History",
        "folder": "Price Tracking",
        "tags": ["nas", "storage", "price-alert"],
        "check_interval": 3600,
    },
    {
        "url": "https://www.amazon.com/dp/B0C8P5Y2NT",
        "title": "WD Red Plus 22TB NAS Drive",
        "folder": "Price Tracking",
        "tags": ["storage", "hardware", "amazon"],
        "check_interval": 3600,
    },
    # GitHub Releases
    {
        "url": "https://github.com/yt-dlp/yt-dlp/releases",
        "title": "yt-dlp Releases",
        "folder": "GitHub Releases",
        "tags": ["tool", "media", "python"],
        "check_interval": 7200,
    },
    {
        "url": "https://github.com/home-assistant/core/releases",
        "title": "Home Assistant Core Releases",
        "folder": "GitHub Releases",
        "tags": ["homelab", "automation", "iot"],
        "check_interval": 7200,
    },
    {
        "url": "https://github.com/tailscale/tailscale/releases",
        "title": "Tailscale Releases",
        "folder": "GitHub Releases",
        "tags": ["vpn", "networking", "go"],
        "check_interval": 14400,
    },
    {
        "url": "https://github.com/grafana/grafana/releases",
        "title": "Grafana Releases",
        "folder": "GitHub Releases",
        "tags": ["monitoring", "dashboard", "go"],
        "check_interval": 14400,
    },
    {
        "url": "https://github.com/dgtlmoon/changedetection.io/releases",
        "title": "changedetection.io Releases",
        "folder": "GitHub Releases",
        "tags": ["monitoring", "self-hosted", "python"],
        "check_interval": 14400,
    },
    # News
    {
        "url": "https://www.bbc.com/news",
        "title": "BBC News — Top Stories",
        "folder": "News",
        "tags": ["world", "breaking"],
        "check_interval": 600,
    },
    {
        "url": "https://www.reuters.com/technology/",
        "title": "Reuters Technology",
        "folder": "News",
        "tags": ["tech", "business"],
        "check_interval": 900,
    },
    {
        "url": "https://techcrunch.com/",
        "title": "TechCrunch Homepage",
        "folder": "News",
        "tags": ["tech", "startups"],
        "check_interval": 900,
    },
    {
        "url": "https://news.ycombinator.com/",
        "title": "Hacker News Front Page",
        "folder": "News",
        "tags": ["tech", "dev", "community"],
        "check_interval": 600,
    },
    {
        "url": "https://arstechnica.com/",
        "title": "Ars Technica Latest",
        "folder": "News",
        "tags": ["tech", "science", "long-form"],
        "check_interval": 1800,
    },
    # Government
    {
        "url": "https://forecast.weather.gov/MapClick.php?lat=38.6270&lon=-90.1994",
        "title": "NWS Forecast — St. Louis",
        "folder": "Government",
        "tags": ["weather", "stl", "alert"],
        "check_interval": 1800,
    },
    {
        "url": "https://tools.usps.com/go/TrackConfirmAction?tLabels=9400111899223456789012",
        "title": "USPS Package Tracking",
        "folder": "Government",
        "tags": ["shipping", "tracking"],
        "check_interval": 3600,
    },
    {
        "url": "https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&company=openai&type=&dateb=&owner=include&count=10&search_text=&action=getcompany",
        "title": "SEC EDGAR — OpenAI Filings",
        "folder": "Government",
        "tags": ["sec", "finance", "ai"],
        "check_interval": 86400,
    },
    {
        "url": "https://www.fcc.gov/news-events/blog",
        "title": "FCC Blog — Regulatory Updates",
        "folder": "Government",
        "tags": ["regulation", "telecom"],
        "check_interval": 43200,
    },
    {
        "url": "https://sam.gov/search/?keywords=cybersecurity&dateRange=%7B%22modifiedDateRange%22%3A%7B%22endDate%22%3A%22%22%7D%7D",
        "title": "SAM.gov — Cybersecurity Contracts",
        "folder": "Government",
        "tags": ["contracts", "gov", "security"],
        "check_interval": 86400,
    },
    # Competitors
    {
        "url": "https://www.acmetechsolutions.com/services",
        "title": "Acme Tech Solutions — Services Page",
        "folder": "Competitors",
        "tags": ["competitor", "msp", "pricing"],
        "check_interval": 86400,
    },
    {
        "url": "https://www.primebitconsulting.com/pricing",
        "title": "PrimeBit Consulting — Pricing",
        "folder": "Competitors",
        "tags": ["competitor", "msp", "pricing"],
        "check_interval": 86400,
    },
    {
        "url": "https://www.nexgenitsupport.com/about",
        "title": "NexGen IT Support — About Us",
        "folder": "Competitors",
        "tags": ["competitor", "msp"],
        "check_interval": 86400,
    },
    {
        "url": "https://www.cloudpinnacle.io/blog",
        "title": "CloudPinnacle — Blog Updates",
        "folder": "Competitors",
        "tags": ["competitor", "cloud", "blog"],
        "check_interval": 43200,
    },
    {
        "url": "https://www.byteshieldcyber.com/",
        "title": "ByteShield Cyber — Homepage",
        "folder": "Competitors",
        "tags": ["competitor", "security"],
        "check_interval": 86400,
    },
]

SAMPLE_DIFFS = [
    {
        "removed": "Price: $549.99",
        "added": "Price: $479.99  SALE",
        "context": "Product pricing section updated",
    },
    {
        "removed": "Version 2024.1.3",
        "added": "Version 2024.2.0",
        "context": "Release version bumped with changelog",
    },
    {
        "removed": "Status: In Transit",
        "added": "Status: Out for Delivery",
        "context": "Package tracking status updated",
    },
    {
        "removed": "Cloudy, High 42\u00b0F",
        "added": "Partly Sunny, High 51\u00b0F",
        "context": "Weather forecast updated",
    },
    {
        "removed": "No recent filings found.",
        "added": "New filing: Form S-1 Registration Statement",
        "context": "SEC filing detected",
    },
    {
        "removed": "Starting at $99/mo",
        "added": "Starting at $129/mo",
        "context": "Competitor raised pricing",
    },
    {
        "removed": "Team: 15 Engineers",
        "added": "Team: 22 Engineers",
        "context": "Competitor headcount grew",
    },
    {
        "removed": "v3.14.1 (Latest)",
        "added": "v3.15.0 (Latest) - Major Update",
        "context": "New major release detected",
    },
    {
        "removed": "In Stock (12 available)",
        "added": "Only 2 left in stock - order soon",
        "context": "Low stock alert",
    },
    {
        "removed": "Expected delivery: March 3",
        "added": "Expected delivery: February 28",
        "context": "Delivery estimate updated",
    },
]


def generate_demo_data():
    """Generate realistic demo data if DB is empty."""
    conn = get_db()
    count = conn.execute("SELECT COUNT(*) FROM watches").fetchone()[0]
    if count > 0:
        conn.close()
        return

    now = datetime.now(timezone.utc)

    # Create folders
    folder_map = {}
    for i, f in enumerate(DEMO_FOLDERS):
        fid = str(uuid.uuid4())
        folder_map[f["name"]] = fid
        conn.execute(
            "INSERT INTO folders (id, name, color, icon, sort_order, created_at) VALUES (?,?,?,?,?,?)",
            (fid, f["name"], f["color"], f.get("icon"), i, now.isoformat()),
        )

    # Create watches
    statuses = ["ok"] * 14 + ["changed"] * 6 + ["error"] * 3 + ["paused"] * 2
    random.shuffle(statuses)

    for i, w in enumerate(DEMO_WATCHES):
        wid = str(uuid.uuid4())
        status = statuses[i % len(statuses)]

        last_checked = now - timedelta(minutes=random.randint(1, 55))
        last_changed = now - timedelta(
            hours=random.randint(0, 23), minutes=random.randint(0, 59)
        )
        change_count = random.randint(1, 50)

        conn.execute(
            """INSERT INTO watches
               (id, url, title, check_interval, folder_id, tags, notes, status,
                last_checked, last_changed, change_count, created_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                wid,
                w["url"],
                w["title"],
                w["check_interval"],
                folder_map.get(w["folder"]),
                json.dumps(w["tags"]),
                "",
                status,
                last_checked.isoformat(),
                last_changed.isoformat(),
                change_count,
                (now - timedelta(days=random.randint(7, 90))).isoformat(),
            ),
        )

        # Generate change history (5-12 entries per watch)
        num_changes = random.randint(5, 12)
        for c in range(num_changes):
            cid = str(uuid.uuid4())
            ts = now - timedelta(
                days=random.randint(0, 30),
                hours=random.randint(0, 23),
                minutes=random.randint(0, 59),
            )
            diff = random.choice(SAMPLE_DIFFS)
            diff_text = (
                f"--- previous\n+++ current\n"
                f"@@ Change detected @@\n"
                f"  {diff['context']}\n"
                f"- {diff['removed']}\n"
                f"+ {diff['added']}\n"
            )
            conn.execute(
                "INSERT INTO changes (id, watch_id, timestamp, diff_text) VALUES (?,?,?,?)",
                (cid, wid, ts.isoformat(), diff_text),
            )

    conn.commit()
    conn.close()


# ---------------------------------------------------------------------------
# Startup
# ---------------------------------------------------------------------------


@app.on_event("startup")
def startup():
    init_db()
    generate_demo_data()


# ---------------------------------------------------------------------------
# WebSocket for real-time notifications
# ---------------------------------------------------------------------------

connected_clients: list[WebSocket] = []


@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    await ws.accept()
    connected_clients.append(ws)
    try:
        while True:
            await ws.receive_text()
    except WebSocketDisconnect:
        connected_clients.remove(ws)


async def broadcast(message: dict):
    dead = []
    for ws in connected_clients:
        try:
            await ws.send_json(message)
        except Exception:
            dead.append(ws)
    for ws in dead:
        connected_clients.remove(ws)


# ---------------------------------------------------------------------------
# HTML UI
# ---------------------------------------------------------------------------


@app.get("/", response_class=HTMLResponse)
def serve_ui():
    return FileResponse(str(STATIC_DIR / "index.html"))


# ---------------------------------------------------------------------------
# API — Watches
# ---------------------------------------------------------------------------


@app.get("/api/watches")
def list_watches(
    folder_id: Optional[str] = None,
    tag: Optional[str] = None,
    status: Optional[str] = None,
    search: Optional[str] = None,
):
    conn = get_db()
    query = "SELECT * FROM watches WHERE 1=1"
    params: list = []

    if folder_id:
        query += " AND folder_id = ?"
        params.append(folder_id)
    if status:
        query += " AND status = ?"
        params.append(status)
    if search:
        query += " AND (title LIKE ? OR url LIKE ?)"
        params.extend([f"%{search}%", f"%{search}%"])

    query += " ORDER BY last_changed DESC"
    rows = conn.execute(query, params).fetchall()

    results = []
    for r in rows:
        w = dict(r)
        w["tags"] = json.loads(w["tags"]) if w["tags"] else []
        if tag and tag not in w["tags"]:
            continue
        results.append(w)

    conn.close()
    return results


@app.post("/api/watches")
async def create_watch(watch: WatchCreate):
    conn = get_db()
    wid = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        """INSERT INTO watches
           (id, url, title, check_interval, folder_id, tags, notes, status,
            last_checked, last_changed, change_count, created_at)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
        (
            wid,
            watch.url,
            watch.title or watch.url[:80],
            watch.check_interval,
            watch.folder_id,
            json.dumps(watch.tags),
            watch.notes or "",
            "ok",
            now,
            now,
            0,
            now,
        ),
    )
    conn.commit()
    row = dict(conn.execute("SELECT * FROM watches WHERE id=?", (wid,)).fetchone())
    row["tags"] = json.loads(row["tags"]) if row["tags"] else []
    conn.close()
    await broadcast({"type": "watch_created", "watch": row})
    return row


@app.put("/api/watches/{watch_id}")
async def update_watch(watch_id: str, data: WatchUpdate):
    conn = get_db()
    existing = conn.execute("SELECT * FROM watches WHERE id=?", (watch_id,)).fetchone()
    if not existing:
        conn.close()
        raise HTTPException(404, "Watch not found")

    updates = {}
    if data.title is not None:
        updates["title"] = data.title
    if data.url is not None:
        updates["url"] = data.url
    if data.check_interval is not None:
        updates["check_interval"] = data.check_interval
    if data.folder_id is not None:
        updates["folder_id"] = data.folder_id if data.folder_id != "" else None
    if data.tags is not None:
        updates["tags"] = json.dumps(data.tags)
    if data.notes is not None:
        updates["notes"] = data.notes
    if data.status is not None:
        updates["status"] = data.status

    if updates:
        set_clause = ", ".join(f"{k}=?" for k in updates)
        conn.execute(
            f"UPDATE watches SET {set_clause} WHERE id=?",
            [*updates.values(), watch_id],
        )
        conn.commit()

    row = dict(conn.execute("SELECT * FROM watches WHERE id=?", (watch_id,)).fetchone())
    row["tags"] = json.loads(row["tags"]) if row["tags"] else []
    conn.close()
    await broadcast({"type": "watch_updated", "watch": row})
    return row


@app.delete("/api/watches/{watch_id}")
async def delete_watch(watch_id: str):
    conn = get_db()
    existing = conn.execute("SELECT * FROM watches WHERE id=?", (watch_id,)).fetchone()
    if not existing:
        conn.close()
        raise HTTPException(404, "Watch not found")
    conn.execute("DELETE FROM watches WHERE id=?", (watch_id,))
    conn.commit()
    conn.close()
    await broadcast({"type": "watch_deleted", "watch_id": watch_id})
    return {"ok": True}


# ---------------------------------------------------------------------------
# API — Folders
# ---------------------------------------------------------------------------


@app.get("/api/folders")
def list_folders():
    conn = get_db()
    folders = [dict(r) for r in conn.execute("SELECT * FROM folders ORDER BY sort_order").fetchall()]
    # Add watch counts
    for f in folders:
        f["watch_count"] = conn.execute(
            "SELECT COUNT(*) FROM watches WHERE folder_id=?", (f["id"],)
        ).fetchone()[0]
    conn.close()
    return folders


@app.post("/api/folders")
def create_folder(folder: FolderCreate):
    conn = get_db()
    fid = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()
    max_order = conn.execute("SELECT COALESCE(MAX(sort_order),0) FROM folders").fetchone()[0]
    conn.execute(
        "INSERT INTO folders (id, name, parent_id, color, icon, sort_order, created_at) VALUES (?,?,?,?,?,?,?)",
        (fid, folder.name, folder.parent_id, folder.color, folder.icon, max_order + 1, now),
    )
    conn.commit()
    row = dict(conn.execute("SELECT * FROM folders WHERE id=?", (fid,)).fetchone())
    row["watch_count"] = 0
    conn.close()
    return row


# ---------------------------------------------------------------------------
# API — Changes
# ---------------------------------------------------------------------------


@app.get("/api/changes/{watch_id}")
def get_changes(watch_id: str, limit: int = Query(default=10, le=100)):
    conn = get_db()
    rows = conn.execute(
        "SELECT * FROM changes WHERE watch_id=? ORDER BY timestamp DESC LIMIT ?",
        (watch_id, limit),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# API — Bulk operations
# ---------------------------------------------------------------------------


@app.post("/api/bulk")
async def bulk_action(data: BulkAction):
    conn = get_db()
    affected = 0

    if data.action == "delete":
        for wid in data.watch_ids:
            conn.execute("DELETE FROM watches WHERE id=?", (wid,))
            affected += 1
    elif data.action == "move_folder":
        folder_id = data.value if data.value else None
        for wid in data.watch_ids:
            conn.execute("UPDATE watches SET folder_id=? WHERE id=?", (folder_id, wid))
            affected += 1
    elif data.action == "add_tag":
        for wid in data.watch_ids:
            row = conn.execute("SELECT tags FROM watches WHERE id=?", (wid,)).fetchone()
            if row:
                tags = json.loads(row[0]) if row[0] else []
                if data.value and data.value not in tags:
                    tags.append(data.value)
                conn.execute("UPDATE watches SET tags=? WHERE id=?", (json.dumps(tags), wid))
                affected += 1
    elif data.action == "remove_tag":
        for wid in data.watch_ids:
            row = conn.execute("SELECT tags FROM watches WHERE id=?", (wid,)).fetchone()
            if row:
                tags = json.loads(row[0]) if row[0] else []
                if data.value in tags:
                    tags.remove(data.value)
                conn.execute("UPDATE watches SET tags=? WHERE id=?", (json.dumps(tags), wid))
                affected += 1
    elif data.action == "pause":
        for wid in data.watch_ids:
            conn.execute("UPDATE watches SET status='paused' WHERE id=?", (wid,))
            affected += 1
    elif data.action == "resume":
        for wid in data.watch_ids:
            conn.execute("UPDATE watches SET status='ok' WHERE id=?", (wid,))
            affected += 1

    conn.commit()
    conn.close()
    await broadcast({"type": "bulk_action", "action": data.action, "count": affected})
    return {"ok": True, "affected": affected}


# ---------------------------------------------------------------------------
# API — Stats
# ---------------------------------------------------------------------------


@app.get("/api/stats")
def get_stats():
    conn = get_db()
    total = conn.execute("SELECT COUNT(*) FROM watches").fetchone()[0]
    today_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0).isoformat()
    changes_today = conn.execute(
        "SELECT COUNT(*) FROM changes WHERE timestamp >= ?", (today_start,)
    ).fetchone()[0]
    errored = conn.execute("SELECT COUNT(*) FROM watches WHERE status='error'").fetchone()[0]
    paused = conn.execute("SELECT COUNT(*) FROM watches WHERE status='paused'").fetchone()[0]
    changed = conn.execute("SELECT COUNT(*) FROM watches WHERE status='changed'").fetchone()[0]
    folders = conn.execute("SELECT COUNT(*) FROM folders").fetchone()[0]

    # Tag breakdown
    rows = conn.execute("SELECT tags FROM watches").fetchall()
    tag_counts: dict[str, int] = {}
    for r in rows:
        for t in json.loads(r[0]) if r[0] else []:
            tag_counts[t] = tag_counts.get(t, 0) + 1
    top_tags = sorted(tag_counts.items(), key=lambda x: -x[1])[:15]

    conn.close()
    return {
        "total_watches": total,
        "changes_today": changes_today,
        "errored": errored,
        "paused": paused,
        "changed": changed,
        "folders": folders,
        "top_tags": [{"tag": t, "count": c} for t, c in top_tags],
    }
