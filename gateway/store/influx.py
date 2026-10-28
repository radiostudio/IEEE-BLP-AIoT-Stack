"""Hybrid store: time series in InfluxDB 1.x, inventory and experiments in SQLite.

Same public methods as store.db.Store, so the pipeline, tools, dashboard and
agents do not know which backend they run on.

    InfluxDB  readings     one point per frame, retention policy "raw"
              rollups      mean/min/max/count per bucket, retention policy
                           "rollup", filled by a continuous query
              annotations  retention policy "autogen" (kept forever)
    SQLite    sensors, experiments (rows updated in place, which InfluxDB
              cannot do), in a file separate from the SQLite backend's

Standard library only: line protocol over HTTP for writes, InfluxQL over
HTTP for reads. Writes are queued and sent in batches by a background
thread so the BLE callback never waits on the network.
"""

from __future__ import annotations

import atexit
import base64
import json
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from .db import Store

RAW_RP = "raw"
ROLLUP_RP = "rollup"
JOURNAL_RP = "autogen"           # created with every database, never expires
READINGS = "readings"
ROLLUP = "readings_rollup"
ANNOTATIONS = "annotations"
CQ_NAME = "cq_rollup"
# Fields written with every frame that are bookkeeping, not measurands.
FRAME_FIELDS = ("seq", "status", "rx_time")

_DURATION = re.compile(r"^(\d+)(w|d|h|m|s)$")
_UNIT_S = {"w": 604800, "d": 86400, "h": 3600, "m": 60, "s": 1}


class InfluxUnavailable(RuntimeError):
    pass


class InfluxError(RuntimeError):
    pass


def duration_s(text: str) -> int:
    """'7d' -> 604800. Also the gate that keeps config values out of
    InfluxQL unchecked: only <number><w|d|h|m|s> passes."""
    m = _DURATION.match(text.strip())
    if not m or int(m.group(1)) == 0:
        raise ValueError(f"bad duration '{text}': use a number followed by "
                         f"w, d, h, m or s, e.g. 7d or 5m")
    return int(m.group(1)) * _UNIT_S[m.group(2)]


def _escape_key(s: str) -> str:
    # measurement names, tag keys/values and field keys
    return (str(s).replace("\\", "\\\\").replace(",", "\\,")
            .replace("=", "\\=").replace(" ", "\\ "))


def _escape_str_field(s: str) -> str:
    return '"' + str(s).replace("\\", "\\\\").replace('"', '\\"') + '"'


def _ident(s: str) -> str:
    return '"' + str(s).replace("\\", "\\\\").replace('"', '\\"') + '"'


def _literal(s: str) -> str:
    return "'" + str(s).replace("\\", "\\\\").replace("'", "\\'") + "'"


def line(measurement: str, tags: dict, fields: dict, ts_ns: int) -> str | None:
    """One line-protocol point. Numbers are always written as floats: a
    field that is int in one point and float in the next is rejected by
    InfluxDB, and card decode returns ints for scale-1 fields."""
    parts = []
    for k, v in fields.items():
        if isinstance(v, str):
            parts.append(f"{_escape_key(k)}={_escape_str_field(v)}")
            continue
        f = float(v)
        if f != f or f in (float("inf"), float("-inf")):
            continue  # line protocol has no NaN/inf
        parts.append(f"{_escape_key(k)}={f!r}")
    if not parts:
        return None
    tag_s = "".join(f",{_escape_key(k)}={_escape_key(v)}"
                    for k, v in sorted(tags.items()) if v not in (None, ""))
    return f"{_escape_key(measurement)}{tag_s} {','.join(parts)} {ts_ns}"


