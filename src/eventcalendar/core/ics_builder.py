"""ICS file building and merging utilities."""

import copy
import logging
import uuid
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Dict, List, Optional, Tuple

import pytz
from dateutil import parser
from icalendar import Calendar, Event, vText, Alarm

from eventcalendar.config.constants import (
    ICS_PRODID,
    ICS_VERSION,
    ICS_CALSCALE,
    DEFAULT_REMINDER_MINUTES,
    DEFAULT_EVENT_TITLE,
)
from eventcalendar.core.timezone_utils import (
    normalize_time_string,
    resolve_timezone,
    attach_timezone_with_warnings,
    extract_timezone_from_time_string,
)
from eventcalendar.core.event_model import CalendarEvent

logger = logging.getLogger(__name__)


@dataclass
class ICSBuildResult:
    """Result of building an ICS event."""
    success: bool
    ics_content: Optional[str] = None
    warning: Optional[str] = None


@dataclass
class DateTimeResult:
    """Result of parsing event date/time."""
    start_utc: datetime
    end_utc: datetime
    warning: Optional[str] = None


@dataclass
class ICSBatchResult:
    """Structured result for a multi-event build."""

    ics_strings: List[str]
    created_events: List[Dict]
    skipped_events: List[str]
    warnings: List[str]


# Required fields for event validation. "uid" and "timezone" are not listed:
# both are defaulted during ICS creation, so their absence is not fatal.
REQUIRED_EVENT_FIELDS = {"title", "start_time", "end_time", "date"}
ALL_DAY_REQUIRED_FIELDS = {"title", "date"}


def _is_all_day(event_dict: Dict) -> bool:
    """Interpret the optional all_day flag, tolerating LLM string booleans."""
    value = event_dict.get("all_day", False)
    if isinstance(value, str):
        return value.strip().lower() in {"true", "yes", "1"}
    return bool(value)


def build_ics_from_events(events: list) -> Tuple[List[str], List[str]]:
    """Build a list of .ics file content strings from event data.

    Args:
        events: List of event dictionaries.

    Returns:
        Tuple of (ics_strings, warnings).
    """
    result = build_ics_batch(events)
    return result.ics_strings, [*result.skipped_events, *result.warnings]


def build_ics_batch(events) -> ICSBatchResult:
    """Validate and build each event without allowing one bad item to crash a batch."""
    normalized = _normalize_events_input(events)
    ics_strings: List[str] = []
    created_events: List[Dict] = []
    skipped_events: List[str] = []
    warnings: List[str] = []

    if normalized is None:
        return ICSBatchResult([], [], ["Event payload must be an object or a list of objects."], [])

    for index, raw_event in enumerate(normalized):
        if not isinstance(raw_event, dict):
            skipped_events.append(
                f"Skipping event {index + 1} - expected an object, got {type(raw_event).__name__}."
            )
            continue
        try:
            event_dict = CalendarEvent.from_dict(raw_event).to_dict()
        except Exception as exc:
            title = raw_event.get("title") or f"Event {index + 1}"
            skipped_events.append(f"Skipping '{title}' - {exc}")
            continue

        result = _build_single_event_ics(event_dict, index)
        if result.success and result.ics_content is not None:
            ics_strings.append(result.ics_content)
            created_events.append(event_dict)
            if result.warning:
                warnings.append(result.warning)
        elif result.warning:
            skipped_events.append(result.warning)

    return ICSBatchResult(ics_strings, created_events, skipped_events, warnings)


def _normalize_events_input(events) -> Optional[List]:
    """Ensure events is a list of dicts.

    Args:
        events: Input that should be a list of event dicts.

    Returns:
        Normalized list of event dictionaries.
    """
    if isinstance(events, dict):
        return [events]
    if not isinstance(events, list):
        logger.error("Expected a list of events, but got %s", type(events))
        return None
    return events


