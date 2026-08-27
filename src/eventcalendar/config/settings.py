"""Centralized configuration for EventCalendarGenerator."""

from dataclasses import dataclass
from typing import Tuple


@dataclass(frozen=True)
class APIConfig:
    """Configuration for API interactions."""
    model_name: str = "gemini-3.7-flash"
    # Interactive work gets one retry for a genuinely transient failure.  A
    # monotonic job deadline below prevents phase-local retries from multiplying
    # into several minutes of apparent UI hangs.
    max_retries: int = 2
    base_delay: float = 0.75
    max_backoff: float = 3.0
    request_deadline_seconds: float = 60.0
    generation_timeout_seconds: float = 45.0
    upload_timeout_seconds: float = 10.0
    cleanup_timeout_seconds: float = 3.0
    cleanup_budget_seconds: float = 6.0
    cleanup_retries: int = 2
    # Inline transient images avoid the File API's upload/create/delete round
    # trips.  12 MiB raw becomes about 16 MiB after base64 encoding, leaving
    # conservative room under generateContent's 20 MiB request limit.
    inline_image_budget_bytes: int = 12 * 1024 * 1024
    # Extraction is latency-sensitive; Gemini 3.7 defaults to medium thinking.
    thinking_level: str = "low"
    # Enough for large multi-event schedules without allowing the full 64k model
    # ceiling to turn a malformed extraction into an unbounded response.
    max_output_tokens: int = 16384


@dataclass(frozen=True)
class UIConfig:
    """Configuration for UI behavior."""
    preview_debounce_ms: int = 120
    temp_file_cleanup_delay_ms: int = 60_000
    min_window_size: Tuple[int, int] = (700, 520)
    default_window_size: Tuple[int, int] = (750, 560)
    # Kept in the public config contract; one admitted job means one worker is sufficient.
    executor_max_workers: int = 1


# Default configuration instances
API_CONFIG = APIConfig()
UI_CONFIG = UIConfig()