class InfluxStore:
    FLUSH_INTERVAL_S = 1.0
    BATCH_LINES = 5000
    MAX_QUEUED_LINES = 200_000   # ~ an hour of one kit while InfluxDB is down

    def __init__(self, url: str, database: str, meta_db_path: str | Path,
                 username: str | None = None, password: str | None = None,
                 raw_retention: str = "7d", rollup_period: str = "5m",
                 rollup_retention: str = "52w", wait_s: float = 30.0):
        self.url = url.rstrip("/")
        self.database = database
        self.raw_retention = raw_retention
        self.rollup_period = rollup_period
        self.rollup_retention = rollup_retention
        self.raw_retention_s = duration_s(raw_retention)
        self.rollup_period_s = duration_s(rollup_period)
        duration_s(rollup_retention)
        self._auth = None
        if username:
            token = base64.b64encode(f"{username}:{password or ''}".encode())
            self._auth = "Basic " + token.decode()

        self._meta = Store(meta_db_path)
        self._queue: dict[str, list[str]] = {RAW_RP: [], JOURNAL_RP: []}
        self._queue_lock = threading.Lock()
        self._flush_lock = threading.Lock()
        self._stop = threading.Event()

        self._wait_ready(wait_s)
        self._ensure_schema()

        self._thread = threading.Thread(target=self._flush_loop, daemon=True,
                                        name="influx-flush")
        self._thread.start()
        atexit.register(self.close)

    def describe(self) -> str:
        return (f"influx ({self.database} @ {self.url}), raw kept "
                f"{self.raw_retention}, rollup {self.rollup_period} kept "
                f"{self.rollup_retention}; inventory in {self._meta.db_path}")

    # -- HTTP --------------------------------------------------------------

    def _request(self, path: str, params: dict, body: bytes | None = None,
                 timeout: float = 10.0) -> bytes:
        req = urllib.request.Request(
            f"{self.url}{path}?{urllib.parse.urlencode(params)}",
            data=body, method="POST" if body is not None else "GET")
        if self._auth:
            req.add_header("Authorization", self._auth)
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.read()

    def _wait_ready(self, wait_s: float) -> None:
        deadline = time.monotonic() + wait_s
        announced = False
        while True:
            try:
                self._request("/ping", {}, timeout=3)
                return
            except (urllib.error.URLError, OSError) as exc:
                if time.monotonic() >= deadline:
                    raise InfluxUnavailable(
                        f"InfluxDB not reachable at {self.url} ({exc}). Start "
                        f"InfluxDB, or set \"store_backend\": \"sqlite\" in "
                        f"gateway/config.json") from exc
                if not announced:
                    print(f"[store] waiting for InfluxDB at {self.url} ...")
                    announced = True
                time.sleep(1)

    def query(self, q: str, write: bool = False) -> list[dict]:
        """Run InfluxQL; returns the series of the first statement."""
        params = {"db": self.database, "epoch": "ns"}
        try:
            if write:  # CREATE/ALTER/DROP must be POSTed
                raw = self._request("/query", params,
                                    urllib.parse.urlencode({"q": q}).encode())
            else:
                raw = self._request("/query", {**params, "q": q})
        except urllib.error.HTTPError as exc:
            raise InfluxError(f"{exc.code}: {exc.read().decode(errors='replace')}"
                              f" for {q}") from exc
        doc = json.loads(raw)
        if "error" in doc:
            raise InfluxError(f"{doc['error']} for {q}")
        result = (doc.get("results") or [{}])[0]
        if "error" in result:
            raise InfluxError(f"{result['error']} for {q}")
        return result.get("series", [])

    @staticmethod
    def _rows(series: list[dict]):
        for s in series:
            cols = s["columns"]
            for vals in s.get("values", []):
                yield dict(zip(cols, vals))

    # -- schema ------------------------------------------------------------

    def _ensure_schema(self) -> None:
        """Idempotent; every process runs it at startup, so editing a
        retention or the rollup period in config takes effect on restart.
        Shortening a retention deletes data older than the new limit."""
        db = _ident(self.database)
        self.query(f"CREATE DATABASE {db}", write=True)
        existing = {r["name"]: r for r in
                    self._rows(self.query(f"SHOW RETENTION POLICIES ON {db}"))}
        for rp, dur, default in ((RAW_RP, self.raw_retention, True),
                                 (ROLLUP_RP, self.rollup_retention, False)):
            verb = "ALTER" if rp in existing else "CREATE"
            repl = "" if verb == "ALTER" else " REPLICATION 1"
            self.query(f"{verb} RETENTION POLICY {_ident(rp)} ON {db} "
                       f"DURATION {dur}{repl}{' DEFAULT' if default else ''}",
                       write=True)

        select = (f"SELECT mean(*), min(*), max(*), count(*) INTO "
                  f"{db}.{_ident(ROLLUP_RP)}.{_ident(ROLLUP)} FROM "
                  f"{db}.{_ident(RAW_RP)}.{_ident(READINGS)} "
                  f"GROUP BY time({self.rollup_period}), *")
        ours = [s for s in self.query("SHOW CONTINUOUS QUERIES")
                if s.get("name") == self.database]  # one series per database
        current = [r for r in self._rows(ours) if r.get("name") == CQ_NAME]
        if current and f"time({self.rollup_period})" in current[0]["query"]:
            return
        if current:
            self.query(f"DROP CONTINUOUS QUERY {_ident(CQ_NAME)} ON {db}",
                       write=True)
        self.query(f"CREATE CONTINUOUS QUERY {_ident(CQ_NAME)} ON {db} "
                   f"BEGIN {select} END", write=True)

    # -- writes ------------------------------------------------------------

    def _enqueue(self, rp: str, lines: list[str]) -> None:
        with self._queue_lock:
            q = self._queue[rp]
            q.extend(lines)
            if len(q) > self.MAX_QUEUED_LINES:
                dropped = len(q) - self.MAX_QUEUED_LINES
                del q[:dropped]
                print(f"[store] InfluxDB backlog full, dropped {dropped} "
                      f"oldest points")

    def write_lines(self, rp: str, lines: list[str]) -> None:
        """Synchronous batch write (migration, flush). Raises InfluxError on
        a rejected batch, URLError/OSError when InfluxDB is unreachable."""
        for i in range(0, len(lines), self.BATCH_LINES):
            body = "\n".join(lines[i:i + self.BATCH_LINES]).encode()
            try:
                self._request("/write", {"db": self.database, "rp": rp,
                                         "precision": "ns"}, body, timeout=30)
            except urllib.error.HTTPError as exc:
                raise InfluxError(
                    f"{exc.code}: {exc.read().decode(errors='replace')}") from exc

    def flush(self) -> None:
        with self._flush_lock:
            for rp in (RAW_RP, JOURNAL_RP):
                with self._queue_lock:
                    batch, self._queue[rp] = self._queue[rp], []
                if not batch:
                    continue
                try:
                    self.write_lines(rp, batch)
                except InfluxError as exc:
                    # rejected data (e.g. a field type conflict) will be
                    # rejected again; drop it instead of retrying forever
                    print(f"[store] InfluxDB rejected {len(batch)} points: {exc}")
                except (urllib.error.URLError, OSError) as exc:
                    print(f"[store] InfluxDB write failed, will retry: {exc}")
                    with self._queue_lock:
                        self._queue[rp][:0] = batch

    def _flush_loop(self) -> None:
        while not self._stop.wait(self.FLUSH_INTERVAL_S):
            self.flush()

    def close(self) -> None:
        if self._stop.is_set():
            return
        self._stop.set()
        self.flush()
        self._meta.close()

    # -- ingest (Store API) ------------------------------------------------

    def upsert_sensor(self, *args, **kwargs) -> None:
        self._meta.upsert_sensor(*args, **kwargs)

    def insert_readings(self, sensor_uid: str, ts: float, rx_time: float,
                        seq: int, status: int, values: dict[str, float]) -> None:
        if not values:
            return
        kit_id, _, type_id = sensor_uid.partition(":")
        ln = line(READINGS,
                  {"sensor_uid": sensor_uid, "kit_id": kit_id,
                   "sensor_type_id": type_id},
                  {**values, "seq": seq, "status": status, "rx_time": rx_time},
                  int(ts * 1e9))
        if ln:
            self._enqueue(RAW_RP, [ln])

    # -- queries (Store API) -----------------------------------------------

    def list_sensors(self) -> list[dict]:
        return self._meta.list_sensors()

    def read_latest(self, sensor_uid: str) -> dict:
        self.flush()  # read-your-writes within this process
        q = (f"SELECT * FROM {_ident(RAW_RP)}.{_ident(READINGS)} "
             f"WHERE sensor_uid = {_literal(sensor_uid)} "
             f"ORDER BY time DESC LIMIT 1")
        out = {}
        for row in self._rows(self.query(q)):
            ts = row["time"] / 1e9
            skip = {"time", "sensor_uid", "kit_id", "sensor_type_id", *FRAME_FIELDS}
            for f, v in row.items():
                if f not in skip and v is not None:
                    out[f] = {"value": v, "ts": ts,
                              "status": int(row.get("status") or 0)}
        return out

    def query_timeseries(self, sensor_uid: str, field: str,
                         start: float, end: float,
                         agg: str | None = None, bucket_s: int = 60) -> list[dict]:
        """Raw points (or buckets) from "raw"; the part of the window older
        than the raw retention comes from the rollups, at no finer than the
        rollup period. Rollup points carry status None."""
        self.flush()
        cutoff = time.time() - self.raw_retention_s
        points: list[dict] = []
        if start < cutoff:
            points += self._query_rollup(sensor_uid, field, start,
                                         min(end, cutoff), agg, bucket_s)
        if end >= cutoff:
            points += self._query_raw(sensor_uid, field, max(start, cutoff),
                                      end, agg, bucket_s)
        return points

    def _where(self, sensor_uid: str, start: float, end: float) -> str:
        return (f"WHERE sensor_uid = {_literal(sensor_uid)} "
                f"AND time >= {int(start * 1e9)} AND time <= {int(end * 1e9)}")

    def _query_raw(self, sensor_uid, field, start, end, agg, bucket_s):
        src = f"{_ident(RAW_RP)}.{_ident(READINGS)}"
        f = _ident(field)
        where = self._where(sensor_uid, start, end)
        if agg in ("mean", "min", "max"):
            q = (f"SELECT {agg.upper()}({f}) AS value, COUNT({f}) AS n FROM {src} "
                 f"{where} GROUP BY time({int(bucket_s)}s) fill(none)")
            return [{"ts": r["time"] / 1e9, "value": r["value"], "n": r["n"]}
                    for r in self._rows(self.query(q)) if r["value"] is not None]
        q = f"SELECT {f}, status FROM {src} {where}"
        return [{"ts": r["time"] / 1e9, "value": r[field],
                 "status": int(r["status"] or 0)}
                for r in self._rows(self.query(q)) if r.get(field) is not None]

    def _query_rollup(self, sensor_uid, field, start, end, agg, bucket_s):
        src = f"{_ident(ROLLUP_RP)}.{_ident(ROLLUP)}"
        where = self._where(sensor_uid, start, end)
        mean_f, min_f, max_f, count_f = (_ident(f"{p}_{field}") for p in
                                         ("mean", "min", "max", "count"))
        if agg in ("mean", "min", "max"):
            bucket = max(int(bucket_s), self.rollup_period_s)
            fn = {"mean": f"MEAN({mean_f})", "min": f"MIN({min_f})",
                  "max": f"MAX({max_f})"}[agg]
            q = (f"SELECT {fn} AS value, SUM({count_f}) AS n FROM {src} "
                 f"{where} GROUP BY time({bucket}s) fill(none)")
            return [{"ts": r["time"] / 1e9, "value": r["value"], "n": r["n"]}
                    for r in self._rows(self.query(q)) if r["value"] is not None]
        q = f"SELECT {mean_f} AS value FROM {src} {where}"
        return [{"ts": r["time"] / 1e9, "value": r["value"], "status": None}
                for r in self._rows(self.query(q)) if r["value"] is not None]

    # -- annotations (Store API) -------------------------------------------

    def annotate(self, note: str, sensor_uid: str | None = None,
                 author: str | None = None, ts: float | None = None) -> int:
        """Returns the annotation's timestamp in ns, which serves as its id."""
        ts_ns = time.time_ns() if ts is None else int(ts * 1e9)
        ln = line(ANNOTATIONS, {"sensor_uid": sensor_uid, "author": author},
                  {"note": note}, ts_ns)
        self._enqueue(JOURNAL_RP, [ln])
        return ts_ns

    def annotations(self, since: float = 0.0) -> list[dict]:
        self.flush()
        q = (f"SELECT * FROM {_ident(JOURNAL_RP)}.{_ident(ANNOTATIONS)} "
             f"WHERE time >= {int(since * 1e9)}")
        return [{"id": r["time"], "ts": r["time"] / 1e9,
                 "sensor_uid": r.get("sensor_uid"), "author": r.get("author"),
                 "note": r.get("note")}
                for r in self._rows(self.query(q))]

    # -- experiments (Store API) -------------------------------------------

    def start_experiment(self, *args, **kwargs) -> int:
        return self._meta.start_experiment(*args, **kwargs)

    def end_experiment(self, exp_id: int) -> None:
        self._meta.end_experiment(exp_id)

    def get_experiment(self, exp_id: int) -> dict | None:
        return self._meta.get_experiment(exp_id)
