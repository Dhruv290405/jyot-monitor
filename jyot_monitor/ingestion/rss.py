"""Live RSS and JSON feed ingestion with cursor tracking and error isolation."""

from __future__ import annotations

import hashlib
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import feedparser
import requests

from jyot_monitor.database import Database
from jyot_monitor.schemas import AttachmentRef, AttachmentType, ItemSchema, ProcessingStatus

logger = logging.getLogger(__name__)


class RSSIngester:
    """Fetches and normalizes RSS safety feeds into ItemSchema objects."""

    def __init__(self, db: Database, timeout_seconds: float = 8.0):
        self.db = db
        self.timeout_seconds = timeout_seconds

    def fetch_feed(self, source_config: Dict[str, Any]) -> List[ItemSchema]:
        """Fetches a feed from source configuration."""
        source_id = source_config.get("id", "unknown_source")
        url = source_config.get("url")
        if not url:
            return []

        try:
            resp = requests.get(
                url,
                timeout=self.timeout_seconds,
                headers={"User-Agent": "JyotMonitor/1.0 (+https://jyot.in)"},
            )
            if resp.status_code != 200:
                logger.warning(f"Failed to fetch feed {source_id} (HTTP {resp.status_code})")
                return []

            parsed = feedparser.parse(resp.content)
            items: List[ItemSchema] = []

            for entry in parsed.entries:
                item = self._normalize_entry(entry, source_config)
                if item and not self.db.is_item_seen(item.item_id):
                    items.append(item)

            return items

        except Exception as e:
            logger.error(f"Error ingesting feed {source_id}: {e}")
            return []

    def _normalize_entry(
        self, entry: Any, source_config: Dict[str, Any]
    ) -> Optional[ItemSchema]:
        """Normalizes a raw feedparser entry into ItemSchema."""
        title = entry.get("title", "").strip()
        summary = entry.get("summary", "").strip() or entry.get("description", "").strip()
        link = entry.get("link", "").strip()

        combined_text = f"{title}\n\n{summary}".strip()
        if not combined_text:
            return None

        # Build stable item ID and content hash
        content_hash = hashlib.sha256(combined_text.encode("utf-8")).hexdigest()
        item_id = hashlib.sha256(f"{source_config.get('id')}:{link or content_hash}".encode("utf-8")).hexdigest()[:16]

        # Timestamp
        published_at = datetime.now(timezone.utc).isoformat()
        if hasattr(entry, "published_parsed") and entry.published_parsed:
            try:
                published_at = datetime(*entry.published_parsed[:6], tzinfo=timezone.utc).isoformat()
            except Exception:
                pass

        # Extract attachments
        attachments: List[AttachmentRef] = []
        enclosures = entry.get("enclosures", [])
        for enc in enclosures:
            href = enc.get("href")
            enc_type = enc.get("type", "").lower()
            if href:
                att_type = AttachmentType.PDF if "pdf" in enc_type or href.lower().endswith(".pdf") else AttachmentType.IMAGE
                attachments.append(
                    AttachmentRef(
                        attachment_type=att_type,
                        ref=href,
                        mime_type=enc_type or ("application/pdf" if att_type == AttachmentType.PDF else "image/jpeg"),
                    )
                )

        return ItemSchema(
            item_id=f"rss_{item_id}",
            source=source_config.get("name", source_config.get("id")),
            source_url=link,
            published_at=published_at,
            text=combined_text,
            attachments=attachments,
            content_hash=content_hash,
            processing_status=ProcessingStatus.PENDING,
        )