def _build_single_event_ics(event_dict: Dict, index: int) -> ICSBuildResult:
    """Build ICS for a single event.

    Args:
        event_dict: Dictionary containing event data.
        index: Index of the event in the list (for error messages).

    Returns:
        ICSBuildResult with success status, content, and optional warning.
    """
    try:
        # Validate required fields
        validation_warning = _validate_event_fields(event_dict, index)
        if validation_warning:
            return ICSBuildResult(success=False, warning=validation_warning)

        # Parse the event window: whole dates for all-day events, otherwise
        # timezone-resolved UTC datetimes.
        if _is_all_day(event_dict):
            start, end = _parse_all_day_dates(event_dict)
            warning = None
            all_day = True
        else:
            dt_result = _parse_event_datetime(event_dict)
            start, end = dt_result.start_utc, dt_result.end_utc
            warning = dt_result.warning
            all_day = False

        # Build the ICS calendar object
        cal = _create_ics_calendar()
        event = _create_ics_event(event_dict, start, end, all_day=all_day)
        cal.add_component(event)

        ics_content = _format_ics_output(cal)
        return ICSBuildResult(
            success=True,
            ics_content=ics_content,
            warning=warning
        )

    except Exception as e:
        event_title = event_dict.get('title', 'Unknown Title')
        error_msg = f"Error building ICS for event {index + 1} ({event_title}): {e}"
        logger.error(error_msg)
        return ICSBuildResult(success=False, warning=error_msg)


def _validate_event_fields(event_dict: Dict, index: int) -> Optional[str]:
    """Validate that required fields are present.

    Args:
        event_dict: Dictionary containing event data.
        index: Index of the event for error messages.

    Returns:
        Warning message if validation fails, None otherwise.
    """
    required = ALL_DAY_REQUIRED_FIELDS if _is_all_day(event_dict) else REQUIRED_EVENT_FIELDS
    missing_keys = required - set(event_dict.keys())
    if missing_keys:
        event_title = event_dict.get('title', f'Event {index + 1}')
        warning_msg = f"Skipping '{event_title}' - missing required fields: {missing_keys}"
        logger.warning(warning_msg)
        return warning_msg
    return None


def _parse_all_day_dates(event_dict: Dict) -> Tuple[date, date]:
    """Parse the date range for an all-day event.

    Args:
        event_dict: Dictionary containing event data.

    Returns:
        Tuple of (start_date, end_date_exclusive). Per RFC 5545, DTEND for
        all-day events is non-inclusive: the day AFTER the last event day.

    Raises:
        ValueError: If the end date is before the start date.
    """
    start_day = date.fromisoformat(event_dict["date"])
    end_date_raw = event_dict.get("end_date")
    last_day = date.fromisoformat(end_date_raw) if end_date_raw else start_day
    if last_day < start_day:
        raise ValueError(
            f"All-day end date ({last_day.isoformat()}) is before start date "
            f"({start_day.isoformat()})."
        )
    return start_day, last_day + timedelta(days=1)


