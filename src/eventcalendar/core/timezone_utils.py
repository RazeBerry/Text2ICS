"""Timezone resolution and time normalization utilities."""

import logging
import os
import re
from datetime import datetime
from typing import Optional, Tuple

import pytz
import tzlocal
from dateutil import tz as du_tz
from pytz.exceptions import AmbiguousTimeError, NonExistentTimeError

from eventcalendar.config.constants import ABBR_TO_TZ

logger = logging.getLogger(__name__)

_IANA_TZ_PATTERN = re.compile(r"\b([A-Za-z]+/[A-Za-z0-9_\-]+(?:/[A-Za-z0-9_\-]+)?)\b")
# Two clock times joined by a dash ("19:30-20:00", "7:30 PM - 9:00 PM"). Each
# side is a clock time with an optional am/pm suffix.
_TIME_RANGE_PATTERN = re.compile(
    r"^\s*\d{1,2}(?:[:.]\d{2})?\s*(?:[ap]\.?m\.?)?"
    r"\s*[-–—]\s*"
    r"\d{1,2}(?:[:.]\d{2})?\s*(?:[ap]\.?m\.?)?\s*$",
    re.IGNORECASE,
)
_UTC_OFFSET_PATTERN = re.compile(
    r"^(?:(UTC|GMT)\s*)?(?P<sign>[+-])(?P<hours>\d{1,2})(?::?(?P<minutes>\d{2}))?$",
    re.IGNORECASE,
)

_DST_AMBIGUOUS_ENV = "EVENTCALENDAR_DST_AMBIGUOUS"  # earlier|later|raise
_DST_NONEXISTENT_ENV = "EVENTCALENDAR_DST_NONEXISTENT"  # shift_forward|raise
_DEFAULT_DST_AMBIGUOUS = "later"
_DEFAULT_DST_NONEXISTENT = "shift_forward"


def _describe_tz(tzobj) -> str:
    if hasattr(tzobj, "zone"):  # pytz
        return str(getattr(tzobj, "zone"))
    if hasattr(tzobj, "key"):  # zoneinfo
        return str(getattr(tzobj, "key"))
    return str(tzobj)


def _get_dst_policy(env_var: str, default: str) -> str:
    raw = os.environ.get(env_var, default)
    if raw is None:
        return default
    return str(raw).strip().lower()


def _parse_utc_offset_seconds(tz_str: str) -> Optional[int]:
    """Parse timezone strings like 'Z', '+02:00', '-0500', 'UTC+2' into seconds."""
    if not tz_str:
        return None

    s = tz_str.strip()
    if not s:
        return None

    upper = s.upper()
    if upper in {"Z", "UTC", "GMT"}:
        return 0

    match = _UTC_OFFSET_PATTERN.match(s)
    if not match:
        return None

    sign = -1 if match.group("sign") == "-" else 1
    hours = int(match.group("hours"))
    minutes = int(match.group("minutes") or "0")
    if minutes > 59:
        return None
    total_seconds = sign * (hours * 3600 + minutes * 60)
    # Real-world UTC offsets only span -12:00 .. +14:00 (IANA range); anything
    # outside is almost certainly a misparsed time range, not an offset.
    if total_seconds < -12 * 3600 or total_seconds > 14 * 3600:
        return None
    return total_seconds


def extract_timezone_from_time_string(time_str: str) -> Tuple[str, Optional[str]]:
    """Extract an explicit timezone token from a time string.

    Examples:
        "7:30 PM EST" -> ("7:30 PM", "EST")
        "19:30+02:00" -> ("19:30", "+02:00")
        "10:00 (America/Los_Angeles)" -> ("10:00", "America/Los_Angeles")
    """
    if not isinstance(time_str, str):
        return str(time_str), None

    s = time_str.strip()
    if not s:
        return s, None

    # Parenthesized tz at end: "7pm (EST)"
    paren_match = re.search(r"\(\s*([^)]+?)\s*\)\s*$", s)
    if paren_match:
        tz_candidate = paren_match.group(1).strip()
        normalized = _normalize_tz_candidate(tz_candidate)
        if normalized:
            return s[:paren_match.start()].strip(), normalized

    # IANA zone anywhere in the string.
    iana_match = _IANA_TZ_PATTERN.search(s)
    if iana_match:
        tz_candidate = iana_match.group(1)
        cleaned = (s[:iana_match.start()] + s[iana_match.end():]).strip()
        return cleaned, tz_candidate

    # A time range is not a timezone offset: "19:30-20:00" must not be read as
    # "19:30" at UTC-20:00. Detect ranges before the attached-offset branch.
    # Trade-off: a genuine attached NEGATIVE offset ("19:30-08:00") is
    # indistinguishable from a range and is treated as a range; positive offsets
    # ("19:30+0200") and "Z" are unaffected.
    if _TIME_RANGE_PATTERN.match(s):
        return s, None

    # Trailing Z or numeric offset attached to the time: "19:30Z", "19:30+0200"
    attached = re.search(r"^(?P<time>.*?)(?P<tz>Z|[+-]\d{2}:?\d{2})$", s, re.IGNORECASE)
    if attached and attached.group("time").strip():
        return attached.group("time").strip(), attached.group("tz").upper()

    # Last whitespace-separated token.
    parts = re.split(r"\s+", s)
    if len(parts) >= 2:
        candidate = parts[-1].strip().strip(",;")
        normalized = _normalize_tz_candidate(candidate)
        if normalized:
            return " ".join(parts[:-1]).strip(), normalized

    return s, None


