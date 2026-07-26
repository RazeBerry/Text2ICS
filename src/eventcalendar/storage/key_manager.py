"""High-level API key management."""

import logging
import os
import sys
from pathlib import Path
from typing import Callable, Iterator, Optional, Tuple

from dotenv import unset_key

from eventcalendar.config.constants import PREFERRED_ENV_VAR, PRIMARY_ENV_VAR
from eventcalendar.storage.keyring_storage import load_from_keyring, save_to_keyring
from eventcalendar.storage.env_storage import (
    get_env_file_path,
    get_legacy_env_path,
    get_executable_dir_env_path,
    load_from_env_file,
    store_in_env_file,
)

logger = logging.getLogger(__name__)


def _key_sources() -> Iterator[Tuple[Callable[[], Optional[str]], str, Optional[Path]]]:
    """Yield the single authoritative key lookup order."""
    yield (
        lambda: os.environ.get(PREFERRED_ENV_VAR),
        f"Environment Variable ({PREFERRED_ENV_VAR})",
        None,
    )
    yield (
        lambda: os.environ.get(PRIMARY_ENV_VAR),
        f"Environment Variable ({PRIMARY_ENV_VAR})",
        None,
    )
    yield load_from_keyring, f"{get_keyring_display_name()} (Secure)", None
    user_path = get_env_file_path()
    yield lambda: load_from_env_file(user_path), f"User Config: {user_path}", user_path
    if getattr(sys, "frozen", False):
        executable_path = get_executable_dir_env_path()
        yield (
            lambda: load_from_env_file(executable_path),
            f"Executable Directory: {executable_path}",
            executable_path,
        )
    legacy_path = get_legacy_env_path()
    yield (
        lambda: load_from_env_file(legacy_path),
        f"LEGACY (Insecure): {legacy_path}",
        legacy_path,
    )


def get_keyring_display_name() -> str:
    """Get platform-appropriate display name for the secure keyring storage.

    Returns:
        Human-readable name for the OS keyring/credential manager.
    """
    if sys.platform == "darwin":
        return "macOS Keychain"
    elif sys.platform.startswith("win"):
        return "Windows Credential Manager"
    else:
        # Linux and other Unix-like systems use Secret Service
        return "System Keyring (Secret Service)"


def get_api_key_source() -> Tuple[Optional[str], str]:
    """Determine which storage location is currently being used for the API key.

    Returns:
        Tuple of (api_key, source_description).
    """
    for loader, description, _path in _key_sources():
        key = loader()
        if key:
            return key, description

    return None, "No API Key Found"


def migrate_legacy_key() -> Tuple[bool, str]:
    """Migrate API key from legacy .env (project directory) to secure storage.

    Returns:
        Tuple of (success, message).
    """
    legacy_path = get_legacy_env_path()

    # Check if legacy key exists
    if not legacy_path.exists():
        return False, "No legacy key file found"

    legacy_key = load_from_env_file(legacy_path)
    if not legacy_key:
        return False, "Legacy file exists but contains no valid key"

    # Check if we already have the key in secure storage
    keyring_key = load_from_keyring()
    if keyring_key:
        if keyring_key == legacy_key:
            logger.info("API key already migrated to keyring")
            return True, "Key already in keyring - you can safely delete legacy .env"
        else:
            logger.warning("Different key in keyring vs legacy - keeping both")
            return False, "Conflicting keys detected - manual intervention required"

    # Migrate to secure storage
    logger.info("Migrating API key from legacy location to secure storage...")
    if save_api_key(legacy_key):
        logger.info("Migration successful!")
        return True, f"Migrated to secure storage. You can now safely delete: {legacy_path}"
    else:
        logger.error("Migration failed")
        return False, "Failed to save key to secure storage"


def load_api_key() -> Optional[str]:
    """Load the Gemini API key.

    Priority:
        1. GEMINI_API_KEY_FREE environment variable
        2. GEMINI_API_KEY environment variable
        3. OS keyring
        4. User config .env
        5. Legacy .env

    Automatically attempts migration if only legacy key exists.

    Returns:
        The API key if found, None otherwise.
    """
    legacy_path = get_legacy_env_path()
    for loader, _description, path in _key_sources():
        key = loader()
        if not key:
            continue
        if path == legacy_path:
            logger.warning("Using legacy API key storage - attempting migration...")
            success, message = migrate_legacy_key()
            (logger.info if success else logger.warning)(message)
        return key

    return None


def delete_legacy_key_file() -> Tuple[bool, str]:
    """Remove Gemini credentials while preserving unrelated legacy settings."""
    legacy_path = get_legacy_env_path()
    if not legacy_path.exists():
        return True, "Legacy key file is already absent."
    try:
        unset_key(str(legacy_path), PREFERRED_ENV_VAR)
        unset_key(str(legacy_path), PRIMARY_ENV_VAR)
        remaining_lines = legacy_path.read_text(encoding="utf-8").splitlines()
        has_other_content = any(
            line.strip() and not line.lstrip().startswith("#") for line in remaining_lines
        )
        if has_other_content:
            return True, f"Removed Gemini keys and preserved other settings in: {legacy_path}"
        legacy_path.unlink()
    except Exception as exc:
        logger.error("Could not remove legacy credentials from %s: %s", legacy_path, exc)
        return False, f"Could not remove credentials from {legacy_path}: {exc}"
    return True, f"Deleted legacy key file: {legacy_path}"


def save_api_key(api_key: str) -> bool:
    """Save the API key securely.

    Primary: OS keyring (encrypted, persistent)
    Fallback: .env in per-user config dir with secure permissions (only if keyring fails)

    Args:
        api_key: The API key to save.

    Returns:
        True if saved successfully, False otherwise.
    """
    try:
        # Sanitize input: remove quotes, whitespace, control characters
        api_key = api_key.strip().strip("'\"").strip()

        # Try keyring first
        keyring_ok = save_to_keyring(api_key)
        if keyring_ok:
            logger.info("API key saved to keyring successfully")
        else:
            logger.warning("Keyring unavailable, using file storage instead")
            store_in_env_file(api_key)

        return True

    except Exception as e:
        logger.error("Failed to save API key: %s", e)
        return False


def check_and_warn_legacy_storage() -> Optional[str]:
    """Check for legacy storage and return a warning message if found.

    Returns:
        Warning message if legacy storage is in use, None otherwise.
    """
    legacy_path = get_legacy_env_path()
    if not legacy_path.exists():
        return None

    # Check if we also have secure storage
    keyring_key = load_from_keyring()
    env_file_key = load_from_env_file(get_env_file_path())

    if keyring_key or env_file_key:
        return (
            f"Legacy .env file found at {legacy_path}. "
            "Your key has been migrated to secure storage. "
            "You can safely delete the legacy file."
        )

    return (
        f"Your API key is stored insecurely at {legacy_path}. "
        "Consider migrating to secure storage using the Settings menu."
    )