def _parse_event_datetime(event_dict: Dict) -> DateTimeResult:
    """Parse and resolve event date/time with timezone.

    Args:
        event_dict: Dictionary containing event data.

    Returns:
        DateTimeResult with UTC datetimes and optional warning.

    Raises:
        Exception: If date/time parsing fails.
    """
    try:
        warnings: List[str] = []

        # Parse the date first
        event_date = date.fromisoformat(event_dict["date"])
        end_date_raw = event_dict.get("end_date") or event_dict.get("date")
        end_date = date.fromisoformat(end_date_raw)

        # Parse start and end times
        start_time_str_raw = normalize_time_string(event_dict["start_time"])
        end_time_str_raw = normalize_time_string(event_dict["end_time"])

        base_tz_str = event_dict.get("timezone", "local") or "local"
        start_tz_str = event_dict.get("start_timezone") or base_tz_str
        explicit_end_timezone = bool(event_dict.get("end_timezone"))
        end_tz_str = event_dict.get("end_timezone") or start_tz_str

        # If the LLM embedded timezone in time strings, prefer that.
        start_time_str, start_tz_from_time = extract_timezone_from_time_string(start_time_str_raw)
        end_time_str, end_tz_from_time = extract_timezone_from_time_string(end_time_str_raw)
        if start_tz_from_time:
            start_tz_str = start_tz_from_time
        if end_tz_from_time:
            end_tz_str = end_tz_from_time
        elif not explicit_end_timezone:
            # An embedded start zone becomes the event's effective zone unless
            # the user explicitly supplied a different end zone.
            end_tz_str = start_tz_str

        # Resolve start/end timezones separately (supports travel "timezone jumps")
        event_title = event_dict.get("title")
        start_tz, start_tz_warning = resolve_timezone(str(start_tz_str), event_title)
        end_tz, end_tz_warning = resolve_timezone(str(end_tz_str), event_title)
        if start_tz_warning:
            warnings.append(f"Start time: {start_tz_warning}")
        if end_tz_warning and end_tz_warning != start_tz_warning:
            warnings.append(f"End time: {end_tz_warning}")

        # Parse times and combine with date
        start_time = parser.parse(start_time_str).time()
        end_time = parser.parse(end_time_str).time()

        # Combine date and time (still naive at this point)
        start_dt_naive = datetime.combine(event_date, start_time)
        end_dt_naive = datetime.combine(end_date, end_time)

        # Attach timezone
        start_dt, start_dst_warning = attach_timezone_with_warnings(start_tz, start_dt_naive)
        end_dt, end_dst_warning = attach_timezone_with_warnings(end_tz, end_dt_naive)
        if start_dst_warning:
            warnings.append(f"Start time: {start_dst_warning}")
        if end_dst_warning:
            warnings.append(f"End time: {end_dst_warning}")

        # Convert to UTC for storage
        start_dt_utc = start_dt.astimezone(pytz.utc)
        end_dt_utc = end_dt.astimezone(pytz.utc)

        # If end time is not after start, assume it crosses midnight (or the end date was omitted).
        if end_dt_utc <= start_dt_utc:
            explicit_end_date = "end_date" in event_dict and bool(event_dict.get("end_date"))
            if explicit_end_date:
                raise ValueError(
                    f"End time ({end_dt_utc.isoformat()}) is not after start time "
                    f"({start_dt_utc.isoformat()}) after timezone conversion."
                )

            def tz_key(tzobj) -> str:
                return str(getattr(tzobj, "zone", getattr(tzobj, "key", str(tzobj))))

            naive_duration = end_dt_naive - start_dt_naive

            same_timezone = tz_key(start_tz) == tz_key(end_tz)

            # Zero-duration input in one timezone: the LLM echoed the start time
            # (only a start time was stated). Assume a 1-hour event rather than
            # rolling the end date forward into a full 24-hour block.
            if naive_duration == timedelta(0) and same_timezone:
                candidate_end_dt = start_dt + timedelta(hours=1)
                if hasattr(end_tz, "normalize"):
                    candidate_end_dt = end_tz.normalize(candidate_end_dt)
                end_dt = candidate_end_dt
                end_dt_utc = candidate_end_dt.astimezone(pytz.utc)
                warnings.append("End time equals start time; assumed a 1-hour duration.")

            # DST edge cases can make an end time appear to be <= start time even when the
            # user provided a positive wall-time duration (e.g. 02:30–03:30 on spring-forward).
            # In that case, preserve the naive duration rather than rolling the end date.
            if naive_duration > timedelta(0) and same_timezone:
                candidate_end_dt = start_dt + naive_duration
                if hasattr(end_tz, "normalize"):
                    candidate_end_dt = end_tz.normalize(candidate_end_dt)
                candidate_end_utc = candidate_end_dt.astimezone(pytz.utc)
                if candidate_end_utc > start_dt_utc:
                    end_dt = candidate_end_dt
                    end_dt_utc = candidate_end_utc
                    warnings.append(
                        "End time was not after start after DST/timezone resolution; "
                        "preserved the original duration instead of rolling the end date."
                    )
                else:
                    # Fall back to rolling the end date.
                    pass

            if end_dt_utc <= start_dt_utc:
                adjusted = False
                for days in (1, 2):
                    candidate_end_naive = end_dt_naive + timedelta(days=days)
                    candidate_end_dt, candidate_dst_warning = attach_timezone_with_warnings(
                        end_tz,
                        candidate_end_naive,
                    )
                    candidate_end_utc = candidate_end_dt.astimezone(pytz.utc)
                    if candidate_end_utc > start_dt_utc:
                        end_dt = candidate_end_dt
                        end_dt_utc = candidate_end_utc
                        adjusted = True
                        warnings.append(
                            "End time occurred before start after timezone conversion; "
                            f"assumed the end date is {candidate_end_naive.date().isoformat()}."
                        )
                        if candidate_dst_warning:
                            warnings.append(f"End time: {candidate_dst_warning}")
                        break

                if not adjusted:
                    raise ValueError(
                        f"End time ({end_dt_utc.isoformat()}) is not after start time "
                        f"({start_dt_utc.isoformat()}) after timezone conversion."
                    )

        return DateTimeResult(
            start_utc=start_dt_utc,
            end_utc=end_dt_utc,
            warning="\n".join(warnings) if warnings else None,
        )
    except Exception as dt_err:
        event_title = event_dict.get('title', 'Unknown')
        logger.warning(
            "Skipping event '%s' due to date/time parsing error: %s",
            event_title, dt_err
        )
        raise


