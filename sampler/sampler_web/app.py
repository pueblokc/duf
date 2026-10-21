"""
sampler_web/app.py

FastAPI web companion for the sampler terminal dashboard tool.
Serves on port 8506. Parses sampler YAML configs, runs shell commands
periodically, and pushes real-time updates to connected browsers via WebSocket.

Demo mode (--demo / no config file) starts with a built-in system dashboard.
"""

import asyncio
import json
import logging
import os
import platform
import subprocess
import sys
import time
from collections import deque
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

import psutil
import yaml
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

# ── Logging ──────────────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("sampler_web")

# ── Constants ─────────────────────────────────────────────────────────────────

STATIC_DIR = Path(__file__).parent / "static"
DEFAULT_RATE_MS = 2000
HISTORY_LEN = 120          # samples kept per widget item
PORT = 8506


# ── Widget data store ─────────────────────────────────────────────────────────

class WidgetStore:
    """
    Holds parsed config + live data for every widget.

    self.widgets = [
        {
            "id":       str,
            "type":     "sparkline" | "gauge" | "barchart" | "runchart" | "textbox" | "asciibox",
            "title":    str,
            "rate_ms":  int,
            "items": [
                {
                    "label":   str,
                    "history": deque([float, ...]),   # sparkline/runchart/barchart
                    "current": float | str,
                    "color":   str,                   # CSS colour
                },
            ],
            # gauge-specific
            "min": float,
            "max": float,
            "thresholds": list[dict],
        }
    ]
    """

    ANSI_COLORS = {
        # subset of 256-colour → CSS
        178: "#d7af00", 196: "#ff0000", 46: "#00ff00",
        51:  "#00ffff", 201: "#ff00ff", 226: "#ffff00",
        214: "#ffaf00", 82:  "#5fff00", 27: "#005fff",
    }

    def __init__(self):
        self.widgets: list[dict] = []
        self.lock = asyncio.Lock()

    # ── YAML config parsing ───────────────────────────────────────────────────

    def load_yaml(self, path: str) -> None:
        with open(path) as fh:
            cfg = yaml.safe_load(fh)
        self.widgets.clear()
        idx = 0

        section_map = {
            "sparklines":  "sparkline",
            "runcharts":   "runchart",
            "barcharts":   "barchart",
            "gauges":      "gauge",
            "textboxes":   "textbox",
            "asciiboxes":  "asciibox",
        }

        for section, wtype in section_map.items():
            for raw in (cfg.get(section) or []):
                widget = self._parse_widget(raw, wtype, idx)
                self.widgets.append(widget)
                idx += 1

        log.info("Loaded %d widgets from %s", len(self.widgets), path)

    def _ansi_to_css(self, code: Optional[int]) -> str:
        if code is None:
            return "#00ff88"
        return self.ANSI_COLORS.get(code, "#00ff88")

    def _parse_widget(self, raw: dict, wtype: str, idx: int) -> dict:
        rate_ms = raw.get("rate-ms", DEFAULT_RATE_MS)
        title   = raw.get("title", f"Widget {idx}")

        # position: [[col, row], [width, height]]
        pos = raw.get("position", [[0, 0], [30, 10]])

        widget: dict[str, Any] = {
            "id":       f"w{idx}",
            "type":     wtype,
            "title":    title,
            "rate_ms":  rate_ms,
            "position": pos,
            "items":    [],
            "min":      0.0,
            "max":      100.0,
            "thresholds": [],
        }

        if wtype in ("sparkline", "textbox", "asciibox"):
            widget["items"] = [{
                "label":   title,
                "sample":  raw.get("sample", ""),
                "history": deque(maxlen=HISTORY_LEN),
                "current": 0.0,
                "color":   self._ansi_to_css(raw.get("color")),
            }]

        elif wtype in ("runchart", "barchart"):
            for item in (raw.get("items") or []):
                widget["items"].append({
                    "label":   item.get("label", "?"),
                    "sample":  item.get("sample", ""),
                    "history": deque(maxlen=HISTORY_LEN),
                    "current": 0.0,
                    "color":   self._ansi_to_css(item.get("color")),
                })

        elif wtype == "gauge":
            for role in ("cur", "min", "max"):
                src = raw.get(role, {})
                widget[f"_{role}_sample"] = src.get("sample", "") if isinstance(src, dict) else ""
            widget["_cur_val"] = 0.0
            widget["_min_val"] = 0.0
            widget["_max_val"] = 100.0
            widget["items"] = [{
                "label":   "cur",
                "sample":  widget.pop("_cur_sample"),
                "history": deque(maxlen=HISTORY_LEN),
                "current": 0.0,
                "color":   "#00ff88",
            }]
            widget["_min_sample"] = widget.pop("_min_sample", "")
            widget["_max_sample"] = widget.pop("_max_sample", "")
            # parse threshold colours from triggers
            for trig in (raw.get("triggers") or []):
                widget["thresholds"].append({
                    "title":     trig.get("title", ""),
                    "condition": trig.get("condition", ""),
                })

        return widget

    # ── Demo mode ─────────────────────────────────────────────────────────────

    def load_demo(self) -> None:
        """
        Build a system monitoring dashboard using psutil — no shell commands
        needed. Each widget has a 'demo_fn' callable instead of 'sample'.
        """
        self.widgets.clear()

        def _w(idx, wtype, title, rate_ms, pos, items, **extra) -> dict:
            return {
                "id":       f"w{idx}",
                "type":     wtype,
                "title":    title,
                "rate_ms":  rate_ms,
                "position": pos,
                "items":    items,
                "min":      extra.get("min", 0.0),
                "max":      extra.get("max", 100.0),
                "thresholds": extra.get("thresholds", []),
                **{k: v for k, v in extra.items()
                   if k not in ("min", "max", "thresholds")},
            }

        def _item(label, fn, color="#00ff88"):
            return {
                "label":    label,
                "demo_fn":  fn,
                "history":  deque(maxlen=HISTORY_LEN),
                "current":  0.0,
                "color":    color,
            }

        # ── Sparklines ────────────────────────────────────────────────────────
        self.widgets.append(_w(
            0, "sparkline", "CPU Usage %", 800,
            [[0, 0], [30, 8]],
            [_item("cpu", lambda: psutil.cpu_percent(interval=None), "#00ff88")],
        ))

        self.widgets.append(_w(
            1, "sparkline", "Memory Usage %", 1500,
            [[30, 0], [30, 8]],
            [_item("mem", lambda: psutil.virtual_memory().percent, "#00ccff")],
        ))

        # ── Gauges ────────────────────────────────────────────────────────────
        self.widgets.append(_w(
            2, "gauge", "CPU Gauge", 800,
            [[0, 9], [30, 4]],
            [_item("cpu", lambda: psutil.cpu_percent(interval=None), "#00ff88")],
            min=0.0, max=100.0,
            thresholds=[
                {"value": 70, "color": "#ffaf00"},
                {"value": 90, "color": "#ff4444"},
            ],
        ))

        disk = psutil.disk_usage("/")
        self.widgets.append(_w(
            3, "gauge", "Disk Usage %", 5000,
            [[30, 9], [30, 4]],
            [_item("disk",
                   lambda: psutil.disk_usage("/").percent,
                   "#ffaf00")],
            min=0.0, max=100.0,
            thresholds=[
                {"value": 80, "color": "#ffaf00"},
                {"value": 95, "color": "#ff4444"},
            ],
        ))

        # ── Bar chart — per-core CPU ──────────────────────────────────────────
        # Pre-warm percpu so first real call returns valid data, not all-zeros.
        psutil.cpu_percent(percpu=True)

        num_cores = psutil.cpu_count(logical=True) or 4
        cores_colors = ["#00ff88", "#00ccff", "#ffaf00", "#ff44aa",
                        "#88ffcc", "#44aaff", "#ffdd44", "#ff88aa"]

        # Shared cache so all 8 core lambdas share one percpu call per cycle.
        _percpu_cache: dict = {"ts": 0.0, "vals": []}

        def _get_core(idx: int) -> float:
            now = time.time()
            if now - _percpu_cache["ts"] > 0.5:
                _percpu_cache["vals"] = psutil.cpu_percent(percpu=True)
                _percpu_cache["ts"] = now
            vals = _percpu_cache["vals"]
            return vals[idx] if idx < len(vals) else 0.0

        core_items = [
            _item(f"Core {i}",
                  (lambda i=i: lambda: _get_core(i))(i),
                  cores_colors[i % len(cores_colors)])
            for i in range(min(num_cores, 8))
        ]
        self.widgets.append(_w(
            4, "barchart", "Per-Core CPU %", 1200,
            [[0, 14], [30, 10]],
            core_items,
            min=0.0, max=100.0,
        ))

        # ── Bar chart — network bytes ─────────────────────────────────────────
        # Single shared counter cache; both sent/recv read from one snapshot.
        _net_cache: dict = {"ts": 0.0, "sent_rate": 0.0, "recv_rate": 0.0,
                            "prev_sent": 0, "prev_recv": 0}

        def _refresh_net() -> None:
            now = time.time()
            if now - _net_cache["ts"] < 0.5:
                return
            c = psutil.net_io_counters()
            dt = max(now - _net_cache["ts"], 0.1) if _net_cache["ts"] else 1.0
            _net_cache["sent_rate"] = max((c.bytes_sent - _net_cache["prev_sent"]) / dt / 1024, 0.0)
            _net_cache["recv_rate"] = max((c.bytes_recv - _net_cache["prev_recv"]) / dt / 1024, 0.0)
            _net_cache.update(ts=now, prev_sent=c.bytes_sent, prev_recv=c.bytes_recv)

        # Prime with current counters so first delta is valid
        _c0 = psutil.net_io_counters()
        _net_cache.update(ts=time.time(), prev_sent=_c0.bytes_sent, prev_recv=_c0.bytes_recv)

        def net_sent():
            _refresh_net()
            return _net_cache["sent_rate"]

        def net_recv():
            _refresh_net()
            return _net_cache["recv_rate"]

        self.widgets.append(_w(
            5, "barchart", "Network KB/s", 1000,
            [[30, 14], [30, 10]],
            [
                _item("Sent",   net_sent,  "#00ff88"),
                _item("Recv",   net_recv,  "#00ccff"),
            ],
        ))

        # ── Text boxes ────────────────────────────────────────────────────────
        def top_procs():
            procs = []
            for p in sorted(psutil.process_iter(["pid", "name", "cpu_percent", "memory_percent"]),
                            key=lambda x: x.info.get("cpu_percent") or 0,
                            reverse=True)[:8]:
                info = p.info
                procs.append(
                    f"{info['pid']:>6}  {(info['name'] or '?')[:20]:<20}  "
                    f"CPU {info.get('cpu_percent') or 0:>5.1f}%  "
                    f"MEM {info.get('memory_percent') or 0:>4.1f}%"
                )
            header = f"{'PID':>6}  {'NAME':<20}  {'CPU':>8}  {'MEM':>7}"
            return header + "\n" + "\n".join(procs)

        self.widgets.append(_w(
            6, "textbox", "Top Processes", 3000,
            [[60, 0], [40, 14]],
            [{
                "label":   "procs",
                "demo_fn": top_procs,
                "history": deque(maxlen=HISTORY_LEN),
                "current": "",
                "color":   "#00ff88",
            }],
        ))

        def sys_info():
            vm = psutil.virtual_memory()
            swap = psutil.swap_memory()
            temps = {}
            try:
                tf = psutil.sensors_temperatures()
                if tf:
                    for name, entries in tf.items():
                        if entries:
                            temps[name] = entries[0].current
            except (AttributeError, OSError):
                pass

            lines = [
                f"  OS       : {platform.system()} {platform.release()}",
                f"  Hostname : {platform.node()}",
                f"  CPU      : {platform.processor()[:40] or 'n/a'}",
                f"  Cores    : {psutil.cpu_count(logical=False)} physical / {psutil.cpu_count(logical=True)} logical",
                f"  RAM      : {vm.total/1e9:.1f} GB total  {vm.available/1e9:.1f} GB free",
                f"  Swap     : {swap.total/1e9:.1f} GB total  {swap.free/1e9:.1f} GB free",
                f"  Uptime   : {str(datetime.fromtimestamp(psutil.boot_time()).strftime('%Y-%m-%d %H:%M'))}",
            ]
            if temps:
                lines.append(f"  Temps    : " + "  ".join(f"{k} {v:.0f}°C" for k, v in list(temps.items())[:3]))
            return "\n".join(lines)

        self.widgets.append(_w(
            7, "textbox", "System Info", 10000,
            [[60, 15], [40, 9]],
            [{
                "label":   "sysinfo",
                "demo_fn": sys_info,
                "history": deque(maxlen=HISTORY_LEN),
                "current": "",
                "color":   "#00ccff",
            }],
        ))

        log.info("Demo mode: %d widgets loaded", len(self.widgets))

    # ── Serialisation for WebSocket ───────────────────────────────────────────

    def snapshot(self) -> list[dict]:
        """Return JSON-serialisable snapshot of all widget state."""
        out = []
        for w in self.widgets:
            items_snap = []
            for item in w["items"]:
                items_snap.append({
                    "label":   item["label"],
                    "history": list(item["history"]),
                    "current": item["current"],
                    "color":   item.get("color", "#00ff88"),
                })
            out.append({
                "id":         w["id"],
                "type":       w["type"],
                "title":      w["title"],
                "position":   w["position"],
                "items":      items_snap,
                "min":        w.get("min", 0.0),
                "max":        w.get("max", 100.0),
                "thresholds": w.get("thresholds", []),
            })
        return out