def _normalize_tz_candidate(candidate: str) -> Optional[str]:
    if not candidate:
        return None

    raw = candidate.strip().strip(",;").strip()
    if not raw:
        return None

    # Ignore AM/PM tokens.
    upper = raw.upper().replace(".", "")
    if upper in {"AM", "PM"}:
        return None

    # Prefer IANA zones as-is.
    if "/" in raw:
        return raw

    # Canonical UTC tokens.
    if upper in {"Z", "UTC", "GMT"}:
        return upper

    # UTC offsets (+02:00, -0500, UTC+2, GMT-0300).
    if _parse_utc_offset_seconds(raw) is not None:
        return upper.replace(" ", "")

    # Abbreviations (EST/PDT/etc.) – normalize to upper.
    if upper in ABBR_TO_TZ:
        return upper

    return None


def normalize_time_string(time_str: str) -> str:
    """Handle common human formats like '20:00h' or '20h15' before parsing.

    Args:
        time_str: The time string to normalize.

    Returns:
        A normalized time string that dateutil can parse.
    """
    if not isinstance(time_str, str):
        return str(time_str)

    s = time_str.strip()

    # Convert European "20.00" to "20:00" for dateutil
    if re.match(r"^\d{1,2}\.\d{2}$", s):
        s = s.replace(".", ":")

    # Handle "20:00h", "20h", "20h15", "20h15m" styles
    match = re.match(r"^\s*(\d{1,2})(?:[:\.]?(\d{2}))?\s*h(?:rs?)?\.?\s*$", s, re.IGNORECASE)
    if match:
        hour = int(match.group(1))
        minute = match.group(2) or "00"
        return f"{hour:02d}:{minute}"

    match = re.match(r"^\s*(\d{1,2})h(\d{2})\s*$", s, re.IGNORECASE)
    if match:
        hour = int(match.group(1))
        minute = match.group(2)
        return f"{hour:02d}:{minute}"

    # Fallback: return cleaned string
    return s


def resolve_timezone(tz_str: str, event_title: Optional[str] = None) -> Tuple[object, Optional[str]]:
    """Resolve a timezone string to a timezone object.

    Args:
        tz_str: The timezone string (e.g., "EST", "America/New_York", "local").
        event_title: Optional event title for warning messages.

    Returns:
        Tuple of (timezone_object, warning_message or None).
    """
    tz_str_raw = tz_str or "local"
    tz_clean = str(tz_str_raw).strip()
    tz_upper = tz_clean.upper()
    warning = None

    if tz_upper == "LOCAL":
        # User's system zone (DST aware)
        local_tz_obj = tzlocal.get_localzone()
        tz_name = getattr(local_tz_obj, "zone", str(local_tz_obj))
    else:
        offset_seconds = _parse_utc_offset_seconds(tz_clean)
        if offset_seconds is not None:
            if offset_seconds == 0:
                return pytz.utc, None
            return du_tz.tzoffset(tz_upper.replace(" ", ""), offset_seconds), None

        tz_name = ABBR_TO_TZ.get(tz_upper, tz_clean)

    try:
        local_tz = pytz.timezone(tz_name)
    except pytz.UnknownTimeZoneError:
        # Last-ditch attempt with dateutil (may return fixed offset)
        local_tz = du_tz.gettz(tz_name)
        if local_tz is None:
            local_tz = pytz.utc
            event_desc = f"'{event_title}'" if event_title else "event"
            warning = (
                f"Couldn't resolve timezone '{tz_str_raw}' for {event_desc} - "
                "using UTC. Please verify the time in your calendar."
            )
            logger.warning(warning)

    return local_tz, warning


