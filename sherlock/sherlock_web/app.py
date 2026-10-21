"""Sherlock Web UI - FastAPI backend with WebSocket streaming."""

import asyncio
import csv
import io
import json
import os
import sys
import time
import traceback
from pathlib import Path
from datetime import datetime, timezone

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException, Query
from fastapi.responses import HTMLResponse, StreamingResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

# Add parent dir to path so we can import sherlock_project
sys.path.insert(0, str(Path(__file__).parent.parent))

from sherlock_project.sherlock import sherlock as run_sherlock
from sherlock_project.sites import SitesInformation
from sherlock_project.result import QueryStatus, QueryResult
from sherlock_project.notify import QueryNotify

from . import database

app = FastAPI(title="Sherlock Web UI", version="1.0.0")

# Serve static files
static_dir = Path(__file__).parent / "static"
if static_dir.exists():
    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")


@app.on_event("startup")
async def startup():
    database.init_db()


class WebSocketNotifier(QueryNotify):
    """Custom notifier that sends results via WebSocket."""

    def __init__(self, search_id: int):
        super().__init__()
        self.search_id = search_id
        self.results_queue = asyncio.Queue()

    def start(self, message=None):
        pass

    def update(self, result):
        """Called for each site result. result is a QueryResult object."""
        try:
            status_str = result.status.name if isinstance(result.status, QueryStatus) else str(result.status)
            response_time_ms = round(result.query_time * 1000, 1) if result.query_time else None

            data = {
                "type": "result",
                "site_name": result.site_name,
                "url_user": result.site_url_user,
                "status": status_str,
                "response_time_ms": response_time_ms,
                "context": result.context,
            }
            self.results_queue.put_nowait(data)
        except Exception as e:
            self.results_queue.put_nowait({
                "type": "result",
                "site_name": getattr(result, "site_name", "unknown"),
                "url_user": getattr(result, "site_url_user", ""),
                "status": "UNKNOWN",
                "response_time_ms": None,
                "context": str(e),
            })

    def finish(self, message=None):
        self.results_queue.put_nowait({"type": "done"})

    def __str__(self):
        return "WebSocketNotifier"


def run_search_sync(username: str, search_id: int, notifier: WebSocketNotifier,
                    timeout: int = 60, nsfw: bool = False, site_filter: list = None):
    """Run sherlock search synchronously (called from thread)."""
    try:
        sites = SitesInformation()
        if not nsfw:
            sites.remove_nsfw_sites()

        site_data = {site.name: site.information for site in sites}

        if site_filter:
            site_filter_lower = [s.lower() for s in site_filter]
            site_data = {k: v for k, v in site_data.items() if k.lower() in site_filter_lower}

        total_sites = len(site_data)

        # Run the actual sherlock search - notifier.update() will be called for each site
        results = run_sherlock(
            username=username,
            site_data=site_data,
            query_notify=notifier,
            timeout=timeout,
        )

        # Count results and persist to DB
        found_count = 0
        error_count = 0

        for site_name, result_data in results.items():
            status_obj = result_data.get("status")
            if isinstance(status_obj, QueryResult):
                status_name = status_obj.status.name if isinstance(status_obj.status, QueryStatus) else str(status_obj.status)
                url_main = result_data.get("url_main", "")
                url_user = result_data.get("url_user", "")
                http_status = str(result_data.get("http_status", ""))
                rt_ms = round(status_obj.query_time * 1000, 1) if status_obj.query_time else None

                if status_name == "CLAIMED":
                    found_count += 1
                elif status_name in ("UNKNOWN", "WAF"):
                    error_count += 1

                database.add_result(
                    search_id=search_id,
                    site_name=site_name,
                    url_main=url_main,
                    url_user=url_user,
                    status=status_name,
                    http_status=http_status,
                    response_time_ms=rt_ms,
                )

        database.finish_search(search_id, total_sites, found_count, error_count)
        notifier.finish()

    except Exception as e:
        tb = traceback.format_exc()
        print(f"Search error: {e}\n{tb}", file=sys.stderr)
        notifier.results_queue.put_nowait({
            "type": "error",
            "message": f"{str(e)}",
        })