# ── Command execution ─────────────────────────────────────────────────────────

async def run_shell(cmd: str, timeout: float = 5.0) -> str:
    """Run a shell command asynchronously, return stdout stripped."""
    try:
        proc = await asyncio.create_subprocess_shell(
            cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        return stdout.decode(errors="replace").strip()
    except (asyncio.TimeoutError, Exception) as exc:
        log.debug("Command failed [%s]: %s", cmd[:60], exc)
        return ""


def safe_float(val: str) -> float:
    try:
        return float(val.split()[0])
    except (ValueError, IndexError):
        return 0.0


# ── Background sampling loop ──────────────────────────────────────────────────

class Sampler:
    def __init__(self, store: WidgetStore):
        self.store = store
        self._tasks: list[asyncio.Task] = []

    async def start(self):
        for widget in self.store.widgets:
            task = asyncio.create_task(self._widget_loop(widget))
            self._tasks.append(task)

    async def stop(self):
        for t in self._tasks:
            t.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)
        self._tasks.clear()

    async def _widget_loop(self, widget: dict):
        rate_s = widget["rate_ms"] / 1000.0
        while True:
            try:
                await self._sample_widget(widget)
            except Exception as exc:
                log.debug("Sample error widget %s: %s", widget["id"], exc)
            await asyncio.sleep(rate_s)

    async def _sample_widget(self, widget: dict):
        wtype = widget["type"]

        if wtype == "gauge":
            await self._sample_gauge(widget)
            return

        for item in widget["items"]:
            # Demo path
            if "demo_fn" in item:
                try:
                    loop = asyncio.get_running_loop()
                    val = await loop.run_in_executor(None, item["demo_fn"])
                except Exception:
                    val = ""
            elif "sample" in item:
                val = await run_shell(item["sample"])
            else:
                continue

            if wtype in ("textbox", "asciibox"):
                item["current"] = str(val)
                item["history"].append(str(val))
            else:
                fval = safe_float(str(val)) if not isinstance(val, (int, float)) else float(val)
                item["current"] = fval
                item["history"].append(fval)

    async def _sample_gauge(self, widget: dict):
        item = widget["items"][0]

        if "demo_fn" in item:
            loop = asyncio.get_running_loop()
            cur = await loop.run_in_executor(None, item["demo_fn"])
            widget["min"] = widget.get("min", 0.0)
            widget["max"] = widget.get("max", 100.0)
        else:
            cur_out = await run_shell(widget.get("_min_sample", "echo 0") or "echo 0")
            min_out = await run_shell(widget.get("_min_sample", "echo 0") or "echo 0")
            max_out = await run_shell(widget.get("_max_sample", "echo 100") or "echo 100")
            cur = safe_float(cur_out)
            widget["min"] = safe_float(min_out)
            widget["max"] = safe_float(max_out) or 100.0

        fval = float(cur) if isinstance(cur, (int, float)) else safe_float(str(cur))
        item["current"] = fval
        item["history"].append(fval)


