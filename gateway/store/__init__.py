"""Storage backends. open_store() picks one from config["store_backend"]:

  sqlite  everything in one SQLite file (db_path)
  influx  hybrid: time series in InfluxDB, inventory and experiments in a
          separate SQLite file (influx.meta_db_path); see store/influx.py
"""

from __future__ import annotations

from pathlib import Path

from ..core import PACKAGE_DIR
from .db import Store


def _resolve(path: str) -> Path:
    p = Path(path)
    return p if p.is_absolute() else PACKAGE_DIR / p


def open_store(cfg: dict):
    backend = cfg.get("store_backend", "sqlite")
    if backend == "sqlite":
        return Store(_resolve(cfg["db_path"]))
    if backend == "influx":
        from .influx import InfluxStore
        ix = cfg["influx"]
        return InfluxStore(
            url=ix["url"], database=ix["database"],
            meta_db_path=_resolve(ix["meta_db_path"]),
            username=ix.get("username"), password=ix.get("password"),
            raw_retention=ix["raw_retention"],
            rollup_period=ix["rollup_period"],
            rollup_retention=ix["rollup_retention"])
    raise ValueError(f"unknown store_backend '{backend}': use sqlite or influx")