def _create_ics_calendar() -> Calendar:
    """Create a new ICS calendar with standard headers.

    Returns:
        A new Calendar object with required headers.
    """
    cal = Calendar()
    cal.add("PRODID", ICS_PRODID)
    cal.add("VERSION", ICS_VERSION)
    cal.add("CALSCALE", ICS_CALSCALE)
    return cal


def _create_ics_event(event_dict: Dict, start, end, all_day: bool = False) -> Event:
    """Create an ICS event component.

    Args:
        event_dict: Dictionary containing event data.
        start: Start as a UTC datetime, or a date for all-day events.
        end: End as a UTC datetime, or the exclusive end date for all-day events.
        all_day: Whether this is an all-day (VALUE=DATE) event.

    Returns:
        An Event component ready to add to a calendar.
    """
    ve = Event()

    # Ensure UID is present and reasonably unique
    uid = event_dict.get("uid") or str(uuid.uuid4())
    ve.add("UID", uid)

    # Use current UTC time for DTSTAMP
    ve.add("DTSTAMP", datetime.now(pytz.utc))

    # Add start and end. icalendar serializes date objects as VALUE=DATE.
    ve.add("DTSTART", start)
    ve.add("DTEND", end)

    # Add summary (title)
    title = event_dict.get("title", DEFAULT_EVENT_TITLE)
    ve.add("SUMMARY", vText(str(title)))

    # Add optional location
    location = event_dict.get("location")
    if location:
        ve.add("LOCATION", vText(str(location)))

    # Add optional description
    description = event_dict.get("description")
    if description:
        ve.add("DESCRIPTION", vText(str(description)))

    # Add a reminder alarm
    alarm = Alarm()
    alarm.add("ACTION", "DISPLAY")
    alarm.add("DESCRIPTION", "Reminder")
    if all_day:
        # All-day DTSTART is midnight; fire at 09:00 on the first day,
        # matching the system calendar's default alert for all-day events.
        alarm.add("TRIGGER", timedelta(hours=9))
    else:
        alarm.add("TRIGGER", timedelta(minutes=DEFAULT_REMINDER_MINUTES))
    ve.add_component(alarm)

    return ve


