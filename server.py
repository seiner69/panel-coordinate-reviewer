#!/usr/bin/env python3
from __future__ import annotations

import argparse
import io
import json
import os
import tempfile
from datetime import datetime, timezone
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlencode, urlparse

from PIL import Image


STATIC_ROOT = Path(__file__).resolve().parent / "web"
DEFAULT_PANEL_TYPES = [
    "single_panel",
    "continuous_long_panel",
    "composite_panel",
    "separator_or_text",
    "non_story",
]
STATUSES = {"pending", "approved", "rejected"}


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
        os.replace(temp_name, path)
    except BaseException:
        try:
            os.unlink(temp_name)
        except FileNotFoundError:
            pass
        raise


class Dataset:
    def __init__(self, data_dir: Path) -> None:
        self.data_dir = data_dir.resolve()
        project_path = self.data_dir / "project.json"
        project = load_json(project_path)
        if not isinstance(project, dict):
            raise ValueError("project.json must contain an object")

        self.title = str(project.get("title", "Panel coordinate review")).strip()
        self.image_path = self._resolve_local(str(project.get("stream_image", "stream.png")))
        self.candidates_path = self._resolve_local(str(project.get("candidates_file", "candidates.json")))
        self.state_path = self._resolve_local(str(project.get("state_file", "review-state.json")))
        self.context_margin = max(0, int(project.get("context_margin", 600)))

        raw_types = project.get("panel_types", DEFAULT_PANEL_TYPES)
        if not isinstance(raw_types, list) or not raw_types:
            raise ValueError("panel_types must be a non-empty list")
        self.panel_types = [str(item).strip() for item in raw_types]
        if any(not item for item in self.panel_types) or len(set(self.panel_types)) != len(self.panel_types):
            raise ValueError("panel_types must contain unique non-empty strings")

        raw_sources = project.get("sources", [])
        if not isinstance(raw_sources, list):
            raise ValueError("sources must be a list")
        self.sources = [self._normalize_source(item) for item in raw_sources]
        self.sources.sort(key=lambda item: (item["global_y0"], item["global_y1"], item["name"]))
        self.boundaries = self._build_boundaries(self.sources)

        with Image.open(self.image_path) as image:
            self.stream_width, self.stream_height = image.size
        if self.stream_width <= 0 or self.stream_height <= 0:
            raise ValueError("stream image has invalid dimensions")
        self._validate_sources()

        if self.state_path.exists():
            initial = load_json(self.state_path)
        else:
            initial = load_json(self.candidates_path)
        self.state = self.normalize_state(initial)
        if not self.state_path.exists():
            atomic_write_json(self.state_path, self.state)

    def _resolve_local(self, relative_name: str) -> Path:
        candidate = (self.data_dir / relative_name).resolve()
        if not candidate.is_relative_to(self.data_dir):
            raise ValueError(f"path escapes data directory: {relative_name}")
        return candidate

    @staticmethod
    def _normalize_source(raw: Any) -> dict[str, Any]:
        if not isinstance(raw, dict):
            raise ValueError("each source must be an object")
        name = str(raw.get("name", "")).strip()
        y0 = int(raw["global_y0"])
        y1 = int(raw["global_y1"])
        if not name or y0 < 0 or y0 >= y1:
            raise ValueError("invalid source range")
        return {"name": name, "global_y0": y0, "global_y1": y1}

    @staticmethod
    def _build_boundaries(sources: list[dict[str, Any]]) -> list[dict[str, Any]]:
        boundaries: list[dict[str, Any]] = []
        for previous, current in zip(sources, sources[1:]):
            if previous["global_y1"] == current["global_y0"]:
                boundaries.append({
                    "global_y": current["global_y0"],
                    "before": previous["name"],
                    "after": current["name"],
                })
        return boundaries

    def _validate_sources(self) -> None:
        for source in self.sources:
            if source["global_y1"] > self.stream_height:
                raise ValueError(f"source exceeds stream height: {source['name']}")

    def source_names(self, y0: int, y1: int) -> list[str]:
        return [
            source["name"]
            for source in self.sources
            if max(y0, source["global_y0"]) < min(y1, source["global_y1"])
        ]

    def normalize_state(self, payload: Any) -> dict[str, Any]:
        if isinstance(payload, list):
            items = payload
            current_index = 0
        elif isinstance(payload, dict):
            items = payload.get("items")
            current_index = int(payload.get("current_index", 0))
        else:
            raise ValueError("state must be an object or a list")
        if not isinstance(items, list) or not items:
            raise ValueError("items must be a non-empty list")

        normalized: list[dict[str, Any]] = []
        seen: set[str] = set()
        for index, raw in enumerate(items, start=1):
            if not isinstance(raw, dict):
                raise ValueError("each item must be an object")
            item = dict(raw)
            provisional_id = str(item.get("provisional_id", item.get("id", ""))).strip()
            if not provisional_id:
                provisional_id = f"panel_{index:04d}"
            if provisional_id in seen:
                raise ValueError(f"duplicate provisional_id: {provisional_id}")
            seen.add(provisional_id)

            x0, x1 = int(item["x0"]), int(item["x1"])
            y0, y1 = int(item["global_y0"]), int(item["global_y1"])
            if not (0 <= x0 < x1 <= self.stream_width and 0 <= y0 < y1 <= self.stream_height):
                raise ValueError(f"invalid bounds for {provisional_id}")
            panel_type = str(item.get("panel_type", self.panel_types[0]))
            status = str(item.get("review_status", "pending"))
            if panel_type not in self.panel_types:
                raise ValueError(f"invalid panel type for {provisional_id}")
            if status not in STATUSES:
                raise ValueError(f"invalid review status for {provisional_id}")

            names = self.source_names(y0, y1)
            normalized.append({
                "provisional_id": provisional_id,
                "order": index,
                "x0": x0,
                "x1": x1,
                "global_y0": y0,
                "global_y1": y1,
                "width": x1 - x0,
                "height": y1 - y0,
                "panel_type": panel_type,
                "cross_source": len(names) > 1,
                "source_files": names,
                "review_status": status,
                "reviewer_note": str(item.get("reviewer_note", "")),
            })

        normalized.sort(key=lambda item: (item["global_y0"], item["global_y1"], item["x0"], item["x1"]))
        for index, item in enumerate(normalized, start=1):
            item["order"] = index
        current_index = max(0, min(current_index, len(normalized) - 1))
        return {
            "schema_version": 1,
            "dataset_title": self.title,
            "coordinate_convention": "zero-based half-open",
            "stream_width": self.stream_width,
            "stream_height": self.stream_height,
            "panel_types": self.panel_types,
            "source_boundaries": self.boundaries,
            "current_index": current_index,
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "items": normalized,
        }

    def save_state(self, payload: Any) -> dict[str, Any]:
        normalized = self.normalize_state(payload)
        atomic_write_json(self.state_path, normalized)
        self.state = normalized
        return normalized

    def context_bounds(self, y0: int, y1: int) -> tuple[int, int]:
        if not (0 <= y0 < y1 <= self.stream_height):
            raise ValueError("invalid context bounds")
        return max(0, y0 - self.context_margin), min(self.stream_height, y1 + self.context_margin)

    def context_png(self, y0: int, y1: int) -> tuple[bytes, int, int]:
        context_y0, context_y1 = self.context_bounds(y0, y1)
        with Image.open(self.image_path) as source:
            crop = source.crop((0, context_y0, self.stream_width, context_y1)).convert("RGB")
            output = io.BytesIO()
            crop.save(output, "PNG", optimize=True)
        return output.getvalue(), context_y0, context_y1


