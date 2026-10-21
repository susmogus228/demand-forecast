import json
import threading
import unittest
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.error import HTTPError
from demand_forecast.demo import make_server


class Stub:
    def metadata(self): return {"selected_model": "test", "origins": ["2012-11-01"]}
    def examples(self): return {"samples": []}
    def study(self): return {"conditions": []}
    def forecast(self, origin, history=None):
        if origin != "2012-11-01": raise ValueError("Unknown origin")
        return {"rows": [], "origin": origin}
    def predict(self, pixels, method="temperature", seed=42):
        return {"status": "abstained", "label": None, "probabilities": [0.125] * 8}
    def solve(self, payload): return {"reachable": False, "cost": None, "path": []}
    def compare(self, payload): return {"results": [], "costs_agree": True}
    def presets(self): return {"scenarios": []}


class WebTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = make_server(Path("results"), port=0, service=Stub())
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.base = f"http://127.0.0.1:{cls.server.server_port}"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join()

    def request(self, path, body=None, headers=None, method=None):
        req = Request(self.base + path, data=body, headers=headers or {}, method=method)
        try: response = urlopen(req, timeout=5)
        except HTTPError as exc: response = exc
        with response: return response.status, response.headers, response.read()

    def test_page_and_assets(self):
        status, headers, body = self.request("/")
        self.assertEqual(status, 200)
        self.assertIn(b"<html", body)
        self.assertEqual(headers["X-Content-Type-Options"], "nosniff")
        self.assertIn("default-src 'self'", headers["Content-Security-Policy"])
        self.assertEqual(self.request("/static/app.js")[0], 200)
        self.assertEqual(self.request("/static/../demo.py")[0], 404)
        self.assertEqual(self.request("/not-found")[0], 404)

    def test_health_schema_and_get(self):
        self.assertEqual(self.request("/api/health")[0], 200)
        code, _, content = self.request("/openapi.json")
        self.assertEqual(code, 200)
        self.assertEqual(json.loads(content)["openapi"], "3.1.0")
        self.assertEqual(self.request("/api/meta")[0], 200)

    def test_real_dispatch(self):
        code, _, body = self.request("/api/forecast", json.dumps({"origin": "2012-11-01"}).encode(), {"Content-Type": "application/json"})
        self.assertEqual(code, 200, body)
        self.assertIsInstance(json.loads(body), dict)

    def test_explicit_custom_history_cannot_fall_back_to_archive(self):
        for value in [None, {}, "not history"]:
            code, _, body = self.request("/api/forecast", json.dumps({"origin": "2012-11-01", "history": value}).encode(), {"Content-Type": "application/json"})
            self.assertEqual(code, 400, body)


    def test_prediction_schema_exposes_response_fields(self):
        spec = json.loads(self.request('/openapi.json')[2])
        schema = spec['paths']['/api/forecast']['post']['responses']['200']['content']['application/json']['schema']
        self.assertIn('rows', schema['properties'])

    def test_malformed_and_nonfinite_json(self):
        for body in [b"{", b"[]", b'{"x": NaN}', b'{"x":1,"x":2}', b'{' + b'"x":[' * 50 + b'0' + b']}' * 50]:
            code, _, content = self.request("/api/forecast", body, {"Content-Type": "application/json"})
            self.assertEqual(code, 400, content)
            self.assertIsInstance(json.loads(content)["error"], str)

    def test_size_media_origin_and_method(self):
        self.assertEqual(self.request("/api/forecast", b"{}", {"Content-Type": "text/plain"})[0], 415)
        self.assertEqual(self.request("/api/forecast", b"x" * 262145, {"Content-Type": "application/json"})[0], 413)
        self.assertEqual(self.request("/api/forecast", b"{}", {"Content-Type": "application/json", "Origin": "https://other.example"})[0], 403)
        self.assertEqual(self.request("/api/health", method="DELETE")[0], 405)
        self.assertEqual(self.request("/api/health", headers={"Host": "attacker.example"})[0], 403)


if __name__ == "__main__": unittest.main()
