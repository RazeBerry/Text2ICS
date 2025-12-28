"""Utilities for masking sensitive data."""

from typing import Optional


def mask_key(key: Optional[str]) -> str:
    """Mask an API key for safe logging.

    Args:
        key: The API key to mask.

    Returns:
        Masked key showing only first and last 4 characters.
    """
    if not key:
        return "<empty>"
    if len(key) <= 8:
        return "***"
    return f"{key[:4]}...{key[-4:]}"


# Backward compatibility alias
_mask_key = mask_key
