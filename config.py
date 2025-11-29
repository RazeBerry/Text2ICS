"""Centralized configuration for EventCalendarGenerator."""

from dataclasses import dataclass
from typing import Tuple


@dataclass(frozen=True)
class APIConfig:
    """Configuration for API interactions."""
    model_name: str = "gemini-2.0-flash"
    max_retries: int = 5
    base_delay: float = 1.0
    max_backoff: float = 10.0
    timeout_seconds: float = 60.0
    max_output_tokens: int = 8192
    temperature: float = 0.0
    top_p: float = 0.3
    top_k: int = 64


@dataclass(frozen=True)
class UIConfig:
    """Configuration for UI behavior."""
    preview_debounce_ms: int = 120
    temp_file_cleanup_delay_ms: int = 60_000
    user_decision_timeout_s: int = 30
    min_window_size: Tuple[int, int] = (600, 450)
    default_window_size: Tuple[int, int] = (700, 500)
    executor_max_workers: int = 2


# Default configuration instances
API_CONFIG = APIConfig()
UI_CONFIG = UIConfig()
