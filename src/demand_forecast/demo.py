"""Loopback HTTP adapter for the independently usable package.

This development server is intentionally local. Use a production reverse proxy
and reviewed process supervision before adapting it to an internet-facing host.
"""
from __future__ import annotations

import json
import math
import mimetypes
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlsplit

PROJECT = "DemandForecast"
KIND = "forecast"
LIMIT = 262144
STATIC = Path(__file__).with_name("static")


def _unique(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate JSON keys are not accepted.")
        result[key] = value
    return result


def _finite_tree(value, depth=0):
    if depth > 24:
        raise ValueError("JSON nesting exceeds the supported depth.")
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError("JSON numbers must be finite.")
    if isinstance(value, dict):
        for item in value.values(): _finite_tree(item, depth + 1)
    elif isinstance(value, list):
        for item in value: _finite_tree(item, depth + 1)


def _service(results):
    if KIND == "forecast":
        from .service import ForecastService
        return ForecastService(results)
    if KIND == "vision":
        from .service import VisionService
        return VisionService(results)
    from . import service
    return service


def openapi():
    error = {"type": "object", "required": ["error", "code"], "properties": {"error": {"type": "string"}, "code": {"type": "string"}, "field": {"type": "string"}}}
    paths = {}
    gets = {"/api/health": "Local service status", "/api/evidence": "Available recorded evidence downloads"}
    if KIND == "forecast":
        gets.update({"/api/meta": "Available replay origins, selected model and source", "/api/evaluation": "Recorded final holdout metrics", "/api/diagnostics": "Hash-checked paired test MAE by month, target hour and day"})
        posts = {"/api/forecast": ("Generate 24 hourly predictions", {"origin": {"type": "string", "format": "date", "description": "Daily midnight forecast origin"}, "history": {"type": "array", "maxItems": 10000, "items": {"type": "object", "required": ["timestamp", "count"], "properties": {"timestamp": {"type": "string"}, "count": {"type": "integer", "minimum": 0, "maximum": 10000000}}, "additionalProperties": False}, "description": "Optional custom observed hours strictly before origin; does not use archive history"}}, ["origin"], {"origin": "2012-11-01"})}
    elif KIND == "vision":
        gets.update({"/api/meta": "Protocol, methods and model provenance", "/api/examples": "Actual held-out 8x8 samples", "/api/study": "All recorded experimental conditions"})
        posts = {"/api/predict": ("Assess one 8x8 digit", {"pixels": {"oneOf": [{"type": "array", "minItems": 64, "maxItems": 64, "items": {"type": "number", "minimum": 0, "maximum": 16}}, {"type": "array", "minItems": 8, "maxItems": 8, "items": {"type": "array", "minItems": 8, "maxItems": 8, "items": {"type": "number", "minimum": 0, "maximum": 16}}}]}, "method": {"type": "string", "enum": ["raw", "temperature"], "default": "temperature"}, "seed": {"type": "integer", "enum": [17, 42, 93], "default": 42}}, ["pixels"], {"pixels": [0] * 64, "method": "temperature", "seed": 42})}
    else:
        gets.update({"/api/presets": "Original editable synthetic scenarios", "/api/benchmark": "Recorded benchmark summary"})
        props = {"grid": {"type": "array", "minItems": 1, "maxItems": 128, "items": {"type": "array", "minItems": 1, "maxItems": 128, "items": {"type": "integer", "minimum": 0, "maximum": 9}}, "description": "Rectangular; 0=wall, 1..9=entry cost"}, "start": {"type": "array", "minItems": 2, "maxItems": 2, "items": {"type": "integer", "minimum": 0}}, "goal": {"type": "array", "minItems": 2, "maxItems": 2, "items": {"type": "integer", "minimum": 0}}, "trace_limit": {"type": "integer", "minimum": 0, "maximum": 2048, "default": 512}}
        sample = {"grid": [[1, 9, 9, 9, 1], [1, 1, 1, 1, 1]], "start": [0, 0], "goal": [0, 4]}
        posts = {"/api/compare": ("Compare optimal costs on the same map", props, ["grid", "start", "goal"], sample), "/api/solve": ("Solve a weighted map", dict(props, algorithm={"type": "string", "enum": ["astar", "dijkstra"], "default": "astar"}), ["grid", "start", "goal"], dict(sample, algorithm="astar"))}
    for path, summary in gets.items():
        paths[path] = {"get": {"summary": summary, "responses": {"200": {"description": "Recorded or live response", "content": {"application/json": {"schema": {"type": "object"}}}}}}}
    coordinate = {"type": "array", "minItems": 2, "maxItems": 2, "items": {"type": "integer", "minimum": 0}}
    number = {"type": "number", "minimum": 0}
    nullable_number = {"type": ["number", "null"], "minimum": 0}
    route_properties = {"algorithm": {"type": "string", "enum": ["astar", "dijkstra"]}, "reachable": {"type": "boolean"}, "cost": nullable_number, "cost_unit": {"const": "abstract_entry_cost"}, "path": {"type": "array", "items": coordinate}, "steps": {"type": ["integer", "null"], "minimum": 0}, "expanded": {"type": "integer", "minimum": 0}, "heap_peak": {"type": "integer", "minimum": 0}, "runtime_ms": number, "trace": {"type": "array", "maxItems": 2048, "items": {"type": "object", "required": ["node", "g", "h", "f"], "properties": {"node": coordinate, "g": number, "h": number, "f": number}}}, "trace_truncated": {"type": "boolean"}}
    route_response = {"type": "object", "required": list(route_properties), "properties": route_properties}
    forecast_row = {"timestamp": {"type": "string"}, "horizon": {"type": "integer", "minimum": 0, "maximum": 23}, "prediction": number, "baseline": number, "actual": nullable_number, "lag24_observed": {"type": "boolean"}, "lag168_observed": {"type": "boolean"}, "baseline_source": {"type": "string"}}
    forecast_properties = {"origin": {"type": "string"}, "horizon_hours": {"const": 24}, "kind": {"enum": ["historical_replay", "custom_history"]}, "selected_model": {"type": "string"}, "warnings": {"type": "array", "items": {"type": "string"}}, "rows": {"type": "array", "minItems": 24, "maxItems": 24, "items": {"type": "object", "required": [k for k in forecast_row if k != "baseline_source"], "properties": forecast_row}}}
    probability = {"type": "number", "minimum": 0, "maximum": 1}
    vision_properties = {"status": {"enum": ["assessed", "abstained"]}, "label": {"type": ["integer", "null"], "minimum": 0, "maximum": 7}, "predicted_label": {"type": "integer", "minimum": 0, "maximum": 7}, "probabilities": {"type": "array", "minItems": 8, "maxItems": 8, "items": probability, "description": "Probabilities in class order 0..7, summing to one"}, "confidence": probability, "threshold": probability, "method": {"enum": ["raw", "temperature"]}, "seed": {"enum": [17, 42, 93]}, "temperature": {"type": "number", "exclusiveMinimum": 0}, "protocol_sha256": {"type": "string"}, "warning": {"type": "string"}}
    for path, (summary, props, required, example) in posts.items():
        responses = {"200": {"description": "Successful calculation, including valid abstention or unreachable results", "content": {"application/json": {"schema": {"type": "object"}}}}}
        if KIND == "forecast": response_schema = {"type": "object", "required": list(forecast_properties), "properties": forecast_properties}
        elif KIND == "vision": response_schema = {"type": "object", "required": list(vision_properties), "properties": vision_properties}
        elif path == "/api/solve": response_schema = route_response
        else: response_schema = {"type": "object", "required": ["results", "costs_agree"], "properties": {"results": {"type": "array", "minItems": 2, "maxItems": 2, "items": route_response}, "costs_agree": {"const": True}}}
        responses["200"]["content"]["application/json"]["schema"] = response_schema
        for code, label in [(400, "Invalid input"), (403, "Invalid host or cross-origin request"), (413, "Body exceeds 256 KiB"), (415, "Expected application/json"), (500, "Calculation failure")]:
            responses[str(code)] = {"description": label, "content": {"application/json": {"schema": error}}}
        schema = {"type": "object", "required": required, "properties": props, "additionalProperties": False}
        paths[path] = {"post": {"summary": summary, "requestBody": {"required": True, "content": {"application/json": {"schema": schema, "example": example}}}, "responses": responses}}
    return {"openapi": "3.1.0", "info": {"title": PROJECT + " local API", "version": "0.1.1", "description": "No API key. Runs on loopback. Models and datasets are local; no paid external inference API."}, "servers": [{"url": "/"}], "paths": paths}


def make_server(results_dir: Path, port: int = 0, service=None):
    results = Path(results_dir).resolve()
    core = service if service is not None else _service(results)

    def evidence():
        return {p.name: p for p in sorted(results.glob("*")) if p.is_file() and p.suffix.lower() in {".csv", ".json", ".md", ".png"} and p.stat().st_size <= 32 * 1024 * 1024}

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.0"

        def log_message(self, *args):
            pass  # Do not log raw user requests or local data.

        def setup(self):
            super().setup()
            self.connection.settimeout(5)

        def send_bytes(self, status, body, content_type, attachment=None):
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'")
            if attachment: self.send_header("Content-Disposition", f'attachment; filename="{attachment}"')
            self.end_headers()
            if self.command != "HEAD":
                try: self.wfile.write(body)
                except (ConnectionError, TimeoutError): pass

        def json(self, status, obj):
            self.send_bytes(status, json.dumps(obj, allow_nan=False, ensure_ascii=True).encode(), "application/json; charset=utf-8")

        def error(self, status, message, code, field=None):
            payload = {"error": message, "code": code}
            if field: payload["field"] = str(field)
            self.json(status, payload)

        def same_host(self):
            allowed = {f"127.0.0.1:{self.server.server_port}", f"localhost:{self.server.server_port}"}
            host = self.headers.get("Host", "")
            origin = self.headers.get("Origin")
            if host not in allowed or (origin is not None and origin not in {"http://" + x for x in allowed}):
                self.error(403, "Only same-origin loopback requests are accepted.", "origin_forbidden")
                return False
            return True

        def do_GET(self):
            if not self.same_host(): return
            path = unquote(urlsplit(self.path).path)
            if path == "/api/health": return self.json(200, {"status": "ok", "project": PROJECT, "local_only": True})
            if path == "/openapi.json": return self.json(200, openapi())
            if path == "/api/evidence": return self.json(200, {"files": [{"name": n, "bytes": p.stat().st_size, "url": "/downloads/" + n} for n, p in evidence().items()]})
            if path.startswith("/downloads/"):
                name = path[len("/downloads/"):]
                item = evidence().get(name)
                if item:
                    return self.send_bytes(200, item.read_bytes(), mimetypes.guess_type(name)[0] or "application/octet-stream", name)
                return self.error(404, "Recorded file not found.", "not_found")
            assets = {"/": "index.html", "/static/style.css": "style.css", "/static/app.js": "app.js", "/static/evaluation.js": "evaluation.js"}
            if path in assets:
                item = STATIC / assets[path]
                if item.is_file(): return self.send_bytes(200, item.read_bytes(), mimetypes.guess_type(item.name)[0] + "; charset=utf-8")
                return self.error(404, "Application asset missing.", "not_found")
            try:
                if path == "/api/meta" and KIND != "route": return self.json(200, core.metadata())
                if path == "/api/evaluation" and KIND == "forecast": return self.json(200, core.metadata().get("metrics", {}))
                if path == "/api/diagnostics" and KIND == "forecast": return self.json(200, core.diagnostics())
                if path == "/api/examples" and KIND == "vision": return self.json(200, core.examples())
                if path == "/api/study" and KIND == "vision": return self.json(200, core.study())
                if path == "/api/presets" and KIND == "route": return self.json(200, core.presets())
                if path == "/api/benchmark" and KIND == "route":
                    for name in ("benchmark.json", "summary.json", "benchmark_summary.json"):
                        item = results / name
                        if item.is_file(): return self.json(200, json.loads(item.read_text(encoding="utf-8")))
                    return self.json(200, {"status": "not_recorded", "message": "Run route-lab benchmark --output results to record measurements."})
            except Exception:
                return self.error(500, "Recorded results could not be read. Check the local artifact and CLI output.", "artifact_error")
            self.error(404, "Endpoint not found.", "not_found")

        def do_POST(self):
            if not self.same_host(): return
            path = urlsplit(self.path).path
            allowed = {"forecast": {"/api/forecast"}, "vision": {"/api/predict"}, "route": {"/api/solve", "/api/compare"}}[KIND]
            if path not in allowed: return self.error(404, "Endpoint not found.", "not_found")
            if self.headers.get("Transfer-Encoding") is not None: return self.error(400, "Transfer encoding is not supported.", "invalid_body")
            if self.headers.get_content_type() != "application/json": return self.error(415, "Send Content-Type: application/json.", "unsupported_media_type")
            try:
                length = int(self.headers.get("Content-Length", "-1"))
                if length < 0: raise ValueError
            except ValueError: return self.error(400, "A valid Content-Length is required.", "invalid_length")
            if length > LIMIT: return self.error(413, "Request body exceeds 256 KiB.", "body_too_large")
            try:
                raw = self.rfile.read(length)
                if len(raw) != length: raise ValueError("Incomplete request body.")
                data = json.loads(raw.decode("utf-8"), object_pairs_hook=_unique, parse_constant=lambda _: (_ for _ in ()).throw(ValueError("Non-finite JSON number.")))
                if not isinstance(data, dict): raise ValueError("The request must be a JSON object.")
                _finite_tree(data)
            except (ValueError, UnicodeError, RecursionError, TimeoutError) as exc:
                return self.error(400, str(exc) if not isinstance(exc, RecursionError) else "JSON nesting is too deep.", "invalid_json")
            try:
                if KIND == "forecast":
                    if set(data) - {"origin", "history"} or not isinstance(data.get("origin"), str): raise ValueError("Expected origin and optional history.")
                    if "history" in data and not isinstance(data["history"], list): raise ValueError("Explicit history must be an array; omit the field for historical replay.")
                    output = core.forecast(data["origin"], data.get("history"))
                elif KIND == "vision":
                    if set(data) - {"pixels", "method", "seed"} or "pixels" not in data: raise ValueError("Expected pixels, optional method and seed.")
                    output = core.predict(data["pixels"], data.get("method", "temperature"), data.get("seed", 42))
                else:
                    output = core.solve(data) if path == "/api/solve" else core.compare(data)
                self.json(200, output)
            except (ValueError, TypeError, KeyError, OverflowError) as exc:
                self.error(400, str(exc), "validation_error", getattr(exc, "field", None))
            except Exception:
                self.error(500, "Calculation failed. Check the local model artifacts and recorded protocol.", "calculation_error")

        def do_HEAD(self): self.do_GET()
        def do_DELETE(self): self.error(405, "Method not allowed.", "method_not_allowed")
        do_PUT = do_PATCH = do_OPTIONS = do_DELETE

    class Server(ThreadingHTTPServer):
        daemon_threads = True
        request_queue_size = 8

        def __init__(self, *args, **kwargs):
            self.slots = threading.BoundedSemaphore(4)
            super().__init__(*args, **kwargs)

        def process_request(self, request, client_address):
            if not self.slots.acquire(blocking=False):
                try: request.sendall(b"HTTP/1.0 503 Service Unavailable\r\nContent-Length: 0\r\n\r\n")
                finally: self.shutdown_request(request)
                return
            try: super().process_request(request, client_address)
            except Exception:
                self.slots.release()
                raise

        def process_request_thread(self, request, client_address):
            try: super().process_request_thread(request, client_address)
            finally: self.slots.release()

    return Server(("127.0.0.1", port), Handler)


def serve(results_dir: Path, port: int):
    server = make_server(results_dir, port)
    print(f"{PROJECT}: http://127.0.0.1:{server.server_port} (local only)", flush=True)
    try: server.serve_forever()
    except KeyboardInterrupt: pass
    finally: server.server_close()
