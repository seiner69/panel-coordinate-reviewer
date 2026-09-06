import json
import http.client
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

from PIL import Image

from server import Dataset, ReviewHandler, StateConflict


class DatasetTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        Image.new("RGB", (100, 300), "white").save(self.root / "stream.png")
        (self.root / "project.json").write_text(json.dumps({
            "title": "Test dataset",
            "stream_image": "stream.png",
            "candidates_file": "candidates.json",
            "state_file": "review-state.json",
            "context_margin": 20,
            "panel_types": ["single", "composite"],
            "sources": [
                {"name": "a", "global_y0": 0, "global_y1": 150},
                {"name": "b", "global_y0": 150, "global_y1": 300},
            ],
        }), encoding="utf-8")
        (self.root / "candidates.json").write_text(json.dumps({"items": [{
            "provisional_id": "one",
            "x0": 10,
            "x1": 90,
            "global_y0": 130,
            "global_y1": 170,
            "panel_type": "single",
        }]}), encoding="utf-8")

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_initializes_state_and_cross_source_metadata(self) -> None:
        dataset = Dataset(self.root)
        self.assertTrue((self.root / "review-state.json").is_file())
        self.assertEqual(dataset.state["revision"], 0)
        item = dataset.state["items"][0]
        self.assertEqual(item["source_files"], ["a", "b"])
        self.assertTrue(item["cross_source"])
        self.assertEqual(dataset.state["source_boundaries"][0]["global_y"], 150)

    def test_context_crop_uses_margin(self) -> None:
        dataset = Dataset(self.root)
        png, y0, y1 = dataset.context_png(130, 170)
        self.assertEqual((y0, y1), (110, 190))
        self.assertTrue(png.startswith(b"\x89PNG"))

    def test_rejects_out_of_bounds_state(self) -> None:
        dataset = Dataset(self.root)
        payload = {"items": [{
            "provisional_id": "bad",
            "x0": 0,
            "x1": 101,
            "global_y0": 0,
            "global_y1": 10,
            "panel_type": "single",
        }]}
        with self.assertRaisesRegex(ValueError, "invalid bounds"):
            dataset.normalize_state(payload)

    def test_rejects_path_escape(self) -> None:
        project = json.loads((self.root / "project.json").read_text(encoding="utf-8"))
        project["stream_image"] = "../outside.png"
        (self.root / "project.json").write_text(json.dumps(project), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "escapes data directory"):
            Dataset(self.root)

    def test_rejects_stale_full_state_save(self) -> None:
        dataset = Dataset(self.root)
        first_tab = json.loads(json.dumps(dataset.state))
        second_tab = json.loads(json.dumps(dataset.state))

        saved = dataset.save_state(first_tab)
        self.assertEqual(saved["revision"], 1)
        with self.assertRaisesRegex(StateConflict, "stale review revision"):
            dataset.save_state(second_tab)

    def test_writes_content_minimized_audit_event(self) -> None:
        dataset = Dataset(self.root)
        payload = json.loads(json.dumps(dataset.state))
        payload["items"][0]["review_status"] = "approved"
        payload["items"][0]["reviewer_note"] = "private review detail"

        dataset.save_state(payload)

        events_path = self.root / "review-events.jsonl"
        events = [json.loads(line) for line in events_path.read_text(encoding="utf-8").splitlines()]
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["revision"], 1)
        self.assertEqual(
            events[0]["changed_fields_by_item"],
            {"one": ["review_status", "reviewer_note"]},
        )
        self.assertNotIn("private review detail", events_path.read_text(encoding="utf-8"))

    def test_rejects_event_log_path_collision(self) -> None:
        project = json.loads((self.root / "project.json").read_text(encoding="utf-8"))
        project["events_file"] = "review-state.json"
        (self.root / "project.json").write_text(json.dumps(project), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "must not overwrite"):
            Dataset(self.root)

    def test_audit_failure_does_not_turn_saved_state_into_failed_request(self) -> None:
        dataset = Dataset(self.root)
        payload = json.loads(json.dumps(dataset.state))
        payload["items"][0]["review_status"] = "approved"

        with patch("server.append_json_line", side_effect=OSError("test failure")):
            saved = dataset.save_state(payload)

        self.assertEqual(saved["revision"], 1)
        persisted = json.loads((self.root / "review-state.json").read_text(encoding="utf-8"))
        self.assertEqual(persisted["revision"], 1)

    def test_http_state_and_context_image(self) -> None:
        dataset = Dataset(self.root)
        ReviewHandler.dataset = dataset
        server = ThreadingHTTPServer(("127.0.0.1", 0), ReviewHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            connection = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=5)
            connection.request("GET", "/api/state")
            response = connection.getresponse()
            state = json.loads(response.read().decode("utf-8"))
            self.assertEqual(response.status, 200)
            self.assertEqual(state["dataset_title"], "Test dataset")

            connection.request(
                "POST",
                "/api/state",
                body=json.dumps(state),
                headers={"Content-Type": "application/json"},
            )
            saved_response = connection.getresponse()
            saved = json.loads(saved_response.read().decode("utf-8"))
            self.assertEqual(saved_response.status, 200)
            self.assertEqual(saved["revision"], 1)

            connection.request(
                "POST",
                "/api/state",
                body=json.dumps(state),
                headers={"Content-Type": "application/json"},
            )
            conflict_response = connection.getresponse()
            conflict = json.loads(conflict_response.read().decode("utf-8"))
            self.assertEqual(conflict_response.status, 409)
            self.assertIn("stale review revision", conflict["error"])

            connection.request("GET", "/api/context-image?y0=130&y1=170")
            image_response = connection.getresponse()
            image_data = image_response.read()
            self.assertEqual(image_response.status, 200)
            self.assertEqual(image_response.getheader("Content-Type"), "image/png")
            self.assertTrue(image_data.startswith(b"\x89PNG"))
            connection.close()
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)


if __name__ == "__main__":
    unittest.main()
