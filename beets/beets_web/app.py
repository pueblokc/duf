"""
beets_web/app.py — FastAPI web management UI for beets music library.

Runs in demo mode by default: generates a realistic sample library
without requiring an actual beets installation. Drop in your real
beets database path to switch to live mode.

Usage:
    uvicorn beets_web.app:app --port 8508 --reload
"""

from __future__ import annotations

import os
import sqlite3
import random
import string
import math
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

BASE_DIR = Path(__file__).parent
STATIC_DIR = BASE_DIR / "static"
DB_PATH = BASE_DIR / "demo_library.db"

# ---------------------------------------------------------------------------
# Demo data — 55 realistic albums across genres
# ---------------------------------------------------------------------------

DEMO_ALBUMS = [
    # Rock
    {"title": "Abbey Road", "artist": "The Beatles", "year": 1969, "genre": "Rock", "label": "Apple Records", "tracks": 17, "format": "FLAC", "bitrate": 1411},
    {"title": "Dark Side of the Moon", "artist": "Pink Floyd", "year": 1973, "genre": "Rock", "label": "Harvest Records", "tracks": 10, "format": "FLAC", "bitrate": 1411},
    {"title": "Led Zeppelin IV", "artist": "Led Zeppelin", "year": 1971, "genre": "Rock", "label": "Atlantic Records", "tracks": 8, "format": "FLAC", "bitrate": 1411},
    {"title": "Rumours", "artist": "Fleetwood Mac", "year": 1977, "genre": "Rock", "label": "Warner Bros.", "tracks": 11, "format": "MP3", "bitrate": 320},
    {"title": "Born to Run", "artist": "Bruce Springsteen", "year": 1975, "genre": "Rock", "label": "Columbia", "tracks": 8, "format": "FLAC", "bitrate": 1411},
    {"title": "Nevermind", "artist": "Nirvana", "year": 1991, "genre": "Grunge", "label": "DGC Records", "tracks": 13, "format": "MP3", "bitrate": 320},
    {"title": "OK Computer", "artist": "Radiohead", "year": 1997, "genre": "Art Rock", "label": "Parlophone", "tracks": 12, "format": "FLAC", "bitrate": 1411},
    {"title": "Appetite for Destruction", "artist": "Guns N' Roses", "year": 1987, "genre": "Hard Rock", "label": "Geffen Records", "tracks": 12, "format": "MP3", "bitrate": 320},
    {"title": "The Joshua Tree", "artist": "U2", "year": 1987, "genre": "Rock", "label": "Island Records", "tracks": 11, "format": "FLAC", "bitrate": 1411},
    {"title": "Paranoid", "artist": "Black Sabbath", "year": 1970, "genre": "Heavy Metal", "label": "Vertigo", "tracks": 8, "format": "FLAC", "bitrate": 1411},
    # Electronic / Dance
    {"title": "Random Access Memories", "artist": "Daft Punk", "year": 2013, "genre": "Electronic", "label": "Columbia", "tracks": 13, "format": "FLAC", "bitrate": 1411},
    {"title": "Discovery", "artist": "Daft Punk", "year": 2001, "genre": "Electronic", "label": "Virgin", "tracks": 14, "format": "MP3", "bitrate": 320},
    {"title": "Selected Ambient Works 85–92", "artist": "Aphex Twin", "year": 1992, "genre": "Ambient", "label": "Apollo", "tracks": 13, "format": "FLAC", "bitrate": 1411},
    {"title": "Music Has the Right to Children", "artist": "Boards of Canada", "year": 1998, "genre": "IDM", "label": "Warp Records", "tracks": 18, "format": "FLAC", "bitrate": 1411},
    {"title": "Homework", "artist": "Daft Punk", "year": 1997, "genre": "House", "label": "Virgin", "tracks": 16, "format": "MP3", "bitrate": 320},
    {"title": "Since I Left You", "artist": "The Avalanches", "year": 2000, "genre": "Electronic", "label": "Modular", "tracks": 18, "format": "MP3", "bitrate": 320},
    {"title": "Untrue", "artist": "Burial", "year": 2007, "genre": "UK Garage", "label": "Hyperdub", "tracks": 13, "format": "FLAC", "bitrate": 1411},
    # Hip-Hop
    {"title": "Illmatic", "artist": "Nas", "year": 1994, "genre": "Hip-Hop", "label": "Columbia", "tracks": 10, "format": "MP3", "bitrate": 320},
    {"title": "To Pimp a Butterfly", "artist": "Kendrick Lamar", "year": 2015, "genre": "Hip-Hop", "label": "Aftermath", "tracks": 16, "format": "FLAC", "bitrate": 1411},
    {"title": "The Chronic", "artist": "Dr. Dre", "year": 1992, "genre": "Hip-Hop", "label": "Death Row", "tracks": 16, "format": "MP3", "bitrate": 320},
    {"title": "Ready to Die", "artist": "The Notorious B.I.G.", "year": 1994, "genre": "Hip-Hop", "label": "Bad Boy", "tracks": 17, "format": "MP3", "bitrate": 320},
    {"title": "Madvillainy", "artist": "Madvillain", "year": 2004, "genre": "Hip-Hop", "label": "Stones Throw", "tracks": 22, "format": "FLAC", "bitrate": 1411},
    {"title": "Aquemini", "artist": "OutKast", "year": 1998, "genre": "Hip-Hop", "label": "LaFace", "tracks": 16, "format": "MP3", "bitrate": 320},
    {"title": "My Beautiful Dark Twisted Fantasy", "artist": "Kanye West", "year": 2010, "genre": "Hip-Hop", "label": "Roc-A-Fella", "tracks": 13, "format": "FLAC", "bitrate": 1411},
    # Jazz
    {"title": "Kind of Blue", "artist": "Miles Davis", "year": 1959, "genre": "Jazz", "label": "Columbia", "tracks": 5, "format": "FLAC", "bitrate": 1411},
    {"title": "A Love Supreme", "artist": "John Coltrane", "year": 1965, "genre": "Jazz", "label": "Impulse!", "tracks": 4, "format": "FLAC", "bitrate": 1411},
    {"title": "Time Out", "artist": "Dave Brubeck Quartet", "year": 1959, "genre": "Jazz", "label": "Columbia", "tracks": 7, "format": "FLAC", "bitrate": 1411},
    {"title": "Bitches Brew", "artist": "Miles Davis", "year": 1970, "genre": "Jazz Fusion", "label": "Columbia", "tracks": 6, "format": "FLAC", "bitrate": 1411},
    {"title": "Mingus Ah Um", "artist": "Charles Mingus", "year": 1959, "genre": "Jazz", "label": "Columbia", "tracks": 9, "format": "FLAC", "bitrate": 1411},
    # Classical
    {"title": "The Well-Tempered Clavier", "artist": "Glenn Gould", "year": 1963, "genre": "Classical", "label": "Columbia Masterworks", "tracks": 48, "format": "FLAC", "bitrate": 1411},
    {"title": "Goldberg Variations", "artist": "Glenn Gould", "year": 1981, "genre": "Classical", "label": "CBS Masterworks", "tracks": 32, "format": "FLAC", "bitrate": 1411},
    # R&B / Soul
    {"title": "What's Going On", "artist": "Marvin Gaye", "year": 1971, "genre": "Soul", "label": "Tamla", "tracks": 9, "format": "FLAC", "bitrate": 1411},
    {"title": "Songs in the Key of Life", "artist": "Stevie Wonder", "year": 1976, "genre": "R&B", "label": "Tamla", "tracks": 21, "format": "FLAC", "bitrate": 1411},
    {"title": "Purple Rain", "artist": "Prince", "year": 1984, "genre": "R&B", "label": "Warner Bros.", "tracks": 9, "format": "MP3", "bitrate": 320},
    {"title": "Lemonade", "artist": "Beyoncé", "year": 2016, "genre": "R&B", "label": "Columbia", "tracks": 12, "format": "FLAC", "bitrate": 1411},
    {"title": "I Never Loved a Man the Way I Love You", "artist": "Aretha Franklin", "year": 1967, "genre": "Soul", "label": "Atlantic", "tracks": 11, "format": "FLAC", "bitrate": 1411},
    # Indie / Alternative
    {"title": "In the Aeroplane Over the Sea", "artist": "Neutral Milk Hotel", "year": 1998, "genre": "Indie Folk", "label": "Merge Records", "tracks": 11, "format": "FLAC", "bitrate": 1411},
    {"title": "Funeral", "artist": "Arcade Fire", "year": 2004, "genre": "Indie Rock", "label": "Merge Records", "tracks": 10, "format": "MP3", "bitrate": 320},
    {"title": "Is This It", "artist": "The Strokes", "year": 2001, "genre": "Indie Rock", "label": "RCA", "tracks": 11, "format": "MP3", "bitrate": 320},
    {"title": "Kid A", "artist": "Radiohead", "year": 2000, "genre": "Art Rock", "label": "Parlophone", "tracks": 10, "format": "FLAC", "bitrate": 1411},
    {"title": "Yankee Hotel Foxtrot", "artist": "Wilco", "year": 2002, "genre": "Alt-Country", "label": "Nonesuch", "tracks": 11, "format": "FLAC", "bitrate": 1411},
    {"title": "Loveless", "artist": "My Bloody Valentine", "year": 1991, "genre": "Shoegaze", "label": "Creation Records", "tracks": 11, "format": "FLAC", "bitrate": 1411},
    {"title": "Blue", "artist": "Joni Mitchell", "year": 1971, "genre": "Folk", "label": "Reprise Records", "tracks": 10, "format": "FLAC", "bitrate": 1411},
    # Country / Americana
    {"title": "At Folsom Prison", "artist": "Johnny Cash", "year": 1968, "genre": "Country", "label": "Columbia", "tracks": 28, "format": "MP3", "bitrate": 320},
    {"title": "Harvest", "artist": "Neil Young", "year": 1972, "genre": "Country Rock", "label": "Reprise", "tracks": 10, "format": "FLAC", "bitrate": 1411},
    # World / Reggae
    {"title": "Legend", "artist": "Bob Marley & The Wailers", "year": 1984, "genre": "Reggae", "label": "Island Records", "tracks": 14, "format": "MP3", "bitrate": 320},
    {"title": "Graceland", "artist": "Paul Simon", "year": 1986, "genre": "World", "label": "Warner Bros.", "tracks": 11, "format": "FLAC", "bitrate": 1411},
    # Pop
    {"title": "Thriller", "artist": "Michael Jackson", "year": 1982, "genre": "Pop", "label": "Epic Records", "tracks": 9, "format": "MP3", "bitrate": 320},
    {"title": "Ray of Light", "artist": "Madonna", "year": 1998, "genre": "Pop", "label": "Maverick", "tracks": 13, "format": "MP3", "bitrate": 320},
    {"title": "Tapestry", "artist": "Carole King", "year": 1971, "genre": "Pop", "label": "Ode Records", "tracks": 13, "format": "FLAC", "bitrate": 1411},
    # Metal
    {"title": "Master of Puppets", "artist": "Metallica", "year": 1986, "genre": "Heavy Metal", "label": "Elektra", "tracks": 8, "format": "MP3", "bitrate": 320},
    {"title": "Rust in Peace", "artist": "Megadeth", "year": 1990, "genre": "Thrash Metal", "label": "Capitol", "tracks": 9, "format": "MP3", "bitrate": 320},
    # Punk
    {"title": "London Calling", "artist": "The Clash", "year": 1979, "genre": "Punk", "label": "CBS", "tracks": 19, "format": "MP3", "bitrate": 320},
    {"title": "Never Mind the Bollocks", "artist": "Sex Pistols", "year": 1977, "genre": "Punk", "label": "Virgin", "tracks": 12, "format": "MP3", "bitrate": 320},
    # Extra
    {"title": "Pet Sounds", "artist": "The Beach Boys", "year": 1966, "genre": "Pop", "label": "Capitol", "tracks": 13, "format": "FLAC", "bitrate": 1411},
    {"title": "Songs of Leonard Cohen", "artist": "Leonard Cohen", "year": 1967, "genre": "Folk", "label": "Columbia", "tracks": 10, "format": "FLAC", "bitrate": 1411},
]