@app.get("/", response_class=HTMLResponse)
async def index():
    html_file = Path(__file__).parent / "static" / "index.html"
    return HTMLResponse(content=html_file.read_text(encoding="utf-8"))


@app.websocket("/ws/search")
async def websocket_search(websocket: WebSocket):
    await websocket.accept()
    try:
        data = await websocket.receive_json()
        username = data.get("username", "").strip()
        timeout = data.get("timeout", 60)
        nsfw = data.get("nsfw", False)
        site_filter = data.get("sites", None)

        if not username:
            await websocket.send_json({"type": "error", "message": "Username required"})
            await websocket.close()
            return

        search_id = database.create_search(username)
        await websocket.send_json({"type": "started", "search_id": search_id, "username": username})

        notifier = WebSocketNotifier(search_id)

        # Run search in a thread to not block the event loop
        loop = asyncio.get_event_loop()
        search_task = loop.run_in_executor(
            None,
            run_search_sync,
            username,
            search_id,
            notifier,
            timeout,
            nsfw,
            site_filter,
        )

        # Stream results from queue to websocket
        while True:
            try:
                result = await asyncio.wait_for(notifier.results_queue.get(), timeout=1.0)
                await websocket.send_json(result)
                if result.get("type") in ("done", "error"):
                    break
            except asyncio.TimeoutError:
                # Check if search task is done
                if search_task.done():
                    # Drain remaining items
                    while not notifier.results_queue.empty():
                        result = notifier.results_queue.get_nowait()
                        await websocket.send_json(result)
                    # Check for exceptions
                    exc = search_task.exception()
                    if exc:
                        await websocket.send_json({"type": "error", "message": str(exc)})
                    break
                continue

    except WebSocketDisconnect:
        pass
    except Exception as e:
        try:
            await websocket.send_json({"type": "error", "message": str(e)})
        except:
            pass


@app.get("/api/history")
async def search_history(limit: int = Query(50, ge=1, le=500)):
    return database.get_search_history(limit)


@app.get("/api/search/{search_id}")
async def get_search(search_id: int):
    search = database.get_search(search_id)
    if not search:
        raise HTTPException(status_code=404, detail="Search not found")
    search["results"] = database.get_search_results(search_id)
    return search


@app.get("/api/search/{search_id}/export/csv")
async def export_csv(search_id: int):
    search = database.get_search(search_id)
    if not search:
        raise HTTPException(status_code=404, detail="Search not found")

    results = database.get_search_results(search_id)

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["Site", "URL", "Status", "HTTP Status", "Response Time (ms)"])
    for r in results:
        writer.writerow([r["site_name"], r["url_user"], r["status"], r["http_status"], r["response_time_ms"]])

    output.seek(0)
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename=sherlock_{search['username']}.csv"},
    )


@app.get("/api/search/{search_id}/export/json")
async def export_json(search_id: int):
    search = database.get_search(search_id)
    if not search:
        raise HTTPException(status_code=404, detail="Search not found")

    results = database.get_search_results(search_id)
    found = [r for r in results if r["status"] == "CLAIMED"]

    export = {
        "username": search["username"],
        "searched_at": search["started_at"],
        "total_sites": search["total_sites"],
        "profiles_found": len(found),
        "profiles": [
            {
                "site": r["site_name"],
                "url": r["url_user"],
                "http_status": r["http_status"],
                "response_time_ms": r["response_time_ms"],
            }
            for r in found
        ],
    }

    return JSONResponse(
        content=export,
        headers={"Content-Disposition": f"attachment; filename=sherlock_{search['username']}.json"},
    )


@app.get("/api/sites")
async def list_sites():
    sites = SitesInformation()
    return {"count": len(sites), "sites": sorted(sites.site_name_list())}


if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("SHERLOCK_PORT", 8501))
    uvicorn.run(app, host="0.0.0.0", port=port)