# ── WebSocket connection manager ──────────────────────────────────────────────

class ConnectionManager:
    def __init__(self):
        self.active: set[WebSocket] = set()

    async def connect(self, ws: WebSocket):
        await ws.accept()
        self.active.add(ws)
        log.info("WS client connected  (total: %d)", len(self.active))

    def disconnect(self, ws: WebSocket):
        self.active.discard(ws)
        log.info("WS client disconnected (total: %d)", len(self.active))

    async def broadcast(self, data: dict):
        if not self.active:
            return
        msg = json.dumps(data)
        dead = set()
        for ws in list(self.active):
            try:
                await ws.send_text(msg)
            except Exception:
                dead.add(ws)
        self.active -= dead


# ── App lifecycle ─────────────────────────────────────────────────────────────

store   = WidgetStore()
sampler = Sampler(store)
manager = ConnectionManager()

# Detect config file from env or CLI arg
_config_path = os.environ.get("SAMPLER_CONFIG", "")
if not _config_path and len(sys.argv) > 1 and sys.argv[1].endswith(".yml"):
    _config_path = sys.argv[1]

_demo_mode = not bool(_config_path)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    if _demo_mode:
        log.info("Starting in DEMO mode (no config file specified)")
        store.load_demo()
    else:
        log.info("Loading config: %s", _config_path)
        store.load_yaml(_config_path)

    await sampler.start()

    # Background broadcast loop
    async def _broadcast_loop():
        while True:
            data = {
                "ts":      time.time(),
                "widgets": store.snapshot(),
            }
            await manager.broadcast(data)
            await asyncio.sleep(0.5)          # 2 Hz broadcast rate

    broadcast_task = asyncio.create_task(_broadcast_loop())

    yield

    # Shutdown
    broadcast_task.cancel()
    await sampler.stop()


