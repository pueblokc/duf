"""
Personal Cheat Sheet Manager - FastAPI Backend
curl-compatible API at port 8505

Usage:
  curl localhost:8505/sheet/git/basics   # plain text (namespaced)
  curl localhost:8505/sheet/vim          # plain text (default namespace)
  curl -s localhost:8505/api/sheets      # JSON API
"""

import sqlite3
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Optional, List

import markdown as md
from fastapi import FastAPI, HTTPException, Request, Query
from fastapi.responses import PlainTextResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

# ── Paths ──────────────────────────────────────────────────────────────────
BASE_DIR = Path(__file__).parent
DB_PATH = BASE_DIR / "sheets.db"
STATIC_DIR = BASE_DIR / "static"

# ── App ────────────────────────────────────────────────────────────────────
app = FastAPI(
    title="Personal Cheat Sheet Manager",
    description="curl-compatible cheat sheet API with web UI",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Database ───────────────────────────────────────────────────────────────

def get_db():
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_db()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS sheets (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            name        TEXT    NOT NULL,
            namespace   TEXT    NOT NULL DEFAULT 'default',
            content     TEXT    NOT NULL DEFAULT '',
            tags        TEXT    NOT NULL DEFAULT '[]',
            description TEXT    NOT NULL DEFAULT '',
            created_at  TEXT    NOT NULL,
            updated_at  TEXT    NOT NULL,
            UNIQUE(namespace, name)
        );

        CREATE VIRTUAL TABLE IF NOT EXISTS sheets_fts
            USING fts5(name, namespace, content, tags, description,
                       content=sheets, content_rowid=id);

        CREATE TRIGGER IF NOT EXISTS sheets_ai AFTER INSERT ON sheets BEGIN
            INSERT INTO sheets_fts(rowid, name, namespace, content, tags, description)
            VALUES (new.id, new.name, new.namespace, new.content, new.tags, new.description);
        END;

        CREATE TRIGGER IF NOT EXISTS sheets_ad AFTER DELETE ON sheets BEGIN
            INSERT INTO sheets_fts(sheets_fts, rowid, name, namespace, content, tags, description)
            VALUES ('delete', old.id, old.name, old.namespace, old.content, old.tags, old.description);
        END;

        CREATE TRIGGER IF NOT EXISTS sheets_au AFTER UPDATE ON sheets BEGIN
            INSERT INTO sheets_fts(sheets_fts, rowid, name, namespace, content, tags, description)
            VALUES ('delete', old.id, old.name, old.namespace, old.content, old.tags, old.description);
            INSERT INTO sheets_fts(rowid, name, namespace, content, tags, description)
            VALUES (new.id, new.name, new.namespace, new.content, new.tags, new.description);
        END;
    """)
    conn.commit()

    # Seed sample sheets if DB is empty
    count = conn.execute("SELECT COUNT(*) FROM sheets").fetchone()[0]
    if count == 0:
        _seed_sample_sheets(conn)

    conn.close()


def _seed_sample_sheets(conn):
    now = datetime.utcnow().isoformat()
    samples = [
        {
            "name": "git-basics",
            "namespace": "git",
            "description": "Common git commands",
            "tags": json.dumps(["git", "vcs", "basics"]),
            "content": """# Git Basics

## Initialize
```bash
git init                    # init new repo
git clone <url>             # clone remote repo
git clone <url> --depth 1   # shallow clone (fast)
```

## Stage & Commit
```bash
git add .                   # stage all changes
git add -p                  # interactive stage (hunks)
git commit -m "msg"         # commit with message
git commit --amend          # amend last commit
```

## Branches
```bash
git branch                  # list local branches
git branch -a               # list all branches
git checkout -b feature/x   # create + switch branch
git switch main             # switch branch (modern)
git merge feature/x         # merge branch into current
git rebase main             # rebase current onto main
```

## Remote
```bash
git remote -v               # list remotes
git fetch origin            # fetch without merge
git pull origin main        # pull + merge
git push origin feature/x   # push branch
git push --force-with-lease # safe force push
```

## Stash
```bash
git stash                   # stash dirty state
git stash pop               # restore last stash
git stash list              # show all stashes
git stash drop stash@{0}    # delete a stash
```

## Log & Diff
```bash
git log --oneline --graph   # pretty log
git diff HEAD~1             # diff vs previous commit
git show <sha>              # show commit details
git blame <file>            # line-by-line authorship
```
""",
        },
        {
            "name": "docker",
            "namespace": "docker",
            "description": "Docker and docker-compose essentials",
            "tags": json.dumps(["docker", "containers", "devops"]),
            "content": """# Docker Cheat Sheet

## Images
```bash
docker images               # list images
docker pull nginx:latest    # pull image
docker build -t myapp .     # build from Dockerfile
docker rmi myapp            # remove image
docker image prune          # remove dangling images
```

## Containers
```bash
docker ps                   # running containers
docker ps -a                # all containers
docker run -d -p 8080:80 nginx          # run detached
docker run -it ubuntu bash              # interactive shell
docker run --rm -v $(pwd):/app node sh  # tmp container + volume
docker stop <id>            # graceful stop
docker kill <id>            # force kill
docker rm <id>              # remove container
docker logs -f <id>         # follow logs
docker exec -it <id> bash   # shell into running container
```

## Docker Compose
```bash
docker compose up -d        # start services detached
docker compose down         # stop + remove containers
docker compose down -v      # also remove volumes
docker compose logs -f      # follow all logs
docker compose ps           # service status
docker compose exec web bash # shell into service
docker compose pull         # pull latest images
```

## Cleanup
```bash
docker system prune         # remove unused resources
docker system prune -a      # include unused images
docker volume ls            # list volumes
docker volume prune         # remove unused volumes
```
""",
        },
        {
            "name": "curl",
            "namespace": "http",
            "description": "curl command examples",
            "tags": json.dumps(["curl", "http", "api", "rest"]),
            "content": """# curl Cheat Sheet

## Basic Requests
```bash
curl https://example.com                    # GET
curl -X POST https://api.example.com/data   # POST
curl -X PUT https://api.example.com/item/1  # PUT
curl -X DELETE https://api.example.com/1    # DELETE
```

## Headers & Auth
```bash
curl -H "Authorization: Bearer TOKEN" url   # auth header
curl -H "Content-Type: application/json" url
curl -u user:pass url                        # basic auth
curl -b "session=abc123" url                 # cookie
```

## POST Data
```bash
curl -d "key=value&key2=val2" url           # form data
curl -d '{"key":"value"}' \\
     -H "Content-Type: application/json" url # JSON body
curl -F "file=@/path/to/file" url           # file upload
```

## Output Control
```bash
curl -s url                 # silent (no progress)
curl -o output.html url     # save to file
curl -O url                 # save with remote filename
curl -L url                 # follow redirects
curl -v url                 # verbose (headers)
curl -I url                 # headers only
curl -w "\\n%{http_code}\\n" url  # show status code
```

## This Cheat Sheet API
```bash
curl localhost:8505/sheet/http/curl     # get this sheet
curl localhost:8505/sheet/git/git-basics
curl localhost:8505/sheet/<namespace>/<name>
```
""",
        },
        {
            "name": "python-venv",
            "namespace": "python",
            "description": "Python virtual environment commands",
            "tags": json.dumps(["python", "venv", "pip"]),
            "content": """# Python Virtual Environments

## Create & Activate
```bash
python -m venv venv              # create venv
source venv/bin/activate         # activate (Linux/Mac)
venv\\Scripts\\activate           # activate (Windows CMD)
venv\\Scripts\\Activate.ps1       # activate (Windows PS)
deactivate                       # deactivate
```

## pip
```bash
pip install requests             # install package
pip install -r requirements.txt  # install from file
pip freeze > requirements.txt    # export dependencies
pip list                         # list installed
pip show requests                # package info
pip uninstall requests           # remove package
pip install --upgrade pip        # upgrade pip itself
```

## Common Tools
```bash
pip install black isort flake8   # linting/formatting
pip install pytest pytest-cov    # testing
pip install ipython              # better REPL
pip install httpx fastapi uvicorn # web stack
```

## pyenv (version management)
```bash
pyenv install 3.12.0             # install Python version
pyenv global 3.12.0              # set global version
pyenv local 3.11.0               # set per-directory version
pyenv versions                   # list installed versions
```
""",
        },
        {
            "name": "vim",
            "namespace": "editor",
            "description": "Essential vim keybindings",
            "tags": json.dumps(["vim", "editor", "keybindings"]),
            "content": """# Vim Quick Reference

## Modes
```
i          insert mode (before cursor)
a          insert mode (after cursor)
o          new line below, insert mode
O          new line above, insert mode
ESC        back to normal mode
v          visual mode (char select)
V          visual line mode
Ctrl+v     visual block mode
```

## Navigation
```
h j k l    left down up right
w / b      next/prev word
0 / $      start/end of line
gg / G     top/bottom of file
Ctrl+d     half page down
Ctrl+u     half page up
/pattern   search forward
n / N      next/prev match
```

## Editing
```
dd         delete line
yy         yank (copy) line
p          paste after cursor
P          paste before cursor
u          undo
Ctrl+r     redo
.          repeat last command
x          delete char
r<c>       replace char with <c>
```

## File Operations
```
:w         save
:q         quit
:wq        save and quit
:q!        force quit (no save)
:e file    open file
:split     horizontal split
:vsplit    vertical split
Ctrl+w h/l switch splits
```

## Search & Replace
```
:%s/old/new/g     replace all in file
:%s/old/new/gc    replace with confirm
:10,20s/old/new/g replace in lines 10-20
```
""",
        },
    ]

    for s in samples:
        conn.execute(
            """INSERT OR IGNORE INTO sheets
               (name, namespace, content, tags, description, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (s["name"], s["namespace"], s["content"], s["tags"],
             s["description"], now, now),
        )
    conn.commit()


# ── Pydantic Models ────────────────────────────────────────────────────────

class SheetCreate(BaseModel):
    name: str
    namespace: str = "default"
    content: str = ""
    tags: List[str] = []
    description: str = ""


class SheetUpdate(BaseModel):
    name: Optional[str] = None
    namespace: Optional[str] = None
    content: Optional[str] = None
    tags: Optional[List[str]] = None
    description: Optional[str] = None


class SheetResponse(BaseModel):
    id: int
    name: str
    namespace: str
    content: str
    tags: List[str]
    description: str
    created_at: str
    updated_at: str


def row_to_dict(row) -> dict:
    d = dict(row)
    try:
        d["tags"] = json.loads(d.get("tags", "[]"))
    except Exception:
        d["tags"] = []
    return d


# ── Startup ────────────────────────────────────────────────────────────────

@app.on_event("startup")
async def startup():
    init_db()


# ── Serve UI ───────────────────────────────────────────────────────────────

app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


@app.get("/", response_class=HTMLResponse)
async def serve_ui():
    index = STATIC_DIR / "index.html"
    return HTMLResponse(index.read_text(encoding="utf-8"))


# ── REST API ───────────────────────────────────────────────────────────────

@app.get("/api/sheets")
async def list_sheets(
    namespace: Optional[str] = Query(None),
    tag: Optional[str] = Query(None),
):
    conn = get_db()
    query = "SELECT * FROM sheets WHERE 1=1"
    params = []
    if namespace:
        query += " AND namespace=?"
        params.append(namespace)
    if tag:
        query += " AND tags LIKE ?"
        params.append(f'%"{tag}"%')
    query += " ORDER BY namespace, name"
    rows = conn.execute(query, params).fetchall()
    conn.close()
    return [row_to_dict(r) for r in rows]


@app.get("/api/sheets/{sheet_id}")
async def get_sheet(sheet_id: int):
    conn = get_db()
    row = conn.execute("SELECT * FROM sheets WHERE id=?", (sheet_id,)).fetchone()
    conn.close()
    if not row:
        raise HTTPException(status_code=404, detail="Sheet not found")
    return row_to_dict(row)


@app.post("/api/sheets", status_code=201)
async def create_sheet(sheet: SheetCreate):
    now = datetime.utcnow().isoformat()
    name = re.sub(r"[^a-z0-9\-]", "-", sheet.name.lower().strip()).strip("-")
    namespace = re.sub(r"[^a-z0-9\-]", "-", sheet.namespace.lower().strip()).strip("-") or "default"

    conn = get_db()
    try:
        cur = conn.execute(
            """INSERT INTO sheets (name, namespace, content, tags, description, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (name, namespace, sheet.content, json.dumps(sheet.tags),
             sheet.description, now, now),
        )
        conn.commit()
        row = conn.execute("SELECT * FROM sheets WHERE id=?", (cur.lastrowid,)).fetchone()
        conn.close()
        return row_to_dict(row)
    except sqlite3.IntegrityError:
        conn.close()
        raise HTTPException(status_code=409, detail=f"Sheet '{namespace}/{name}' already exists")


@app.put("/api/sheets/{sheet_id}")
async def update_sheet(sheet_id: int, updates: SheetUpdate):
    now = datetime.utcnow().isoformat()
    conn = get_db()
    row = conn.execute("SELECT * FROM sheets WHERE id=?", (sheet_id,)).fetchone()
    if not row:
        conn.close()
        raise HTTPException(status_code=404, detail="Sheet not found")

    existing = row_to_dict(row)
    name = updates.name if updates.name is not None else existing["name"]
    namespace = updates.namespace if updates.namespace is not None else existing["namespace"]
    content = updates.content if updates.content is not None else existing["content"]
    tags = updates.tags if updates.tags is not None else existing["tags"]
    description = updates.description if updates.description is not None else existing["description"]

    conn.execute(
        """UPDATE sheets SET name=?, namespace=?, content=?, tags=?, description=?, updated_at=?
           WHERE id=?""",
        (name, namespace, content, json.dumps(tags), description, now, sheet_id),
    )
    conn.commit()
    row = conn.execute("SELECT * FROM sheets WHERE id=?", (sheet_id,)).fetchone()
    conn.close()
    return row_to_dict(row)


@app.delete("/api/sheets/{sheet_id}", status_code=204)
async def delete_sheet(sheet_id: int):
    conn = get_db()
    result = conn.execute("DELETE FROM sheets WHERE id=?", (sheet_id,))
    conn.commit()
    conn.close()
    if result.rowcount == 0:
        raise HTTPException(status_code=404, detail="Sheet not found")


@app.get("/api/search")
async def search_sheets(q: str = Query(..., min_length=1)):
    conn = get_db()
    try:
        rows = conn.execute(
            """SELECT s.* FROM sheets s
               JOIN sheets_fts f ON s.id = f.rowid
               WHERE sheets_fts MATCH ?
               ORDER BY rank""",
            (q,),
        ).fetchall()
    except Exception:
        rows = conn.execute(
            """SELECT * FROM sheets
               WHERE name LIKE ? OR content LIKE ? OR description LIKE ? OR tags LIKE ?
               ORDER BY name""",
            (f"%{q}%", f"%{q}%", f"%{q}%", f"%{q}%"),
        ).fetchall()
    conn.close()
    return [row_to_dict(r) for r in rows]


@app.get("/api/namespaces")
async def list_namespaces():
    conn = get_db()
    rows = conn.execute(
        "SELECT namespace, COUNT(*) as count FROM sheets GROUP BY namespace ORDER BY namespace"
    ).fetchall()
    conn.close()
    return [{"namespace": r["namespace"], "count": r["count"]} for r in rows]


@app.get("/api/tags")
async def list_tags():
    conn = get_db()
    rows = conn.execute("SELECT tags FROM sheets").fetchall()
    conn.close()
    all_tags = {}
    for row in rows:
        try:
            tags = json.loads(row["tags"])
            for t in tags:
                all_tags[t] = all_tags.get(t, 0) + 1
        except Exception:
            pass
    return [{"tag": t, "count": c} for t, c in sorted(all_tags.items())]


# ── curl-compatible sheet routes ───────────────────────────────────────────
# Mounted AFTER /api/* routes so they don't interfere.
# Pattern: /sheet/{namespace}/{name}  and  /sheet/{name}

def _is_curl(request: Request) -> bool:
    ua = request.headers.get("user-agent", "").lower()
    accept = request.headers.get("accept", "")
    return "curl" in ua or (accept in ("*/*", "") and "mozilla" not in ua.lower())


def _wrap_rendered(sheet: dict, rendered_html: str) -> str:
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>{sheet['namespace']}/{sheet['name']}</title>
<style>
  body {{ background:#0d0d0d; color:#00ff41; font-family:'Courier New',monospace; padding:2rem; max-width:900px; margin:0 auto; }}
  pre {{ background:#111; border:1px solid #1a3a1a; border-left:3px solid #005511; padding:1rem; border-radius:4px; overflow-x:auto; }}
  code {{ color:#7fff00; }}
  h1,h2,h3 {{ color:#00ff41; border-bottom:1px solid #1a3a1a; padding-bottom:.3rem; }}
  a {{ color:#00bfff; }}
  table {{ border-collapse:collapse; width:100%; }}
  th,td {{ border:1px solid #1a3a1a; padding:.4rem .8rem; text-align:left; }}
  .meta {{ color:#555; font-size:.85rem; margin-bottom:1.5rem; }}
</style>
</head>
<body>
<p class="meta">
  <a href="/">&larr; back to UI</a> &nbsp;|&nbsp;
  <strong>{sheet['namespace']}/{sheet['name']}</strong> &nbsp;|&nbsp;
  {sheet.get('description','') or ''} &nbsp;|&nbsp;
  <code>curl localhost:8505/sheet/{sheet['namespace']}/{sheet['name']}</code>
</p>
{rendered_html}
</body>
</html>"""


@app.get("/sheet/{namespace}/{name}")
async def get_sheet_curl_ns(namespace: str, name: str, request: Request):
    """curl localhost:8505/sheet/git/git-basics"""
    conn = get_db()
    row = conn.execute(
        "SELECT * FROM sheets WHERE namespace=? AND name=?",
        (namespace, name)
    ).fetchone()
    conn.close()

    if not row:
        msg = f"# Sheet not found: {namespace}/{name}\n# Create it at http://localhost:8505\n"
        if _is_curl(request):
            return PlainTextResponse(msg, status_code=404)
        raise HTTPException(status_code=404, detail=f"Sheet {namespace}/{name} not found")

    d = row_to_dict(row)
    if _is_curl(request):
        return PlainTextResponse(d["content"])
    rendered = md.markdown(d["content"], extensions=["fenced_code", "tables"])
    return HTMLResponse(_wrap_rendered(d, rendered))


@app.get("/sheet/{name}")
async def get_sheet_curl_default(name: str, request: Request):
    """curl localhost:8505/sheet/vim  — searches default namespace first"""
    conn = get_db()
    row = conn.execute(
        """SELECT * FROM sheets WHERE name=?
           ORDER BY CASE namespace WHEN 'default' THEN 0 ELSE 1 END LIMIT 1""",
        (name,)
    ).fetchone()
    conn.close()

    if not row:
        msg = f"# Sheet not found: {name}\n# Create it at http://localhost:8505\n"
        if _is_curl(request):
            return PlainTextResponse(msg, status_code=404)
        raise HTTPException(status_code=404, detail=f"Sheet {name} not found")

    d = row_to_dict(row)
    if _is_curl(request):
        return PlainTextResponse(d["content"])
    rendered = md.markdown(d["content"], extensions=["fenced_code", "tables"])
    return HTMLResponse(_wrap_rendered(d, rendered))


# ── Entrypoint ─────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app:app", host="0.0.0.0", port=8505, reload=True)