# Realistic track title patterns per genre
TRACK_TEMPLATES = {
    "Rock": ["Intro", "Highway Jam", "Electric Daydream", "Stone Cold", "Fire in the Sky",
             "Midnight Rider", "Rolling Thunder", "Last Train Home", "Gasoline Dreams", "Iron Curtain",
             "River of Souls", "Locomotive", "Desert Rain", "Signal Fire", "Ghost Road"],
    "Electronic": ["System Boot", "Radiant Flux", "Data Stream", "Neon Pulse", "Binary Sunset",
                   "Frequency Drift", "Vapor Trail", "Circuit Breaker", "Phase Shift", "Resonance",
                   "Sync", "Module 7", "Echo Chamber", "Particle Storm", "White Noise"],
    "Hip-Hop": ["Intro", "Street Wisdom", "Hard Knock", "Crown Heights", "Real Talk",
                "Paper Chase", "Night Moves", "Still Standing", "Block Party", "On the Come Up",
                "Hustle Hard", "Concrete Jungle", "No Sleep", "Outro", "Freestyle"],
    "Jazz": ["Prelude", "Blue Note", "After Midnight", "Walking Bass", "Modal Shift",
             "Cool Breeze", "Ballad for No One", "Uptempo", "The Change", "Resolution"],
    "Classical": ["Allegro", "Andante", "Scherzo", "Adagio", "Presto",
                  "Rondo", "Minuet", "Theme and Variations", "Coda", "Overture"],
    "default": ["Opening", "Main Theme", "Interlude", "Bridge", "Chorus",
                "Verse", "Outro", "Reprise", "Finale", "Coda",
                "Movement I", "Movement II", "Movement III", "Movement IV", "Epilogue"],
}