# ── FastAPI app ────────────────────────────────────────────────────────────────

app = FastAPI(
    title="sampler-web",
    description="Web companion for the sampler terminal dashboard tool",
    version="0.1.0",
    lifespan=lifespan,
)

app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


@app.get("/")
async def root():
    return FileResponse(str(STATIC_DIR / "index.html"))


@app.get("/api/widgets")
async def api_widgets():
    """Return current widget state as JSON."""
    return JSONResponse(content=store.snapshot())


@app.get("/api/status")
async def api_status():
    return {
        "status":    "ok",
        "demo_mode": _demo_mode,
        "config":    _config_path or None,
        "widgets":   len(store.widgets),
        "clients":   len(manager.active),
        "version":   "0.1.0",
    }


@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    await manager.connect(ws)
    try:
        # Send immediate snapshot on connect
        data = {"ts": time.time(), "widgets": store.snapshot()}
        await ws.send_text(json.dumps(data))

        while True:
            # Keep connection alive; broadcast loop does the pushing
            try:
                await asyncio.wait_for(ws.receive_text(), timeout=30.0)
            except asyncio.TimeoutError:
                await ws.send_text(json.dumps({"ping": True}))
    except WebSocketDisconnect:
        manager.disconnect(ws)
    except Exception:
        manager.disconnect(ws)


# ── Entry point ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("sampler_web.app:app", host="0.0.0.0", port=PORT, reload=False)
