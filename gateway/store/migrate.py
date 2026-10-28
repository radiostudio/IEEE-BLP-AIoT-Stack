"""One-off copy of a SQLite gateway.db into the hybrid InfluxDB store.

    python -m gateway migrate-sqlite [--source PATH] [--dry-run]

    readings     last raw_retention  -> InfluxDB "raw", one point per frame
                 all of it           -> InfluxDB "rollup" buckets, computed
                                        here (the continuous query only covers
                                        data that arrives after it exists)
    aggregates   (from `gateway downsample`) -> InfluxDB "rollup"
    annotations  -> InfluxDB journal
    sensors, experiments -> the SQLite inventory file (influx.meta_db_path)

Safe to run again: InfluxDB overwrites identical points, sensor counts are
merged only once, and experiments already copied are skipped. Run it before
the gateway starts writing to InfluxDB, so a rollup bucket is not written by
both this tool and the continuous query.
"""

from __future__ import annotations

import sqlite3
import time
from itertools import groupby
from pathlib import Path

from . import _resolve, open_store
from .influx import (ANNOTATIONS, JOURNAL_RP, RAW_RP, READINGS, ROLLUP,
                     ROLLUP_RP, InfluxError, duration_s, line)

# Stay clear of the raw retention edge: InfluxDB rejects points older than it.
_EDGE_MARGIN_S = 3600


def _tags(uid: str) -> dict:
    kit_id, _, type_id = uid.partition(":")
    return {"sensor_uid": uid, "kit_id": kit_id, "sensor_type_id": type_id}


class _Writer:
    """Batches lines per retention policy and counts what InfluxDB dropped."""

    def __init__(self, store, dry_run: bool):
        self.store, self.dry_run = store, dry_run
        self.pending: dict[str, list[str]] = {}
        self.written: dict[str, int] = {}
        self.dropped = 0

    def add(self, rp: str, ln: str | None) -> None:
        if ln is None:
            return
        self.written[rp] = self.written.get(rp, 0) + 1
        if self.dry_run:
            return
        batch = self.pending.setdefault(rp, [])
        batch.append(ln)
        if len(batch) >= self.store.BATCH_LINES:
            self.flush(rp)

    def flush(self, rp: str | None = None) -> None:
        for r in ([rp] if rp else list(self.pending)):
            batch, self.pending[r] = self.pending.get(r, []), []
            if not batch:
                continue
            try:
                self.store.write_lines(r, batch)
            except InfluxError as exc:
                # partial write: points outside the retention are dropped,
                # the rest are stored
                if "beyond retention policy" not in str(exc):
                    raise
                n = str(exc).rsplit("dropped=", 1)[-1].split("\"")[0].strip()
                self.dropped += int(n) if n.isdigit() else 0