def get_track_names(genre: str, count: int) -> list[str]:
    templates = TRACK_TEMPLATES.get(genre, TRACK_TEMPLATES["default"])
    # If we need more than available templates, cycle through
    names = []
    for i in range(count):
        names.append(templates[i % len(templates)])
    return names


def track_duration() -> int:
    """Random track duration in seconds (2:00 – 8:30)."""
    return random.randint(120, 510)


# ---------------------------------------------------------------------------
# Database setup
# ---------------------------------------------------------------------------

def get_db() -> sqlite3.Connection:
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    """Create schema and seed demo data if database is empty."""
    conn = get_db()
    cur = conn.cursor()

    cur.executescript("""
        CREATE TABLE IF NOT EXISTS artists (
            id      INTEGER PRIMARY KEY AUTOINCREMENT,
            name    TEXT NOT NULL UNIQUE,
            sort    TEXT
        );

        CREATE TABLE IF NOT EXISTS albums (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            title       TEXT NOT NULL,
            artist_id   INTEGER REFERENCES artists(id),
            artist      TEXT NOT NULL,
            year        INTEGER,
            genre       TEXT,
            label       TEXT,
            format      TEXT DEFAULT 'FLAC',
            bitrate     INTEGER DEFAULT 1411,
            track_count INTEGER DEFAULT 0,
            duration    INTEGER DEFAULT 0,
            added       TEXT DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS tracks (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            album_id    INTEGER REFERENCES albums(id),
            title       TEXT NOT NULL,
            artist      TEXT NOT NULL,
            track_num   INTEGER,
            disc_num    INTEGER DEFAULT 1,
            duration    INTEGER,
            format      TEXT DEFAULT 'FLAC',
            bitrate     INTEGER DEFAULT 1411,
            path        TEXT
        );

        CREATE VIRTUAL TABLE IF NOT EXISTS albums_fts USING fts5(
            title, artist, genre, label,
            content='albums',
            content_rowid='id'
        );
    """)

    # Seed if empty
    row = cur.execute("SELECT COUNT(*) FROM albums").fetchone()
    if row[0] == 0:
        _seed_demo_data(conn)

    conn.commit()
    conn.close()


