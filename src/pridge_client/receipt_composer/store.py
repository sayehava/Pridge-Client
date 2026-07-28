# SPDX-FileCopyrightText: 2026 Sayeh Ava Pazouki
# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileComment: Additional terms apply; see ADDITIONAL_TERMS.md.

from __future__ import annotations

import io
import json
import logging
import threading
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


logger = logging.getLogger(__name__)

DEFAULT_COUNTER_KEY = "__default__"


@dataclass
class ReceiptImage:
    id: str
    name: str
    filename: str
    width: int = 0
    height: int = 0


class ReceiptComposerStore:
    IMAGES_SUBDIR = "receipt_composer/images"
    IMAGES_INDEX = "receipt_composer/images.json"
    COUNTERS_FILE = "receipt_composer/counters.json"

    def __init__(self, config_dir: Path) -> None:
        self._images_dir = config_dir / self.IMAGES_SUBDIR
        self._images_index_path = config_dir / self.IMAGES_INDEX
        self._counters_path = config_dir / self.COUNTERS_FILE
        self._lock = threading.Lock()

    # ------------------------------------------------------------------
    # Images
    # ------------------------------------------------------------------
    def list_images(self) -> list[ReceiptImage]:
        return self._load_images_index()

    def add_image(self, name: str, data: bytes) -> ReceiptImage:
        from PIL import Image

        with Image.open(io.BytesIO(data)) as source:
            width, height = source.size
            normalized = source.convert("RGBA")
            self._images_dir.mkdir(parents=True, exist_ok=True)
            image_id = uuid.uuid4().hex
            filename = f"{image_id}.png"
            normalized.save(self._images_dir / filename, format="PNG")

        image = ReceiptImage(id=image_id, name=str(name).strip() or "Untitled", filename=filename, width=width, height=height)
        images = self._load_images_index()
        images.append(image)
        self._save_images_index(images)
        return image

    def remove_image(self, image_id: str) -> bool:
        images = self._load_images_index()
        match = next((image for image in images if image.id == image_id), None)
        if match is None:
            return False
        self._save_images_index([image for image in images if image.id != image_id])
        try:
            (self._images_dir / match.filename).unlink(missing_ok=True)
        except OSError as exc:
            logger.warning("Could not delete receipt image file %s: %s", match.filename, exc)
        return True

    def load_image_bytes(self, image_id: str) -> bytes | None:
        match = next((image for image in self._load_images_index() if image.id == image_id), None)
        if match is None:
            return None
        try:
            return (self._images_dir / match.filename).read_bytes()
        except OSError as exc:
            logger.warning("Could not read receipt image file %s: %s", match.filename, exc)
            return None

    def _load_images_index(self) -> list[ReceiptImage]:
        if not self._images_index_path.exists():
            return []
        try:
            raw = json.loads(self._images_index_path.read_text(encoding="utf-8"))
        except Exception as exc:
            logger.warning("Could not load receipt images index: %s", exc)
            return []
        if not isinstance(raw, list):
            return []
        images: list[ReceiptImage] = []
        for item in raw:
            if not isinstance(item, dict):
                continue
            image_id = str(item.get("id", "")).strip()
            filename = str(item.get("filename", "")).strip()
            if not image_id or not filename:
                continue
            images.append(
                ReceiptImage(
                    id=image_id,
                    name=str(item.get("name", "")).strip() or "Untitled",
                    filename=filename,
                    width=_safe_int(item.get("width")),
                    height=_safe_int(item.get("height")),
                )
            )
        return images

    def _save_images_index(self, images: list[ReceiptImage]) -> None:
        self._images_index_path.parent.mkdir(parents=True, exist_ok=True)
        self._images_index_path.write_text(
            json.dumps([asdict(image) for image in images], indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )

    # ------------------------------------------------------------------
    # Counters — keyed by printer_name only (a counter represents receipts
    # issued on that physical printer, not a particular server connection).
    # ------------------------------------------------------------------
    def get_counters(self, printer_name: str) -> dict[str, dict[str, Any]]:
        with self._lock:
            return dict(self._load_counters().get(printer_name, {}))

    def increment(self, printer_name: str, counter_key: str = DEFAULT_COUNTER_KEY, label: str = "") -> int:
        with self._lock:
            all_counters = self._load_counters()
            printer_counters = all_counters.setdefault(printer_name, {})
            entry = printer_counters.setdefault(counter_key, {"value": 0, "label": label or counter_key})
            entry["value"] = _safe_int(entry.get("value")) + 1
            self._save_counters(all_counters)
            return entry["value"]

    def reset(self, printer_name: str, counter_key: str = DEFAULT_COUNTER_KEY, value: int = 0) -> None:
        with self._lock:
            all_counters = self._load_counters()
            printer_counters = all_counters.setdefault(printer_name, {})
            entry = printer_counters.setdefault(counter_key, {"value": 0, "label": counter_key})
            entry["value"] = int(value)
            self._save_counters(all_counters)

    def add_named_counter(self, printer_name: str, key: str, label: str) -> None:
        key = str(key).strip()
        if not key:
            return
        with self._lock:
            all_counters = self._load_counters()
            printer_counters = all_counters.setdefault(printer_name, {})
            if key not in printer_counters:
                printer_counters[key] = {"value": 0, "label": label or key}
                self._save_counters(all_counters)

    def remove_named_counter(self, printer_name: str, key: str) -> None:
        with self._lock:
            all_counters = self._load_counters()
            printer_counters = all_counters.get(printer_name, {})
            if key in printer_counters:
                del printer_counters[key]
                self._save_counters(all_counters)

    def _load_counters(self) -> dict[str, dict[str, dict[str, Any]]]:
        if not self._counters_path.exists():
            return {}
        try:
            raw = json.loads(self._counters_path.read_text(encoding="utf-8"))
        except Exception as exc:
            logger.warning("Could not load receipt counters: %s", exc)
            return {}
        if not isinstance(raw, dict):
            return {}
        result: dict[str, dict[str, dict[str, Any]]] = {}
        for printer_name, counters in raw.items():
            if not isinstance(counters, dict):
                continue
            printer_counters: dict[str, dict[str, Any]] = {}
            for key, entry in counters.items():
                if not isinstance(entry, dict):
                    continue
                printer_counters[str(key)] = {
                    "value": _safe_int(entry.get("value")),
                    "label": str(entry.get("label", key)),
                }
            result[str(printer_name)] = printer_counters
        return result

    def _save_counters(self, all_counters: dict[str, dict[str, dict[str, Any]]]) -> None:
        self._counters_path.parent.mkdir(parents=True, exist_ok=True)
        self._counters_path.write_text(
            json.dumps(all_counters, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )


def _safe_int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0