def migrate(cfg: dict, source: str | None = None, dry_run: bool = False) -> dict:
    src_path = _resolve(source or cfg["db_path"])
    meta_path = _resolve(cfg["influx"]["meta_db_path"])
    if not src_path.exists():
        raise SystemExit(f"no SQLite database at {src_path}")
    if src_path.resolve() == Path(meta_path).resolve():
        raise SystemExit("source is the inventory file itself; pass the "
                         "SQLite backend's gateway.db with --source")

    ix = cfg["influx"]
    raw_s = duration_s(ix["raw_retention"])
    period = duration_s(ix["rollup_period"])
    src = sqlite3.connect(f"file:{src_path}?mode=ro", uri=True)
    store = None if dry_run else open_store(cfg)
    w = _Writer(store, dry_run)
    summary: dict = {"source": str(src_path), "dry_run": dry_run}

    # readings -> raw, one point per frame
    cutoff = time.time() - raw_s + _EDGE_MARGIN_S
    rows = src.execute(
        "SELECT sensor_uid, ts, seq, status, rx_time, field, value FROM readings"
        " WHERE ts >= ? ORDER BY sensor_uid, ts, seq", (cutoff,))
    for (uid, ts, seq, status, rx_time), grp in groupby(
            rows, key=lambda r: r[:5]):
        fields = {r[5]: r[6] for r in grp}
        fields.update(seq=seq, status=status, rx_time=rx_time)
        w.add(RAW_RP, line(READINGS, _tags(uid), fields, int(ts * 1e9)))
    summary["raw_points"] = w.written.get(RAW_RP, 0)

    # aggregates, then all readings -> rollup buckets. Same series and time
    # means InfluxDB merges the fields of both into one point.
    def rollup(sql: str, args: tuple = ()) -> None:
        cur = src.execute(sql, args)
        for (uid, bucket), grp in groupby(cur, key=lambda r: r[:2]):
            fields = {}
            for _, _, field, n, vmin, vmax, vmean in grp:
                fields.update({f"mean_{field}": vmean, f"min_{field}": vmin,
                               f"max_{field}": vmax, f"count_{field}": n})
            w.add(ROLLUP_RP, line(ROLLUP, _tags(uid), fields, int(bucket * 1e9)))

    rollup("SELECT sensor_uid, bucket, field, n, vmin, vmax, vmean"
           " FROM aggregates ORDER BY sensor_uid, bucket")
    rollup("SELECT sensor_uid, CAST(ts/? AS INTEGER)*? AS bucket, field,"
           " COUNT(*), MIN(value), MAX(value), AVG(value) FROM readings"
           " GROUP BY sensor_uid, bucket, field ORDER BY sensor_uid, bucket",
           (period, period))
    summary["rollup_points"] = w.written.get(ROLLUP_RP, 0)

    for ts, uid, author, note in src.execute(
            "SELECT ts, sensor_uid, author, note FROM annotations ORDER BY ts"):
        w.add(JOURNAL_RP, line(ANNOTATIONS, {"sensor_uid": uid, "author": author},
                               {"note": note}, int(ts * 1e9)))
    summary["annotations"] = w.written.get(JOURNAL_RP, 0)
    w.flush()
    summary["points_beyond_retention_dropped"] = w.dropped

    sensors = src.execute(
        "SELECT uid, kit_id, sensor_type_id, schema_version, part, first_seen,"
        " last_seen, last_status, rx_count, lost_count FROM sensors").fetchall()
    experiments = src.execute(
        "SELECT name, sensors, started, ended, sampling, notes FROM experiments"
    ).fetchall()
    summary["sensors"] = len(sensors)
    summary["experiments_copied"] = 0
    if not dry_run:
        meta = store._meta
        with meta._lock:
            # Counts are added only while the inventory row is newer than the
            # source's (disjoint periods); once merged, first_seen is the
            # older value and a re-run leaves the row alone.
            meta._conn.executemany(
                """INSERT INTO sensors (uid, kit_id, sensor_type_id, schema_version,
                                        part, first_seen, last_seen, last_status,
                                        rx_count, lost_count)
                   VALUES (?,?,?,?,?,?,?,?,?,?)
                   ON CONFLICT(uid) DO UPDATE SET
                     first_seen=excluded.first_seen,
                     rx_count=rx_count+excluded.rx_count,
                     lost_count=lost_count+excluded.lost_count
                   WHERE sensors.first_seen > excluded.last_seen""", sensors)
            for exp in experiments:
                cur = meta._conn.execute(
                    """INSERT INTO experiments (name, sensors, started, ended,
                                                sampling, notes)
                       SELECT ?,?,?,?,?,? WHERE NOT EXISTS (
                         SELECT 1 FROM experiments WHERE name=? AND started=?)""",
                    (*exp, exp[0], exp[2]))
                summary["experiments_copied"] += cur.rowcount
            meta._conn.commit()
        store.close()
    else:
        summary["experiments_copied"] = len(experiments)
    src.close()
    return summary
