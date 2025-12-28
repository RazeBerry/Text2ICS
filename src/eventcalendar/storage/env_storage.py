"""Environment file storage for API keys."""

import logging
import os
import sys
from pathlib import Path
from typing import Optional

from dotenv import dotenv_values, set_key

from eventcalendar.config.constants import PREFERRED_ENV_VAR, PRIMARY_ENV_VAR

logger = logging.getLogger(__name__)


def get_user_config_dir() -> Path:
    """Return a per-user config directory that works across platforms.

    Returns:
        Path to the user's config directory for this application.
    """
    if sys.platform.startswith("win"):
        base_str = os.environ.get("APPDATA") or os.environ.get("LOCALAPPDATA")
        base = Path(base_str) if base_str else (Path.home() / "AppData" / "Roaming")
        return base / "EventCalendarGenerator"

    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "EventCalendarGenerator"

    # Linux and other Unix-like systems
    base_str = os.environ.get("XDG_CONFIG_HOME")
    base = Path(base_str) if base_str else (Path.home() / ".config")
    return base / "EventCalendarGenerator"


def get_env_file_path() -> Path:
    """Get managed .env path under the user config directory.

    Returns:
        Path to the .env file in the user's config directory.
    """
    return get_user_config_dir() / ".env"


def get_legacy_env_path() -> Path:
    """Get backward-compatible path for older installs that stored .env beside code.

    Returns:
        Path to the legacy .env file location.
    """
    # src/eventcalendar/storage/env_storage.py -> project root/.env (when running from source checkout)
    return Path(__file__).parent.parent.parent.parent / ".env"


def get_executable_dir_env_path() -> Path:
    """Get path for .env next to the executable in frozen/packaged builds.

    In PyInstaller builds, users may place .env next to the .app or .exe.
    This ensures we check there before falling back to legacy paths.

    Returns:
        Path to .env next to the executable.
    """
    if getattr(sys, 'frozen', False):
        # Running in a PyInstaller bundle
        return Path(sys.executable).parent / ".env"
    else:
        # Not frozen - same as legacy path for development
        return get_legacy_env_path()


def harden_file_permissions(path: Path) -> None:
    """Best-effort: restrict permissions to the current user on POSIX.

    Args:
        path: Path to the file to secure.
    """
    if os.name != "posix":
        return
    try:
        path.chmod(0o600)
    except Exception as e:
        logger.warning("Could not tighten permissions on %s: %s", path, e)


def harden_directory_permissions(path: Path) -> None:
    """Best-effort: restrict directory permissions to the current user on POSIX.

    Args:
        path: Path to the directory to secure.
    """
    if os.name != "posix":
        return
    try:
        path.chmod(0o700)
    except Exception as e:
        logger.warning("Could not tighten permissions on %s: %s", path, e)


def load_from_env_file(path: Path) -> Optional[str]:
    """Load the API key from an environment file.

    Args:
        path: Path to the .env file.

    Returns:
        The API key if found, None otherwise.
    """
    if not path.exists():
        return None

    # Parse without mutating os.environ (avoids leaking secrets to child processes).
    values = dotenv_values(path)
    key = values.get(PREFERRED_ENV_VAR) or values.get(PRIMARY_ENV_VAR)
    if not key:
        return None
    return str(key).strip().strip("'\"").strip()


def store_in_env_file(api_key: str) -> None:
    """Write the API key to the per-user config .env with secure permissions.

    Args:
        api_key: The API key to store.
    """
    env_path = get_env_file_path()

    # Create parent directory with secure permissions
    env_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    harden_directory_permissions(env_path.parent)

    # Create file with secure permissions atomically
    if not env_path.exists():
        try:
            fd = os.open(str(env_path), os.O_CREAT | os.O_WRONLY | os.O_EXCL, 0o600)
            os.close(fd)
        except FileExistsError:
            pass

    if env_path.exists():
        harden_file_permissions(env_path)

    # Write both variable names for clarity; free-tier key is preferred
    set_key(str(env_path), PREFERRED_ENV_VAR, api_key)
    set_key(str(env_path), PRIMARY_ENV_VAR, api_key)

    if env_path.exists():
        harden_file_permissions(env_path)


# Backward compatibility aliases
_harden_file_permissions = harden_file_permissions
_harden_directory_permissions = harden_directory_permissions
_load_from_env_file = load_from_env_file
_store_in_env_file = store_in_env_file