def _format_ics_output(cal: Calendar) -> str:
    """Format calendar to ICS string with proper line endings.

    Args:
        cal: The Calendar object to format.

    Returns:
        ICS content string with CRLF line endings.
    """
    raw_ical = cal.to_ical()
    decoded_ical = raw_ical.decode("utf-8", errors="replace")
    # Ensure CRLF line endings per RFC5545
    crlf_ical = decoded_ical.replace("\r\n", "\n").replace("\n", "\r\n")
    return crlf_ical


def combine_ics_strings(ics_strings: List[str]) -> str:
    """Merge multiple ICS documents while preserving calendar metadata and TZ data.

    Args:
        ics_strings: List of ICS content strings to merge.

    Returns:
        A single merged ICS string.

    Raises:
        ValueError: If no valid ICS data is provided.
    """
    if not ics_strings:
        raise ValueError("No ICS data provided to combine.")

    calendars = _parse_ics_strings(ics_strings)
    if not calendars:
        raise ValueError("No parseable ICS data provided.")

    merged_calendar = _create_merged_calendar(calendars)
    _add_components_to_merged(merged_calendar, calendars)

    return _format_ics_output(merged_calendar)


def _parse_ics_strings(ics_strings: List[str]) -> List[Calendar]:
    """Parse ICS strings into Calendar objects.

    Args:
        ics_strings: List of ICS content strings.

    Returns:
        List of parsed Calendar objects.

    Raises:
        ValueError: If parsing fails.
    """
    calendars = []
    for index, raw in enumerate(ics_strings):
        if raw is None:
            continue

        data = raw.encode("utf-8") if isinstance(raw, str) else raw
        try:
            calendars.append(Calendar.from_ical(data))
        except Exception as exc:
            raise ValueError(
                f"Failed to parse ICS payload at index {index}: {exc}"
            ) from exc

    return calendars


def _create_merged_calendar(calendars: List[Calendar]) -> Calendar:
    """Create a merged calendar with properties from source calendars.

    Args:
        calendars: List of source Calendar objects.

    Returns:
        A new Calendar with merged properties.
    """
    merged_calendar = Calendar()

    # Copy each source calendar's OWN top-level properties. Component.items()
    # yields only this VCALENDAR's properties; property_items() recurses into
    # subcomponents and injects synthetic BEGIN/END markers, which would leak
    # VEVENT/VALARM properties onto the merged header and unbalance the output.
    for calendar in calendars:
        for prop, value in calendar.items():
            if merged_calendar.get(prop) is not None:
                continue
            # A property supplied multiple times surfaces as a list; add each.
            if isinstance(value, list):
                for element in value:
                    merged_calendar.add(prop, element)
            else:
                merged_calendar.add(prop, value)

    # Ensure mandatory headers exist
    if merged_calendar.get("PRODID") is None:
        merged_calendar.add("PRODID", ICS_PRODID)
    if merged_calendar.get("VERSION") is None:
        merged_calendar.add("VERSION", ICS_VERSION)
    if merged_calendar.get("CALSCALE") is None:
        merged_calendar.add("CALSCALE", ICS_CALSCALE)

    return merged_calendar


def _add_components_to_merged(merged_calendar: Calendar, calendars: List[Calendar]) -> None:
    """Add components from source calendars to merged calendar.

    Args:
        merged_calendar: The target merged calendar.
        calendars: List of source Calendar objects.
    """
    seen_timezones: set = set()

    for calendar in calendars:
        for component in calendar.subcomponents:
            component_copy = copy.deepcopy(component)

            if component_copy.name == "VTIMEZONE":
                tzid_raw = component_copy.get("TZID")
                tzid = str(tzid_raw) if tzid_raw else f"__anon_tz_{len(seen_timezones)}"
                if tzid in seen_timezones:
                    continue
                seen_timezones.add(tzid)
                merged_calendar.add_component(component_copy)
                continue

            if component_copy.name == "VEVENT":
                # Regenerate UID for merged events
                component_copy["UID"] = f"{uuid.uuid4()}@nl-calendar"
                merged_calendar.add_component(component_copy)
                continue

            merged_calendar.add_component(component_copy)
