"""Path utilities for resource access."""

import os
import sys
from pathlib import Path


def get_resource_path(relative_path: str) -> str:
    """Get absolute path to a resource, works for dev and PyInstaller.

    This function handles both development environments and packaged
    PyInstaller executables where resources are bundled in a temp directory.

    Args:
        relative_path: Path relative to the package root.

    Returns:
        Absolute path to the resource.
    """
    if getattr(sys, 'frozen', False):
        # Running in a PyInstaller bundle
        base_path = Path(sys._MEIPASS)
    else:
        # Running in normal Python environment
        base_path = Path(__file__).parent.parent.parent.parent

    return str(base_path / relative_path)


def get_package_dir() -> Path:
    """Get the eventcalendar package directory.

    Returns:
        Path to the eventcalendar package.
    """
    return Path(__file__).parent.parent


def get_project_root() -> Path:
    """Get the project root directory.

    Returns:
        Path to the project root.
    """
    return Path(__file__).parent.parent.parent.parent
