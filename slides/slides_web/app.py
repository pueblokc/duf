"""
slides-web: Web presentation viewer for Markdown slides.
A web serve mode for maaslalani/slides — browser presentations with
keyboard navigation, speaker notes, thumbnails, and PDF export.
"""

import json
import re
from pathlib import Path
from typing import Optional

import markdown
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

app = FastAPI(title="slides-web", version="1.0.0")

STATIC_DIR = Path(__file__).parent / "static"
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

# ---------------------------------------------------------------------------
# Demo presentation (loaded by default)
# ---------------------------------------------------------------------------

DEMO_MARKDOWN = r"""---
title: slides-web
author: KCCS
---

# slides-web

### Beautiful presentations from Markdown

*Press &rarr; to continue*

---

## Why slides-web?

- Write in **Markdown** — focus on content
- Present in the **browser** — no special software
- **Dark mode** by default
- **Keyboard driven** — arrow keys, space bar
- **Export to PDF** — one click

---

## Code Blocks

```python
def present(slides):
    for slide in slides:
        render(slide)
        wait_for_input()
```

Syntax highlighting included.

---

## Lists & Formatting

1. **Bold** for emphasis
2. *Italic* for nuance
3. `Code` for technical terms
4. ~~Strikethrough~~ for corrections

> Blockquotes work beautifully too.

---

## Tables

| Feature | Terminal | Web |
|---------|----------|-----|
| Markdown | ✓ | ✓ |
| Navigation | ✓ | ✓ |
| Speaker Notes | ✗ | ✓ |
| PDF Export | ✗ | ✓ |
| Thumbnails | ✗ | ✓ |

---

## Speaker Notes

Press **N** to toggle speaker notes.

<!-- notes: These are speaker notes! Only visible in presenter mode. Great for remembering talking points. -->

---

## Slide Thumbnails

Press **S** to toggle the sidebar.

Jump to any slide instantly.

---

## Markdown Paste Mode

Click the **paste icon** (top-right) to open the editor.

Paste your own Markdown and present instantly.

---

## Get Started

```bash
pip install fastapi uvicorn markdown
python -m uvicorn slides_web.app:app --port 8509
```

Open `http://localhost:8509`

Paste your Markdown or load a `.md` file.

---

# Thank You

**KCCS** — [kccsonline.com](https://kccsonline.com)
"""

# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------

current_markdown: str = DEMO_MARKDOWN
connected_clients: list[WebSocket] = []


# ---------------------------------------------------------------------------
# Markdown parsing helpers
# ---------------------------------------------------------------------------

def parse_frontmatter(raw: str) -> tuple[dict, str]:
    """Extract YAML-style frontmatter from the top of a markdown string."""
    fm: dict = {}
    body = raw.strip()
    if body.startswith("---"):
        parts = body.split("---", 2)
        if len(parts) >= 3:
            for line in parts[1].strip().splitlines():
                if ":" in line:
                    key, val = line.split(":", 1)
                    fm[key.strip()] = val.strip()
            body = parts[2].strip()
    return fm, body


def extract_notes(md_text: str) -> tuple[str, str]:
    """Pull speaker notes from <!-- notes: ... --> comments."""
    notes = ""
    match = re.search(r"<!--\s*notes:\s*(.*?)\s*-->", md_text, re.DOTALL)
    if match:
        notes = match.group(1).strip()
        md_text = md_text[: match.start()] + md_text[match.end() :]
    return md_text.strip(), notes


def render_markdown(md_text: str) -> str:
    """Convert markdown text to HTML."""
    return markdown.markdown(
        md_text,
        extensions=["fenced_code", "codehilite", "tables", "nl2br"],
        extension_configs={
            "codehilite": {
                "css_class": "codehilite",
                "guess_lang": True,
                "noclasses": True,
                "pygments_style": "monokai",
            }
        },
    )


def parse_slides(raw: str) -> dict:
    """Parse full markdown into structured slide data."""
    fm, body = parse_frontmatter(raw)
    raw_slides = re.split(r"\n---\n", body)
    slides = []
    for i, slide_md in enumerate(raw_slides):
        slide_md = slide_md.strip()
        if not slide_md:
            continue
        cleaned, notes = extract_notes(slide_md)
        slides.append(
            {
                "index": i,
                "markdown": cleaned,
                "html": render_markdown(cleaned),
                "notes": notes,
            }
        )
    return {"frontmatter": fm, "slides": slides, "total": len(slides)}


# ---------------------------------------------------------------------------
# API routes
# ---------------------------------------------------------------------------


class LoadRequest(BaseModel):
    content: str


@app.get("/", response_class=HTMLResponse)
async def index():
    """Serve the SPA."""
    html_path = STATIC_DIR / "index.html"
    return HTMLResponse(content=html_path.read_text(encoding="utf-8"))


@app.post("/api/load")
async def load_markdown(req: LoadRequest):
    """Load new markdown content."""
    global current_markdown
    current_markdown = req.content
    data = parse_slides(current_markdown)
    # Notify all connected WS clients
    msg = json.dumps({"type": "reload", "data": data})
    for ws in list(connected_clients):
        try:
            await ws.send_text(msg)
        except Exception:
            connected_clients.remove(ws)
    return JSONResponse(data)


@app.get("/api/slides")
async def get_slides():
    """Return parsed slides as JSON."""
    return JSONResponse(parse_slides(current_markdown))


@app.get("/api/export/pdf")
async def export_pdf():
    """PDF export placeholder — use browser print (Ctrl+P) for now."""
    return JSONResponse(
        {
            "status": "not_implemented",
            "message": "Use the browser Print dialog (Ctrl+P) with @media print styles for PDF export.",
        }
    )


# ---------------------------------------------------------------------------
# WebSocket for presenter sync
# ---------------------------------------------------------------------------


@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    await ws.accept()
    connected_clients.append(ws)
    try:
        while True:
            data = await ws.receive_text()
            msg = json.loads(data)
            # Broadcast slide navigation to all other clients
            if msg.get("type") == "navigate":
                broadcast = json.dumps(msg)
                for client in list(connected_clients):
                    if client is not ws:
                        try:
                            await client.send_text(broadcast)
                        except Exception:
                            connected_clients.remove(client)
    except WebSocketDisconnect:
        if ws in connected_clients:
            connected_clients.remove(ws)


# ---------------------------------------------------------------------------
# Run directly
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=8509)
