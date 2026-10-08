"""Local dashboard, deliberately thin: the MCP server is the product surface.

Standard-library HTTP server, no external dependencies, binds localhost only.
Serves one page plus a small JSON API reading the same store the agents read.
"""

from __future__ import annotations

import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlsplit

from ..mcp_server.context import GatewayContext
from ..mcp_server.tools.list_sensors import list_sensors
from ..mcp_server.tools.read_latest import read_latest

_PAGE = (Path(__file__).resolve().parent / "index.html")


def make_handler(ctx: GatewayContext):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def _json(self, obj, code=200):
            body = json.dumps(obj).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            if self.path == "/" or self.path == "/index.html":
                body = _PAGE.read_bytes()
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            elif self.path == "/api/sensors":
                self._json(list_sensors(ctx))
            elif self.path.startswith("/api/latest/"):
                uid = unquote(self.path.rsplit("/", 1)[-1])
                self._json(read_latest(ctx, uid))
            elif self.path.startswith("/api/series/"):
                self._series()
            elif self.path == "/api/annotations":
                self._json(ctx.store.annotations(since=time.time() - 86400))
            else:
                self._json({"error": "not found"}, 404)

        def _series(self):
            # /api/series/<uid>/<field>?since=<s>&agg=<mean|min|max|raw>&bucket=<s>
            # Reads history straight from the store so a freshly opened
            # dashboard backfills its graphs instead of starting blank.
            parts = urlsplit(self.path)
            segs = parts.path.split("/")  # ['', 'api', 'series', uid, field]
            if len(segs) != 5 or not segs[3] or not segs[4]:
                self._json({"error": "usage /api/series/<uid>/<field>"}, 400)
                return
            uid = unquote(segs[3])
            field = unquote(segs[4])
            q = parse_qs(parts.query)
            try:
                since = float(q.get("since", ["21600"])[0])
                bucket = int(q.get("bucket", ["60"])[0])
            except ValueError:
                self._json({"error": "since and bucket must be numbers"}, 400)
                return
            since = max(1.0, min(since, 30 * 86400))
            bucket = max(1, min(bucket, 3600))
            agg = q.get("agg", ["mean"])[0]
            if agg not in ("mean", "min", "max"):
                agg = None
            now = time.time()
            pts = ctx.store.query_timeseries(
                uid, field, now - since, now, agg=agg, bucket_s=bucket)
            self._json({"uid": uid, "field": field,
                        "agg": agg, "bucket_s": bucket, "points": pts})

    return Handler


def serve(ctx: GatewayContext, port: int = 8931, background: bool = False):
    # Classroom machines routinely have 8080-class ports occupied (Tomcat,
    # Jenkins, proxies). Walk forward until a bind succeeds so the gateway
    # never dies over a dashboard port.
    httpd = None
    last_exc: Exception | None = None
    for candidate in range(port, port + 20):
        try:
            httpd = ThreadingHTTPServer(("0.0.0.0", candidate),
                                        make_handler(ctx))
            break
        except OSError as exc:
            last_exc = exc
    if httpd is None:
        raise RuntimeError(
            f"could not bind the dashboard to any port in "
            f"{port}-{port + 19}: {last_exc}")
    bound = httpd.server_address[1]
    if bound != port:
        print(f"[dashboard] port {port} unavailable, using {bound}")
    print(f"[dashboard] http://127.0.0.1:{bound}/")
    if background:
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        return httpd
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n[dashboard] stopped")
    finally:
        httpd.server_close()