class ReviewHandler(SimpleHTTPRequestHandler):
    dataset: Dataset

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, directory=str(STATIC_ROOT), **kwargs)

    def send_json(self, payload: Any, status: int = 200) -> None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/api/state":
            self.send_json(self.dataset.state)
            return
        if parsed.path in {"/api/context", "/api/context-image"}:
            try:
                query = parse_qs(parsed.query)
                y0 = int(query["y0"][0])
                y1 = int(query["y1"][0])
                if parsed.path == "/api/context":
                    context_y0, context_y1 = self.dataset.context_bounds(y0, y1)
                    image_query = urlencode({"y0": y0, "y1": y1})
                    self.send_json({
                        "url": f"/api/context-image?{image_query}",
                        "global_y0": context_y0,
                        "global_y1": context_y1,
                        "width": self.dataset.stream_width,
                        "height": context_y1 - context_y0,
                    })
                else:
                    data, _, _ = self.dataset.context_png(y0, y1)
                    self.send_response(HTTPStatus.OK)
                    self.send_header("Content-Type", "image/png")
                    self.send_header("Content-Length", str(len(data)))
                    self.send_header("Cache-Control", "no-store")
                    self.end_headers()
                    self.wfile.write(data)
            except (KeyError, IndexError, TypeError, ValueError) as exc:
                self.send_json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)
            return
        super().do_GET()

    def do_POST(self) -> None:
        if urlparse(self.path).path != "/api/state":
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if length <= 0 or length > 5_000_000:
                raise ValueError("invalid request length")
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
            self.send_json(self.dataset.save_state(payload))
        except (json.JSONDecodeError, UnicodeDecodeError, ValueError) as exc:
            self.send_json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)

    def log_message(self, fmt: str, *args: object) -> None:
        print(f"[{self.log_date_time_string()}] {fmt % args}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Local panel coordinate review server")
    parser.add_argument("--data-dir", type=Path, default=Path(__file__).resolve().parent / "example")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    dataset = Dataset(args.data_dir)
    ReviewHandler.dataset = dataset
    server = ThreadingHTTPServer(("127.0.0.1", args.port), ReviewHandler)
    print(f"Panel reviewer: http://127.0.0.1:{args.port}/")
    print(f"Dataset: {dataset.title} ({dataset.stream_width}x{dataset.stream_height})")
    server.serve_forever()


if __name__ == "__main__":
    main()
