"""Base style utilities."""


def px(value: int) -> str:
    """Return a CSS pixel value.

    Args:
        value: Pixel value as integer.

    Returns:
        CSS pixel string (e.g., '16px').
    """
    return f"{value}px"
