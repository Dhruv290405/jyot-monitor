"""Offline replay fixture loader guaranteeing zero network access."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import List, Union

from jyot_monitor.schemas import AttachmentRef, AttachmentType, ItemSchema, ProcessingStatus


class ReplayIngester:
    """Loads offline test fixtures and items for reproducible evaluations."""

    def __init__(self, fixture_dir_or_file: Union[str, Path]):
        self.target_path = Path(fixture_dir_or_file)

    def load_items(self) -> List[ItemSchema]:
        """Loads and parses items from JSON fixtures without making network requests."""
        if not self.target_path.exists():
            raise FileNotFoundError(f"Replay fixture path does not exist: {self.target_path}")

        items: List[ItemSchema] = []

        if self.target_path.is_file():
            items.extend(self._parse_file(self.target_path))
        elif self.target_path.is_dir():
            # Find all .json and .jsonl files in directory
            for json_path in sorted(self.target_path.glob("*.json")):
                items.extend(self._parse_file(json_path))
            for jsonl_path in sorted(self.target_path.glob("*.jsonl")):
                items.extend(self._parse_file(jsonl_path))

        return items

    def _parse_file(self, file_path: Path) -> List[ItemSchema]:
        """Parses a single JSON or JSONL file into ItemSchema instances."""
        items: List[ItemSchema] = []

        if file_path.suffix == ".jsonl":
            with open(file_path, "r", encoding="utf-8") as f:
                for line in f:
                    if line.strip():
                        raw = json.loads(line)
                        items.append(self._dict_to_item(raw, file_path.parent))
        else:
            with open(file_path, "r", encoding="utf-8") as f:
                raw_data = json.load(f)
                if isinstance(raw_data, list):
                    for obj in raw_data:
                        items.append(self._dict_to_item(obj, file_path.parent))
                elif isinstance(raw_data, dict):
                    # Could be list wrapped in key or single item
                    if "items" in raw_data and isinstance(raw_data["items"], list):
                        for obj in raw_data["items"]:
                            items.append(self._dict_to_item(obj, file_path.parent))
                    else:
                        items.append(self._dict_to_item(raw_data, file_path.parent))

        return items

    def _dict_to_item(self, data: dict, base_dir: Path) -> ItemSchema:
        """Converts raw fixture dict to ItemSchema, resolving local attachment paths."""
        text = data.get("text", "")
        content_hash = data.get("content_hash") or hashlib.sha256(text.encode("utf-8")).hexdigest()
        item_id = data.get("item_id") or f"replay_{content_hash[:12]}"

        # Resolve attachments relative to fixture file location if local file
        attachments: List[AttachmentRef] = []
        for att in data.get("attachments", []):
            if isinstance(att, dict):
                ref = att.get("ref", "")
                att_type_str = att.get("attachment_type", "image")
                att_type = AttachmentType.PDF if att_type_str == "pdf" else AttachmentType.IMAGE

                local_path = None
                # Check if ref is a local relative path
                candidate_path = base_dir / ref
                if candidate_path.exists():
                    local_path = str(candidate_path.resolve())
                elif Path(ref).exists():
                    local_path = str(Path(ref).resolve())

                attachments.append(
                    AttachmentRef(
                        attachment_type=att_type,
                        ref=ref,
                        mime_type=att.get("mime_type", "image/png"),
                        resolved_local_path=local_path,
                    )
                )

        return ItemSchema(
            item_id=item_id,
            source=data.get("source", "replay_fixture"),
            source_url=data.get("source_url", "https://replay.local/item"),
            published_at=data.get("published_at", "2026-10-01T00:00:00Z"),
            text=text,
            attachments=attachments,
            content_hash=content_hash,
            processing_status=ProcessingStatus.PENDING,
            trust_and_safety_flags=data.get("trust_and_safety_flags", []),
        )
