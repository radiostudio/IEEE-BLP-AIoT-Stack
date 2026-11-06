"""Continuous aggregates.

Raw rows older than `keep_raw_s` are rolled into fixed buckets and deleted.
This is what keeps a semester of continuous logging inside the eMMC write
budget on the Uno Q; on a laptop it simply keeps the database small.
"""

from __future__ import annotations

import time

from .db import Store


def downsample(store: Store, period_s: int = 300,
               keep_raw_s: int = 7 * 86400) -> dict:
    cutoff = time.time() - keep_raw_s
    with store._lock:
        conn = store._conn
        cur = conn.execute(
            """SELECT sensor_uid, mac, field,
                      CAST(ts/? AS INTEGER)*? AS bucket,
                      COUNT(*), MIN(value), MAX(value), AVG(value)
               FROM readings WHERE ts < ?
               GROUP BY sensor_uid, mac, field, bucket""",
            (period_s, period_s, cutoff))
        rows = cur.fetchall()
        for uid, mac, field, bucket, n, vmin, vmax, vmean in rows:
            conn.execute(
                """INSERT INTO aggregates (sensor_uid, mac, field, bucket, period_s,
                                           n, vmin, vmax, vmean)
                   VALUES (?,?,?,?,?,?,?,?,?)
                   ON CONFLICT(sensor_uid, mac, field, bucket, period_s) DO UPDATE SET
                     n=excluded.n, vmin=excluded.vmin,
                     vmax=excluded.vmax, vmean=excluded.vmean""",
                (uid, mac, field, bucket, period_s, n, vmin, vmax, vmean))
        deleted = conn.execute("DELETE FROM readings WHERE ts < ?", (cutoff,)).rowcount
        conn.commit()
    return {"aggregated_groups": len(rows), "raw_rows_deleted": deleted}