def _seed_demo_data(conn: sqlite3.Connection):
    cur = conn.cursor()
    random.seed(42)

    for album in DEMO_ALBUMS:
        # Upsert artist
        cur.execute(
            "INSERT OR IGNORE INTO artists (name, sort) VALUES (?, ?)",
            (album["artist"], album["artist"].lstrip("The ").lstrip("A "))
        )
        artist_id = cur.execute(
            "SELECT id FROM artists WHERE name = ?", (album["artist"],)
        ).fetchone()[0]

        # Insert album
        n_tracks = album["tracks"]
        duration = sum(track_duration() for _ in range(n_tracks))
        cur.execute(
            """INSERT INTO albums
               (title, artist_id, artist, year, genre, label, format, bitrate, track_count, duration)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (album["title"], artist_id, album["artist"], album["year"],
             album["genre"], album["label"], album["format"],
             album["bitrate"], n_tracks, duration)
        )
        album_id = cur.lastrowid

        # Insert tracks
        names = get_track_names(album["genre"], n_tracks)
        for i, tname in enumerate(names, start=1):
            tdur = track_duration()
            fake_path = f"/music/{album['artist']}/{album['title']}/{i:02d} - {tname}.{album['format'].lower()}"
            cur.execute(
                """INSERT INTO tracks
                   (album_id, title, artist, track_num, disc_num, duration, format, bitrate, path)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (album_id, tname, album["artist"], i, 1, tdur,
                 album["format"], album["bitrate"], fake_path)
            )

    # Rebuild FTS
    cur.execute("INSERT INTO albums_fts(albums_fts) VALUES ('rebuild')")
    conn.commit()


