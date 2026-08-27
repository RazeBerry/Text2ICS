"""Attachment values and temporary-file ownership independent of Qt widgets."""

from __future__ import annotations

import base64
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Sequence, Tuple

logger = logging.getLogger(__name__)


@dataclass
class ImageAttachmentPayload:
    """A stable attachment snapshot that can be materialized by a worker."""

    source_path: str
    mime_type: str
    temp_path: Optional[str] = None
    base64_data: Optional[str] = None

    def materialize(self, include_base64: bool = True) -> Tuple[str, str, Optional[str]]:
        """Return the upload path, MIME type, and optional compatibility base64."""
        path = self.temp_path or self.source_path
        if not path:
            raise ValueError("Image attachment is missing a file path")
        if include_base64 and self.base64_data is None:
            with open(path, "rb") as fh:
                self.base64_data = base64.b64encode(fh.read()).decode("utf-8")
        return path, self.mime_type, (self.base64_data if include_base64 else None)


class AttachmentStore:
    """Own accepted payloads and delete every managed temporary file once."""

    def __init__(self, limit: int) -> None:
        if limit < 1:
            raise ValueError("Attachment limit must be positive")
        self._limit = limit
        self._payloads: list[ImageAttachmentPayload] = []
        self._temp_paths: set[str] = set()
        self._known_sources: set[str] = set()

    @property
    def payloads(self) -> Sequence[ImageAttachmentPayload]:
        """Expose a read-only view shape; callers should snapshot before work."""
        return list(self._payloads)

    @property
    def remaining_capacity(self) -> int:
        return max(0, self._limit - len(self._payloads))

    def contains_source(self, source_path: str) -> bool:
        return source_path in self._known_sources

    def add(self, candidates: Sequence[ImageAttachmentPayload]) -> list[ImageAttachmentPayload]:
        """Adopt unique candidates up to the limit and dispose of all rejects."""
        accepted: list[ImageAttachmentPayload] = []
        for payload in candidates:
            if self.remaining_capacity <= 0 or payload.source_path in self._known_sources:
                # A caller may accidentally submit the same payload object twice.
                # Never dispose a path this store already owns.
                if payload.temp_path not in self._temp_paths:
                    self.dispose_unowned(payload)
                continue
            self._payloads.append(payload)
            self._known_sources.add(payload.source_path)
            if payload.temp_path:
                self._temp_paths.add(payload.temp_path)
            accepted.append(payload)
        return accepted

    def clear(self) -> None:
        """Release all owned paths and reset attachment identity state."""
        for temp_path in tuple(self._temp_paths):
            try:
                Path(temp_path).unlink(missing_ok=True)
            except Exception as exc:
                logger.warning("Failed to delete temp image file '%s': %s", temp_path, exc)
        self._payloads.clear()
        self._temp_paths.clear()
        self._known_sources.clear()

    @staticmethod
    def dispose_unowned(payload: ImageAttachmentPayload) -> None:
        """Delete a candidate that was never adopted by a store."""
        if not payload.temp_path:
            return
        try:
            Path(payload.temp_path).unlink(missing_ok=True)
        except Exception as exc:
            logger.warning(
                "Failed to delete rejected temp image file '%s': %s",
                payload.temp_path,
                exc,
            )
