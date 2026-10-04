"""Loopback request-boundary tests using disposable synthetic data only."""
import copy
import http.client
import json
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path

from PIL import Image

from server import Dataset, ReviewHandler


class RequestBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        Image.new("RGB", (20, 40), "white").save(root / "stream.png")
        (root / "project.json").write_text("{}", encoding="utf-8")
        (root / "candidates.json").write_text(json.dumps([{
            "provisional_id": "synthetic", "x0": 0, "x1": 20,
            "global_y0": 0, "global_y1": 40,
        }]), encoding="utf-8")
        self.dataset = Dataset(root)
        handler = type("SyntheticReviewHandler", (ReviewHandler,), {"dataset": self.dataset})
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.close_server)
        self.authority = f"127.0.0.1:{self.server.server_port}"

    def close_server(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)

    def request(self, method, path, headers, body=b""):
        connection = http.client.HTTPConnection("127.0.0.1", self.server.server_port, timeout=3)
        try:
            connection.putrequest(method, path, skip_host=True)
            for key, value in headers:
                connection.putheader(key, value)
            if body:
                connection.putheader("Content-Length", str(len(body)))
            connection.endheaders(body)
            response = connection.getresponse()
            return response.status, response.read()
        finally:
            connection.close()

    def test_host_rejects_foreign_missing_wrong_port_and_duplicates(self):
        for hosts in [[], ["untrusted.invalid"], ["localhost:0"],
                      [self.authority, self.authority], ["localhost.evil.invalid"]]:
            with self.subTest(hosts=hosts):
                status, body = self.request("GET", "/api/state", [("Host", h) for h in hosts])
                self.assertEqual(status, 403)
                self.assertNotIn(b'"items"', body)

    def test_origin_rejection_never_writes_state_or_events(self):
        before = self.dataset.state_path.read_bytes()
        payload = copy.deepcopy(self.dataset.state)
        payload["items"][0]["reviewer_note"] = "synthetic rejected edit"
        body = json.dumps(payload).encode("utf-8")
        for origins in [["https://untrusted.invalid"], ["null"],
                        ["http://localhost:0"], [f"https://{self.authority}"],
                        [f"http://{self.authority}", f"http://{self.authority}"]]:
            with self.subTest(origins=origins):
                headers = [("Host", self.authority), ("Content-Type", "text/plain")]
                headers.extend(("Origin", origin) for origin in origins)
                status, _ = self.request("POST", "/api/state", headers, body)
                self.assertEqual(status, 403)
                self.assertEqual(self.dataset.state_path.read_bytes(), before)
                self.assertFalse(self.dataset.events_path.exists())

    def test_gate_covers_static_api_image_and_head(self):
        for method, path in [("GET", "/"), ("HEAD", "/"),
                             ("GET", "/api/context-image?y0=0&y1=10"),
                             ("POST", "/api/state")]:
            for headers in [[("Host", "untrusted.invalid")],
                            [("Host", self.authority), ("Origin", "null")]]:
                with self.subTest(method=method, path=path, headers=headers):
                    status, body = self.request(method, path, headers)
                    self.assertEqual(status, 403)
                    if method == "HEAD":
                        self.assertEqual(body, b"")

    def test_loopback_same_origin_and_originless_cli_remain_usable(self):
        for host in [self.authority, f"localhost:{self.server.server_port}"]:
            headers = [("Host", host), ("Origin", f"http://{host}")]
            status, raw = self.request("GET", "/api/state", headers)
            self.assertEqual(status, 200)
            state = json.loads(raw)
            status, raw = self.request("POST", "/api/state", headers, json.dumps(state).encode())
            self.assertEqual(status, 200)
            self.assertEqual(json.loads(raw)["revision"], state["revision"] + 1)
            self.assertEqual(self.request("HEAD", "/", headers), (200, b""))
        status, _ = self.request("GET", "/api/state", [("Host", self.authority)])
        self.assertEqual(status, 200)


if __name__ == "__main__":
    unittest.main()