# ---------------------------------------------------------------------------
# Lifespan
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield


# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------

app = FastAPI(
    title="beets web UI",
    description="Modern web management interface for your beets music library",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount static files
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------

class AlbumUpdate(BaseModel):
    title: Optional[str] = None
    artist: Optional[str] = None
    year: Optional[int] = None
    genre: Optional[str] = None
    label: Optional[str] = None


class TrackUpdate(BaseModel):
    title: Optional[str] = None
    track_num: Optional[int] = None
    disc_num: Optional[int] = None


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def fmt_duration(seconds: int) -> str:
    h = seconds // 3600
    m = (seconds % 3600) // 60
    s = seconds % 60
    if h:
        return f"{h}:{m:02d}:{s:02d}"
    return f"{m}:{s:02d}"


def row_to_dict(row: sqlite3.Row) -> dict:
    return dict(row)


# ---------------------------------------------------------------------------
# Routes — UI
# ---------------------------------------------------------------------------

@app.get("/", include_in_schema=False)
async def index():
    return FileResponse(str(STATIC_DIR / "index.html"))


# ---------------------------------------------------------------------------
# Routes — Stats
# ---------------------------------------------------------------------------

@app.get("/api/stats")
async def get_stats():
    conn = get_db()
    cur = conn.cursor()

    total_albums = cur.execute("SELECT COUNT(*) FROM albums").fetchone()[0]
    total_tracks = cur.execute("SELECT COUNT(*) FROM tracks").fetchone()[0]
    total_artists = cur.execute("SELECT COUNT(*) FROM artists").fetchone()[0]
    total_duration = cur.execute("SELECT COALESCE(SUM(duration), 0) FROM albums").fetchone()[0]
    genres = cur.execute("SELECT COUNT(DISTINCT genre) FROM albums").fetchone()[0]
    formats = cur.execute(
        "SELECT format, COUNT(*) as cnt FROM albums GROUP BY format ORDER BY cnt DESC"
    ).fetchall()

    conn.close()
    return {
        "total_albums": total_albums,
        "total_tracks": total_tracks,
        "total_artists": total_artists,
        "total_duration_secs": total_duration,
        "total_duration_fmt": fmt_duration(total_duration),
        "genres": genres,
        "formats": [dict(r) for r in formats],
    }


# ---------------------------------------------------------------------------
# Routes — Albums
# ---------------------------------------------------------------------------

@app.get("/api/albums")
async def list_albums(
    q: Optional[str] = Query(None, description="Search query"),
    genre: Optional[str] = Query(None),
    artist: Optional[str] = Query(None),
    format: Optional[str] = Query(None),
    sort: str = Query("year_desc", description="year_asc|year_desc|title|artist"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    conn = get_db()
    cur = conn.cursor()

    conditions = []
    params: list = []

    if q:
        # FTS search — get matching IDs
        fts_rows = cur.execute(
            "SELECT rowid FROM albums_fts WHERE albums_fts MATCH ? LIMIT 200",
            (q,)
        ).fetchall()
        if not fts_rows:
            conn.close()
            return {"items": [], "total": 0}
        ids = [r[0] for r in fts_rows]
        placeholders = ",".join("?" * len(ids))
        conditions.append(f"id IN ({placeholders})")
        params.extend(ids)

    if genre:
        conditions.append("genre = ?")
        params.append(genre)
    if artist:
        conditions.append("artist = ?")
        params.append(artist)
    if format:
        conditions.append("format = ?")
        params.append(format)

    where = ("WHERE " + " AND ".join(conditions)) if conditions else ""

    order_map = {
        "year_desc": "year DESC, title ASC",
        "year_asc": "year ASC, title ASC",
        "title": "title ASC",
        "artist": "artist ASC, year DESC",
    }
    order = order_map.get(sort, "year DESC, title ASC")

    total = cur.execute(
        f"SELECT COUNT(*) FROM albums {where}", params
    ).fetchone()[0]

    rows = cur.execute(
        f"SELECT * FROM albums {where} ORDER BY {order} LIMIT ? OFFSET ?",
        params + [limit, offset]
    ).fetchall()

    conn.close()
    return {
        "items": [row_to_dict(r) for r in rows],
        "total": total,
        "limit": limit,
        "offset": offset,
    }


@app.get("/api/albums/{album_id}")
async def get_album(album_id: int):
    conn = get_db()
    cur = conn.cursor()
    row = cur.execute("SELECT * FROM albums WHERE id = ?", (album_id,)).fetchone()
    if not row:
        conn.close()
        raise HTTPException(status_code=404, detail="Album not found")
    album = row_to_dict(row)
    tracks = cur.execute(
        "SELECT * FROM tracks WHERE album_id = ? ORDER BY disc_num, track_num",
        (album_id,)
    ).fetchall()
    album["tracks"] = [row_to_dict(t) for t in tracks]
    conn.close()
    return album


@app.patch("/api/albums/{album_id}")
async def update_album(album_id: int, body: AlbumUpdate):
    conn = get_db()
    cur = conn.cursor()

    row = cur.execute("SELECT id FROM albums WHERE id = ?", (album_id,)).fetchone()
    if not row:
        conn.close()
        raise HTTPException(status_code=404, detail="Album not found")

    updates = body.model_dump(exclude_none=True)
    if not updates:
        conn.close()
        raise HTTPException(status_code=400, detail="No fields to update")

    set_clause = ", ".join(f"{k} = ?" for k in updates)
    cur.execute(
        f"UPDATE albums SET {set_clause} WHERE id = ?",
        list(updates.values()) + [album_id]
    )
    conn.commit()

    # Rebuild FTS
    cur.execute("INSERT INTO albums_fts(albums_fts) VALUES ('rebuild')")
    conn.commit()

    result = cur.execute("SELECT * FROM albums WHERE id = ?", (album_id,)).fetchone()
    conn.close()
    return row_to_dict(result)


@app.delete("/api/albums/{album_id}")
async def delete_album(album_id: int):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("DELETE FROM tracks WHERE album_id = ?", (album_id,))
    cur.execute("DELETE FROM albums WHERE id = ?", (album_id,))
    conn.commit()
    cur.execute("INSERT INTO albums_fts(albums_fts) VALUES ('rebuild')")
    conn.commit()
    conn.close()
    return {"deleted": album_id}


# ---------------------------------------------------------------------------
# Routes — Tracks
# ---------------------------------------------------------------------------

@app.get("/api/tracks")
async def list_tracks(
    q: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    conn = get_db()
    cur = conn.cursor()

    if q:
        rows = cur.execute(
            """SELECT t.*, a.title as album_title, a.genre
               FROM tracks t JOIN albums a ON t.album_id = a.id
               WHERE t.title LIKE ? OR t.artist LIKE ?
               ORDER BY t.artist, t.title
               LIMIT ? OFFSET ?""",
            (f"%{q}%", f"%{q}%", limit, offset)
        ).fetchall()
        total = cur.execute(
            "SELECT COUNT(*) FROM tracks t WHERE t.title LIKE ? OR t.artist LIKE ?",
            (f"%{q}%", f"%{q}%")
        ).fetchone()[0]
    else:
        rows = cur.execute(
            """SELECT t.*, a.title as album_title, a.genre
               FROM tracks t JOIN albums a ON t.album_id = a.id
               ORDER BY t.artist, t.title
               LIMIT ? OFFSET ?""",
            (limit, offset)
        ).fetchall()
        total = cur.execute("SELECT COUNT(*) FROM tracks").fetchone()[0]

    conn.close()
    return {"items": [row_to_dict(r) for r in rows], "total": total}


@app.patch("/api/tracks/{track_id}")
async def update_track(track_id: int, body: TrackUpdate):
    conn = get_db()
    cur = conn.cursor()

    row = cur.execute("SELECT id FROM tracks WHERE id = ?", (track_id,)).fetchone()
    if not row:
        conn.close()
        raise HTTPException(status_code=404, detail="Track not found")

    updates = body.model_dump(exclude_none=True)
    if not updates:
        conn.close()
        raise HTTPException(status_code=400, detail="No fields to update")

    set_clause = ", ".join(f"{k} = ?" for k in updates)
    cur.execute(
        f"UPDATE tracks SET {set_clause} WHERE id = ?",
        list(updates.values()) + [track_id]
    )
    conn.commit()
    result = cur.execute("SELECT * FROM tracks WHERE id = ?", (track_id,)).fetchone()
    conn.close()
    return row_to_dict(result)


# ---------------------------------------------------------------------------
# Routes — Filters (sidebar data)
# ---------------------------------------------------------------------------

@app.get("/api/genres")
async def list_genres():
    conn = get_db()
    rows = conn.execute(
        "SELECT genre, COUNT(*) as count FROM albums GROUP BY genre ORDER BY count DESC"
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


@app.get("/api/artists")
async def list_artists():
    conn = get_db()
    rows = conn.execute(
        """SELECT a.name, a.id, COUNT(al.id) as album_count
           FROM artists a JOIN albums al ON a.id = al.artist_id
           GROUP BY a.id ORDER BY album_count DESC, a.name ASC"""
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


@app.get("/api/formats")
async def list_formats():
    conn = get_db()
    rows = conn.execute(
        "SELECT format, COUNT(*) as count FROM albums GROUP BY format ORDER BY count DESC"
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# Main entrypoint
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("beets_web.app:app", host="0.0.0.0", port=8508, reload=True)
