"""ytdl-web — Self-hosted web UI for yt-dlp with download queue and format picker.

Features:
- Paste URL → pick format → download
- Queue with progress tracking
- Download history in SQLite
- Format/quality presets
- WebSocket for real-time progress
"""

import asyncio
import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException, Query, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles

app = FastAPI(title="ytdl-web", version="1.0.0")

static_dir = Path(__file__).parent / "static"
if static_dir.exists():
    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

# Config
DOWNLOAD_DIR = os.environ.get("YTDL_DOWNLOAD_DIR", str(Path(__file__).parent / "downloads"))
DB_PATH = os.environ.get("YTDL_DB_PATH", str(Path(__file__).parent / "ytdl_web.db"))
YTDLP_PATH = os.environ.get("YTDL_PATH", "yt-dlp")
MAX_CONCURRENT = int(os.environ.get("YTDL_MAX_CONCURRENT", "3"))

# Global state
download_queue: dict[str, dict] = {}  # task_id -> task info
ws_clients: set[WebSocket] = set()
active_downloads = 0
download_lock = threading.Lock()

Path(DOWNLOAD_DIR).mkdir(parents=True, exist_ok=True)


def init_db():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS downloads (
            id TEXT PRIMARY KEY,
            url TEXT NOT NULL,
            title TEXT,
            thumbnail TEXT,
            format_id TEXT,
            format_label TEXT,
            filename TEXT,
            filesize INTEGER,
            duration TEXT,
            status TEXT DEFAULT 'queued',
            progress REAL DEFAULT 0,
            speed TEXT,
            eta TEXT,
            error TEXT,
            created_at TEXT NOT NULL,
            completed_at TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_downloads_status ON downloads(status);
        CREATE INDEX IF NOT EXISTS idx_downloads_created ON downloads(created_at);
    """)
    conn.commit()
    conn.close()


def db_exec(sql, params=()):
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    result = conn.execute(sql, params)
    rows = result.fetchall()
    conn.commit()
    conn.close()
    return [dict(r) for r in rows]


def db_one(sql, params=()):
    rows = db_exec(sql, params)
    return rows[0] if rows else None


async def broadcast(msg: dict):
    """Send message to all connected WebSocket clients."""
    text = json.dumps(msg)
    dead = set()
    for ws in ws_clients:
        try:
            await ws.send_text(text)
        except:
            dead.add(ws)
    ws_clients -= dead


def get_video_info(url: str) -> dict:
    """Get video info without downloading."""
    try:
        result = subprocess.run(
            [YTDLP_PATH, "--dump-json", "--no-download", "--no-playlist", url],
            capture_output=True, text=True, timeout=30,
        )
        if result.returncode != 0:
            return {"error": result.stderr.strip()}
        data = json.loads(result.stdout)
        formats = []
        for f in data.get("formats", []):
            if f.get("vcodec", "none") != "none" or f.get("acodec", "none") != "none":
                label = f.get("format_note", "") or f.get("format", "")
                ext = f.get("ext", "")
                size = f.get("filesize") or f.get("filesize_approx")
                resolution = f.get("resolution", "")
                vcodec = f.get("vcodec", "none")
                acodec = f.get("acodec", "none")
                has_video = vcodec != "none"
                has_audio = acodec != "none"
                type_label = "video+audio" if has_video and has_audio else "video" if has_video else "audio"
                formats.append({
                    "format_id": f.get("format_id"),
                    "label": f"{label} ({ext})" if label else ext,
                    "ext": ext,
                    "resolution": resolution,
                    "filesize": size,
                    "type": type_label,
                    "vcodec": vcodec[:10] if vcodec else None,
                    "acodec": acodec[:10] if acodec else None,
                    "tbr": f.get("tbr"),
                })

        return {
            "title": data.get("title", "Unknown"),
            "thumbnail": data.get("thumbnail"),
            "duration": data.get("duration_string") or str(data.get("duration", "")),
            "uploader": data.get("uploader"),
            "url": url,
            "formats": sorted(formats, key=lambda x: x.get("tbr") or 0, reverse=True)[:20],
        }
    except subprocess.TimeoutExpired:
        return {"error": "Timeout fetching video info"}
    except Exception as e:
        return {"error": str(e)}


def run_download(task_id: str, url: str, format_id: str, format_label: str):
    """Run a download in a background thread."""
    global active_downloads
    loop = asyncio.new_event_loop()

    try:
        with download_lock:
            active_downloads += 1

        db_exec("UPDATE downloads SET status='downloading' WHERE id=?", (task_id,))
        download_queue[task_id]["status"] = "downloading"

        cmd = [YTDLP_PATH, "--newline", "--progress"]
        if format_id and format_id != "best":
            cmd += ["-f", format_id]
        else:
            cmd += ["-f", "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best"]

        cmd += [
            "-o", str(Path(DOWNLOAD_DIR) / "%(title)s.%(ext)s"),
            "--no-playlist",
            url,
        ]

        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        filename = None

        for line in proc.stdout:
            line = line.strip()

            # Parse progress
            pct_match = re.search(r'\[download\]\s+(\d+\.?\d*)%', line)
            speed_match = re.search(r'at\s+(\S+/s)', line)
            eta_match = re.search(r'ETA\s+(\S+)', line)
            dest_match = re.search(r'\[download\] Destination:\s+(.+)', line)
            merge_match = re.search(r'\[Merger\] Merging formats into "(.+)"', line)

            if dest_match:
                filename = dest_match.group(1)
            if merge_match:
                filename = merge_match.group(1)

            if pct_match:
                pct = float(pct_match.group(1))
                speed = speed_match.group(1) if speed_match else ""
                eta = eta_match.group(1) if eta_match else ""

                db_exec("UPDATE downloads SET progress=?, speed=?, eta=? WHERE id=?",
                        (pct, speed, eta, task_id))
                download_queue[task_id].update({"progress": pct, "speed": speed, "eta": eta})

                # Broadcast to WS clients
                asyncio.run_coroutine_threadsafe(broadcast({
                    "type": "progress",
                    "task_id": task_id,
                    "progress": pct,
                    "speed": speed,
                    "eta": eta,
                }), loop=_main_loop)

        proc.wait()

        if proc.returncode == 0:
            filesize = None
            if filename and Path(filename).exists():
                filesize = Path(filename).stat().st_size

            db_exec(
                "UPDATE downloads SET status='completed', progress=100, filename=?, filesize=?, completed_at=? WHERE id=?",
                (filename, filesize, datetime.now(timezone.utc).isoformat(), task_id),
            )
            download_queue[task_id].update({"status": "completed", "progress": 100, "filename": filename})
            asyncio.run_coroutine_threadsafe(broadcast({
                "type": "completed", "task_id": task_id, "filename": filename,
            }), loop=_main_loop)
        else:
            db_exec("UPDATE downloads SET status='error', error=? WHERE id=?",
                    (f"Exit code {proc.returncode}", task_id))
            download_queue[task_id]["status"] = "error"
            asyncio.run_coroutine_threadsafe(broadcast({
                "type": "error", "task_id": task_id, "error": f"Exit code {proc.returncode}",
            }), loop=_main_loop)

    except Exception as e:
        db_exec("UPDATE downloads SET status='error', error=? WHERE id=?", (str(e), task_id))
        download_queue[task_id]["status"] = "error"
    finally:
        with download_lock:
            active_downloads -= 1


_main_loop = None


@app.on_event("startup")
async def startup():
    global _main_loop
    init_db()
    _main_loop = asyncio.get_event_loop()


@app.get("/", response_class=HTMLResponse)
async def index():
    html_file = Path(__file__).parent / "static" / "index.html"
    return HTMLResponse(content=html_file.read_text(encoding="utf-8"))


@app.post("/api/info")
async def video_info(body: dict):
    """Get video info and available formats."""
    url = body.get("url", "").strip()
    if not url:
        raise HTTPException(400, "URL required")
    info = await asyncio.get_event_loop().run_in_executor(None, get_video_info, url)
    if "error" in info:
        raise HTTPException(400, info["error"])
    return info


@app.post("/api/download")
async def start_download(body: dict):
    """Queue a download."""
    url = body.get("url", "").strip()
    format_id = body.get("format_id", "best")
    format_label = body.get("format_label", "Best")
    title = body.get("title", "Unknown")
    thumbnail = body.get("thumbnail", "")

    if not url:
        raise HTTPException(400, "URL required")

    task_id = str(uuid.uuid4())[:8]
    now = datetime.now(timezone.utc).isoformat()

    db_exec(
        "INSERT INTO downloads (id, url, title, thumbnail, format_id, format_label, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (task_id, url, title, thumbnail, format_id, format_label, now),
    )

    download_queue[task_id] = {
        "id": task_id, "url": url, "title": title, "thumbnail": thumbnail,
        "format_label": format_label, "status": "queued", "progress": 0,
    }

    # Start download thread
    t = threading.Thread(target=run_download, args=(task_id, url, format_id, format_label), daemon=True)
    t.start()

    await broadcast({"type": "queued", "task_id": task_id, "title": title})

    return {"task_id": task_id, "status": "queued"}


@app.get("/api/downloads")
async def list_downloads(limit: int = Query(50, ge=1, le=500)):
    """Get download history."""
    return db_exec("SELECT * FROM downloads ORDER BY created_at DESC LIMIT ?", (limit,))


@app.get("/api/queue")
async def get_queue():
    """Get current download queue."""
    return list(download_queue.values())


@app.delete("/api/downloads/{task_id}")
async def delete_download(task_id: str):
    """Delete a download record."""
    dl = db_one("SELECT * FROM downloads WHERE id=?", (task_id,))
    if not dl:
        raise HTTPException(404, "Download not found")
    if dl.get("filename") and Path(dl["filename"]).exists():
        Path(dl["filename"]).unlink(missing_ok=True)
    db_exec("DELETE FROM downloads WHERE id=?", (task_id,))
    download_queue.pop(task_id, None)
    return {"status": "deleted"}


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    ws_clients.add(websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        ws_clients.discard(websocket)


if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("YTDL_PORT", 8504))
    uvicorn.run(app, host="0.0.0.0", port=port)
