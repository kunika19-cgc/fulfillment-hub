"""store.py - shared state in one SQLite file, so every browser (office, warehouse, courier desk)
sees the same orders and stock. Without this, each browser tab would have its own private copy.

How it works: every screen refresh LOADS the world from the file; every action SAVES it back
(`app.go()` does save + rerun). A refresh of the page no longer resets anything - only the
'Reset demo' button does.

Honest limit: this saves the whole world each time (last write wins). That is fine for a team of
2-6 people on one site; a bigger system would use Postgres with row-level updates.
"""
import json
import os
import sqlite3
import tempfile
from contextlib import closing
from datetime import datetime
from pathlib import Path

import pandas as pd

TABLES = ("orders", "products", "couriers")
DATE_COLS = {"orders": ["created_at", "staged_at"]}
BOOL_COLS = {"orders": ["is_priority"]}
TEXT_COLS_WITH_BLANKS = ["courier", "slot", "picker"]


def db_path():
    """HUB_DB env var wins (tests use it). Otherwise next to the app, or the temp folder if read-only."""
    if os.environ.get("HUB_DB"):
        return Path(os.environ["HUB_DB"])
    here = Path(__file__).resolve().parent
    return here / "hub_state.db" if os.access(here, os.W_OK) else Path(tempfile.gettempdir()) / "hub_state.db"


def _connect():
    con = sqlite3.connect(db_path(), timeout=15)
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("CREATE TABLE IF NOT EXISTS kv (k TEXT PRIMARY KEY, v TEXT)")
    return con


def save(world):
    """Write the whole world in ONE transaction (readers never see a half-written state)."""
    with closing(_connect()) as con:
        con.execute("BEGIN IMMEDIATE")
        for t in TABLES:
            world[t].to_sql(t, con, if_exists="replace", index=False)
        events = {oid: {str(k): v.isoformat() for k, v in steps.items()} for oid, steps in world["events"].items()}
        kv = {
            "now": world["now"].isoformat(),
            "deliveries": world["deliveries"],
            "issues": world["issues"],
            "transfers": world["transfers"],
            "logged": sorted(list(x) for x in world["logged"]),
            "confusions": world["confusions"],
            "events": events,
        }
        con.executemany("INSERT OR REPLACE INTO kv VALUES (?, ?)", [(k, json.dumps(v)) for k, v in kv.items()])
        con.commit()


def load():
    """Return the saved world, or None if nothing has been saved yet."""
    if not db_path().exists():
        return None
    with closing(_connect()) as con:
        kv = dict(con.execute("SELECT k, v FROM kv").fetchall())
        if "now" not in kv:
            return None
        world = {}
        for t in TABLES:
            df = pd.read_sql(f"SELECT * FROM {t}", con)
            for c in DATE_COLS.get(t, []):
                df[c] = pd.to_datetime(df[c])
            for c in BOOL_COLS.get(t, []):
                df[c] = df[c].astype(bool)
            world[t] = df
    for c in TEXT_COLS_WITH_BLANKS:   # blanks come back as None, exactly like freshly generated data
        o = world["orders"]
        o[c] = o[c].astype("object").where(o[c].notna(), None)
    j = {k: json.loads(v) for k, v in kv.items()}
    world["now"] = datetime.fromisoformat(j["now"])
    world["deliveries"], world["issues"], world["transfers"] = j["deliveries"], j["issues"], j["transfers"]
    world["logged"] = {tuple(x) for x in j["logged"]}
    world["confusions"] = j.get("confusions", [])
    world["events"] = {oid: {int(k): datetime.fromisoformat(v) for k, v in steps.items()} for oid, steps in j["events"].items()}
    return world


def reset(make_world):
    """Start the demo over for everyone."""
    save(make_world())
