"""
GoTTY Manager - FastAPI management layer for terminal sharing sessions.

Features:
- Session management (create, list, terminate terminal sessions)
- Token-based authentication
- SQLite session history via aiosqlite
- xterm.js embedded terminal (CDN)
- Admin dashboard
- WebSocket proxying to subprocess shells
- Rate limiting on session creation
"""

import asyncio
import json
import logging
import os
import secrets
import signal
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import aiosqlite
from fastapi import (
    Depends,
    FastAPI,
    HTTPException,
    Request,
    WebSocket,
    WebSocketDisconnect,
    status,
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
)
logger = logging.getLogger("gotty_manager")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
PORT = 8507
DB_PATH = Path(__file__).parent / "sessions.db"
STATIC_DIR = Path(__file__).parent / "static"

# Default shell per platform
if sys.platform == "win32":
    DEFAULT_SHELL = ["powershell.exe", "-NoLogo", "-NoProfile"]
else:
    DEFAULT_SHELL = [os.environ.get("SHELL", "/bin/bash")]

# ---------------------------------------------------------------------------
# Rate limiter
# ---------------------------------------------------------------------------
limiter = Limiter(key_func=get_remote_address, default_limits=["200/minute"])

# ---------------------------------------------------------------------------
# FastAPI app
# ---------------------------------------------------------------------------
app = FastAPI(
    title="GoTTY Manager",
    description="Web-based terminal session management",
    version="1.0.0",
)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount static files
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

# ---------------------------------------------------------------------------
# In-memory session store
# ---------------------------------------------------------------------------
# session_id -> {token, process, websockets, created_at, user_agent, remote_addr, cmd}
active_sessions: dict[str, dict] = {}


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------
class SessionCreate(BaseModel):
    command: Optional[list[str]] = None
    label: Optional[str] = None


class SessionInfo(BaseModel):
    session_id: str
    token: str
    label: str
    command: list[str]
    created_at: str
    remote_addr: str
    user_agent: str
    pid: Optional[int]
    active: bool


# ---------------------------------------------------------------------------
# Database helpers
# ---------------------------------------------------------------------------
async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS session_history (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id  TEXT NOT NULL,
                token       TEXT NOT NULL,
                label       TEXT,
                command     TEXT,
                remote_addr TEXT,
                user_agent  TEXT,
                created_at  TEXT NOT NULL,
                ended_at    TEXT,
                exit_code   INTEGER
            )
            """
        )
        await db.commit()
    logger.info("Database initialised at %s", DB_PATH)


async def db_insert_session(session_id: str, token: str, label: str,
                             command: list[str], remote_addr: str, user_agent: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """
            INSERT INTO session_history
                (session_id, token, label, command, remote_addr, user_agent, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                session_id,
                token,
                label,
                json.dumps(command),
                remote_addr,
                user_agent,
                datetime.now(timezone.utc).isoformat(),
            ),
        )
        await db.commit()


async def db_end_session(session_id: str, exit_code: Optional[int] = None):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """
            UPDATE session_history
            SET ended_at = ?, exit_code = ?
            WHERE session_id = ? AND ended_at IS NULL
            """,
            (datetime.now(timezone.utc).isoformat(), exit_code, session_id),
        )
        await db.commit()


async def db_get_history(limit: int = 50) -> list[dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM session_history ORDER BY id DESC LIMIT ?", (limit,)
        ) as cursor:
            rows = await cursor.fetchall()
            return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# Startup / shutdown
# ---------------------------------------------------------------------------
@app.on_event("startup")
async def startup():
    await init_db()
    logger.info("GoTTY Manager started on port %d", PORT)


@app.on_event("shutdown")
async def shutdown():
    # Terminate all active subprocesses
    for sid, info in list(active_sessions.items()):
        proc: Optional[asyncio.subprocess.Process] = info.get("process")
        if proc and proc.returncode is None:
            try:
                proc.terminate()
            except Exception:
                pass
    logger.info("GoTTY Manager shut down")


# ---------------------------------------------------------------------------
# Auth helper
# ---------------------------------------------------------------------------
def get_session_by_token(token: str) -> Optional[tuple[str, dict]]:
    for sid, info in active_sessions.items():
        if info["token"] == token:
            return sid, info
    return None


# ---------------------------------------------------------------------------
# Routes - Pages
# ---------------------------------------------------------------------------
@app.get("/", response_class=FileResponse)
async def index():
    return FileResponse(str(STATIC_DIR / "index.html"))


@app.get("/terminal/{session_id}", response_class=FileResponse)
async def terminal_page(session_id: str):
    if session_id not in active_sessions:
        raise HTTPException(status_code=404, detail="Session not found")
    return FileResponse(str(STATIC_DIR / "terminal.html"))