_RAISE_POLICIES = {"raise", "error", "strict"}


def _check_ambiguous_policy() -> Tuple[bool, bool]:
    """Check ambiguous-time policy.

    Returns:
        (should_raise, choose_earlier) tuple.
    """
    policy = _get_dst_policy(_DST_AMBIGUOUS_ENV, _DEFAULT_DST_AMBIGUOUS)
    if policy in _RAISE_POLICIES:
        return True, False
    choose_earlier = policy in {"earlier", "first", "dst", "summer"}
    return False, choose_earlier


def _check_nonexistent_policy() -> bool:
    """Check non-existent-time policy.

    Returns:
        True if the caller should raise, False to shift forward.
    """
    policy = _get_dst_policy(_DST_NONEXISTENT_ENV, _DEFAULT_DST_NONEXISTENT)
    return policy in _RAISE_POLICIES


def _ambiguous_warning(naive_dt: datetime, tz_label: str, chosen: str) -> str:
    """Format a warning message for ambiguous DST resolution."""
    return (
        f"DST ambiguity: local time '{naive_dt}' in '{tz_label}' occurs twice; "
        f"choosing the {chosen} instance. "
        f"(Override via {_DST_AMBIGUOUS_ENV}=earlier|later|raise.)"
    )


def _nonexistent_warning(naive_dt: datetime, tz_label: str, resolved: datetime) -> str:
    """Format a warning message for non-existent DST resolution."""
    return (
        f"DST gap: local time '{naive_dt}' in '{tz_label}' does not exist; "
        f"shifted forward to '{resolved}'. "
        f"(Override via {_DST_NONEXISTENT_ENV}=shift_forward|raise.)"
    )


def attach_timezone_with_warnings(tzobj, naive_dt: datetime) -> Tuple[datetime, Optional[str]]:
    """Attach timezone to a naive datetime with DST-safe handling.

    For pytz zones, this will:
    - Detect ambiguous times (fall-back) and choose deterministically (default: later/standard time).
    - Detect non-existent times (spring-forward) and shift forward to the next valid time.

    For zoneinfo/dateutil zones, this resolves DST edge cases using dateutil helpers.

    DST resolution can be configured via environment variables:
    - EVENTCALENDAR_DST_AMBIGUOUS: earlier|later|raise (default: later)
    - EVENTCALENDAR_DST_NONEXISTENT: shift_forward|raise (default: shift_forward)

    Returns:
        (timezone_aware_datetime, warning_message_or_None)
    """
    tz_label = _describe_tz(tzobj)

    if hasattr(tzobj, "localize"):
        # pytz – honor DST rules and surface ambiguity/non-existence.
        try:
            return tzobj.localize(naive_dt, is_dst=None), None
        except AmbiguousTimeError:
            should_raise, choose_earlier = _check_ambiguous_policy()
            if should_raise:
                raise
            resolved = tzobj.localize(naive_dt, is_dst=choose_earlier)
            chosen = "earlier (DST)" if choose_earlier else "later (standard)"
            return resolved, _ambiguous_warning(naive_dt, tz_label, chosen)
        except NonExistentTimeError:
            if _check_nonexistent_policy():
                raise
            resolved = tzobj.normalize(tzobj.localize(naive_dt, is_dst=False))
            return resolved, _nonexistent_warning(naive_dt, tz_label, resolved)

    # zoneinfo/dateutil – attach tzinfo then resolve ambiguity/gaps.
    aware = naive_dt.replace(tzinfo=tzobj)
    warnings: list[str] = []

    if not du_tz.datetime_exists(aware):
        if _check_nonexistent_policy():
            raise ValueError(f"DST gap: local time '{naive_dt}' in '{tz_label}' does not exist.")
        shifted = du_tz.resolve_imaginary(aware)
        warnings.append(_nonexistent_warning(naive_dt, tz_label, shifted))
        aware = shifted

    if du_tz.datetime_ambiguous(aware):
        should_raise, choose_earlier = _check_ambiguous_policy()
        if should_raise:
            raise ValueError(f"DST ambiguity: local time '{naive_dt}' in '{tz_label}' occurs twice.")
        fold = 0 if choose_earlier else 1
        resolved = du_tz.enfold(aware, fold=fold)
        chosen = "earlier (fold=0)" if choose_earlier else "later (fold=1)"
        warnings.append(_ambiguous_warning(naive_dt, tz_label, chosen))
        aware = resolved

    warning = " | ".join(warnings) if warnings else None
    return aware, warning
