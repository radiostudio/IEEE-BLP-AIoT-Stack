"""SQLite timeseries store.

WAL mode with batched inserts: the write pattern that eMMC on the Uno Q can
sustain for a semester. One readings table in long format (one row per field
per frame) so every sensor, present or future, fits without schema changes.
"""

from __future__ import annotations

import json
import sqlite3
import threading
import time
from pathlib import Path

_SCHEMA = """
CREATE TABLE IF NOT EXISTS sensors (
    uid TEXT PRIMARY KEY,
    kit_id INTEGER NOT NULL,
    sensor_type_id INTEGER NOT NULL,
    schema_version INTEGER NOT NULL,
    part TEXT,
    first_seen REAL NOT NULL,
    last_seen REAL NOT NULL,
    last_status INTEGER DEFAULT 0,
    rx_count INTEGER DEFAULT 0,
    lost_count INTEGER DEFAULT 0
);
CREATE TABLE IF NOT EXISTS readings (
    id INTEGER PRIMARY KEY,
    sensor_uid TEXT NOT NULL,
    ts REAL NOT NULL,            -- reconciled time (tick-corrected), epoch seconds
    rx_time REAL NOT NULL,       -- raw arrival time, kept for the QoS lesson
    seq INTEGER NOT NULL,
    field TEXT NOT NULL,
    value REAL NOT NULL,
    status INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_readings ON readings (sensor_uid, field, ts);
CREATE TABLE IF NOT EXISTS aggregates (
    sensor_uid TEXT NOT NULL,
    field TEXT NOT NULL,
    bucket REAL NOT NULL,        -- bucket start, epoch seconds
    period_s INTEGER NOT NULL,
    n INTEGER NOT NULL,
    vmin REAL, vmax REAL, vmean REAL,
    PRIMARY KEY (sensor_uid, field, bucket, period_s)
);
CREATE TABLE IF NOT EXISTS annotations (
    id INTEGER PRIMARY KEY,
    ts REAL NOT NULL,
    sensor_uid TEXT,
    author TEXT,
    note TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS experiments (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    sensors TEXT NOT NULL,       -- JSON list of uids
    started REAL NOT NULL,
    ended REAL,
    sampling TEXT,
    notes TEXT
);
"""


class Store:
    def __init__(self, db_path: str | Path):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA synchronous=NORMAL")
        self._conn.executescript(_SCHEMA)
        self._conn.commit()

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    def describe(self) -> str:
        return f"sqlite ({self.db_path})"

    # -- ingest ------------------------------------------------------------

    def upsert_sensor(self, uid: str, kit_id: int, type_id: int, schema: int,
                      part: str | None, status: int, lost: int) -> None:
        now = time.time()
        with self._lock:
            self._conn.execute(
                """INSERT INTO sensors (uid, kit_id, sensor_type_id, schema_version,
                                        part, first_seen, last_seen, last_status,
                                        rx_count, lost_count)
                   VALUES (?,?,?,?,?,?,?,?,1,?)
                   ON CONFLICT(uid) DO UPDATE SET
                     last_seen=excluded.last_seen,
                     last_status=excluded.last_status,
                     rx_count=rx_count+1,
                     lost_count=lost_count+?""",
                (uid, kit_id, type_id, schema, part, now, now, status, lost, lost))
            self._conn.commit()

    def insert_readings(self, sensor_uid: str, ts: float, rx_time: float,
                        seq: int, status: int, values: dict[str, float]) -> None:
        rows = [(sensor_uid, ts, rx_time, seq, f, v, status)
                for f, v in values.items()]
        with self._lock:
            self._conn.executemany(
                "INSERT INTO readings (sensor_uid, ts, rx_time, seq, field, value, status)"
                " VALUES (?,?,?,?,?,?,?)", rows)
            self._conn.commit()

    # -- query -------------------------------------------------------------

    def list_sensors(self) -> list[dict]:
        with self._lock:
            cur = self._conn.execute("SELECT * FROM sensors ORDER BY uid")
            cols = [d[0] for d in cur.description]
            return [dict(zip(cols, row)) for row in cur.fetchall()]

    def read_latest(self, sensor_uid: str) -> dict:
        with self._lock:
            cur = self._conn.execute(
                """SELECT field, value, ts, status FROM readings
                   WHERE sensor_uid=? AND id IN (
                     SELECT MAX(id) FROM readings WHERE sensor_uid=? GROUP BY field)""",
                (sensor_uid, sensor_uid))
            out = {}
            for f, v, ts, status in cur.fetchall():
                out[f] = {"value": v, "ts": ts, "status": status}
            return out

    def query_timeseries(self, sensor_uid: str, field: str,
                         start: float, end: float,
                         agg: str | None = None, bucket_s: int = 60) -> list[dict]:
        with self._lock:
            if agg in ("mean", "min", "max"):
                fn = {"mean": "AVG", "min": "MIN", "max": "MAX"}[agg]
                cur = self._conn.execute(
                    f"""SELECT CAST(ts/? AS INTEGER)*? AS bucket, {fn}(value), COUNT(*)
                        FROM readings
                        WHERE sensor_uid=? AND field=? AND ts BETWEEN ? AND ?
                        GROUP BY bucket ORDER BY bucket""",
                    (bucket_s, bucket_s, sensor_uid, field, start, end))
                return [{"ts": b, "value": v, "n": n} for b, v, n in cur.fetchall()]
            cur = self._conn.execute(
                """SELECT ts, value, status FROM readings
                   WHERE sensor_uid=? AND field=? AND ts BETWEEN ? AND ?
                   ORDER BY ts""",
                (sensor_uid, field, start, end))
            return [{"ts": t, "value": v, "status": s} for t, v, s in cur.fetchall()]

    # -- annotations and experiments ---------------------------------------

    def annotate(self, note: str, sensor_uid: str | None = None,
                 author: str | None = None, ts: float | None = None) -> int:
        with self._lock:
            cur = self._conn.execute(
                "INSERT INTO annotations (ts, sensor_uid, author, note) VALUES (?,?,?,?)",
                (ts if ts is not None else time.time(), sensor_uid, author, note))
            self._conn.commit()
            return cur.lastrowid

    def annotations(self, since: float = 0.0) -> list[dict]:
        with self._lock:
            cur = self._conn.execute(
                "SELECT id, ts, sensor_uid, author, note FROM annotations"
                " WHERE ts >= ? ORDER BY ts", (since,))
            return [dict(zip(("id", "ts", "sensor_uid", "author", "note"), r))
                    for r in cur.fetchall()]

    def start_experiment(self, name: str, sensors: list[str],
                         sampling: str | None = None,
                         notes: str | None = None) -> int:
        with self._lock:
            cur = self._conn.execute(
                "INSERT INTO experiments (name, sensors, started, sampling, notes)"
                " VALUES (?,?,?,?,?)",
                (name, json.dumps(sensors), time.time(), sampling, notes))
            self._conn.commit()
            return cur.lastrowid

    def end_experiment(self, exp_id: int) -> None:
        with self._lock:
            self._conn.execute("UPDATE experiments SET ended=? WHERE id=?",
                               (time.time(), exp_id))
            self._conn.commit()

    def get_experiment(self, exp_id: int) -> dict | None:
        with self._lock:
            cur = self._conn.execute("SELECT * FROM experiments WHERE id=?", (exp_id,))
            row = cur.fetchone()
            if row is None:
                return None
            cols = [d[0] for d in cur.description]
            doc = dict(zip(cols, row))
            doc["sensors"] = json.loads(doc["sensors"])
            return doc