# ---------------------------------------------------------------------------
# Routes - Session API
# ---------------------------------------------------------------------------
@app.post("/api/sessions", response_model=SessionInfo)
@limiter.limit("10/minute")
async def create_session(request: Request, body: SessionCreate):
    """Create a new terminal session."""
    session_id = secrets.token_urlsafe(12)
    token = secrets.token_urlsafe(32)
    command = body.command or DEFAULT_SHELL
    label = body.label or f"Session {session_id[:6]}"
    remote_addr = request.client.host if request.client else "unknown"
    user_agent = request.headers.get("user-agent", "unknown")
    created_at = datetime.now(timezone.utc).isoformat()

    # Launch subprocess
    try:
        if sys.platform == "win32":
            proc = await asyncio.create_subprocess_exec(
                *command,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
                creationflags=subprocess.CREATE_NEW_PROCESS_GROUP,
            )
        else:
            proc = await asyncio.create_subprocess_exec(
                *command,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
                preexec_fn=os.setsid,
            )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to start shell: {exc}")

    active_sessions[session_id] = {
        "token": token,
        "process": proc,
        "websockets": [],
        "created_at": created_at,
        "remote_addr": remote_addr,
        "user_agent": user_agent,
        "command": command,
        "label": label,
    }

    await db_insert_session(session_id, token, label, command, remote_addr, user_agent)
    logger.info("Created session %s (pid=%s cmd=%s)", session_id, proc.pid, command)

    return SessionInfo(
        session_id=session_id,
        token=token,
        label=label,
        command=command,
        created_at=created_at,
        remote_addr=remote_addr,
        user_agent=user_agent,
        pid=proc.pid,
        active=True,
    )


@app.get("/api/sessions")
async def list_sessions():
    """List all active sessions."""
    result = []
    for sid, info in active_sessions.items():
        proc: Optional[asyncio.subprocess.Process] = info.get("process")
        pid = proc.pid if proc else None
        alive = proc is not None and proc.returncode is None
        result.append(
            {
                "session_id": sid,
                "label": info["label"],
                "command": info["command"],
                "created_at": info["created_at"],
                "remote_addr": info["remote_addr"],
                "user_agent": info["user_agent"],
                "pid": pid,
                "active": alive,
                "ws_clients": len(info["websockets"]),
            }
        )
    return result


@app.delete("/api/sessions/{session_id}")
async def terminate_session(session_id: str):
    """Terminate a terminal session."""
    if session_id not in active_sessions:
        raise HTTPException(status_code=404, detail="Session not found")

    info = active_sessions.pop(session_id)
    proc: Optional[asyncio.subprocess.Process] = info.get("process")
    exit_code = None

    if proc and proc.returncode is None:
        try:
            if sys.platform == "win32":
                proc.terminate()
            else:
                os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
            try:
                exit_code = await asyncio.wait_for(proc.wait(), timeout=3.0)
            except asyncio.TimeoutError:
                proc.kill()
        except Exception as exc:
            logger.warning("Error terminating session %s: %s", session_id, exc)

    # Notify connected WebSocket clients
    for ws in info.get("websockets", []):
        try:
            await ws.send_json({"type": "exit", "code": exit_code})
            await ws.close()
        except Exception:
            pass

    await db_end_session(session_id, exit_code)
    logger.info("Terminated session %s (exit=%s)", session_id, exit_code)
    return {"status": "terminated", "session_id": session_id, "exit_code": exit_code}


@app.get("/api/history")
async def get_history(limit: int = 50):
    """Retrieve session history from SQLite."""
    return await db_get_history(limit=min(limit, 200))


@app.get("/api/health")
async def health():
    return {
        "status": "ok",
        "active_sessions": len(active_sessions),
        "version": "1.0.0",
    }


# ---------------------------------------------------------------------------
# WebSocket - terminal proxying
# ---------------------------------------------------------------------------
@app.websocket("/ws/{session_id}")
async def websocket_terminal(websocket: WebSocket, session_id: str, token: str = ""):
    """Proxy WebSocket <-> subprocess stdin/stdout."""
    # Validate session & token
    if session_id not in active_sessions:
        await websocket.close(code=4004, reason="Session not found")
        return

    info = active_sessions[session_id]
    if info["token"] != token:
        await websocket.close(code=4003, reason="Invalid token")
        return

    proc: asyncio.subprocess.Process = info["process"]
    if proc.returncode is not None:
        await websocket.close(code=4010, reason="Process already exited")
        return

    await websocket.accept()
    info["websockets"].append(websocket)
    logger.info("WS connected to session %s", session_id)

    async def read_stdout():
        """Read process stdout and forward to WebSocket."""
        try:
            while True:
                chunk = await proc.stdout.read(4096)
                if not chunk:
                    break
                await websocket.send_bytes(chunk)
        except Exception:
            pass

    async def read_ws():
        """Read WebSocket messages and forward to process stdin."""
        try:
            while True:
                data = await websocket.receive()
                if "bytes" in data and data["bytes"]:
                    proc.stdin.write(data["bytes"])
                    await proc.stdin.drain()
                elif "text" in data and data["text"]:
                    proc.stdin.write(data["text"].encode())
                    await proc.stdin.drain()
        except WebSocketDisconnect:
            pass
        except Exception:
            pass

    stdout_task = asyncio.create_task(read_stdout())
    ws_task = asyncio.create_task(read_ws())

    done, pending = await asyncio.wait(
        [stdout_task, ws_task],
        return_when=asyncio.FIRST_COMPLETED,
    )
    for t in pending:
        t.cancel()

    try:
        info["websockets"].remove(websocket)
    except ValueError:
        pass

    # Check if process ended
    if proc.returncode is not None and session_id in active_sessions:
        active_sessions.pop(session_id, None)
        await db_end_session(session_id, proc.returncode)

    try:
        await websocket.close()
    except Exception:
        pass

    logger.info("WS disconnected from session %s", session_id)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import uvicorn

    uvicorn.run("gotty_manager.app:app", host="0.0.0.0", port=PORT, reload=False)
