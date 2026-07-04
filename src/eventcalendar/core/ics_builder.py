"""ICS file building and merging utilities."""

import copy
import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
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


# Required fields for event validation
REQUIRED_EVENT_FIELDS = {"uid", "title", "start_time", "end_time", "date", "timezone"}


def build_ics_from_events(events: list) -> Tuple[List[str], List[str]]:
    """Build a list of .ics file content strings from event data.

    Args:
        events: List of event dictionaries.

    Returns:
        Tuple of (ics_strings, warnings).
    """
    events = _normalize_events_input(events)

    ics_strings = []
    warnings = []

    for i, event_dict in enumerate(events):
        result = _build_single_event_ics(event_dict, i)
        if result.success:
            ics_strings.append(result.ics_content)
        if result.warning:
            warnings.append(result.warning)

    return ics_strings, warnings


def _normalize_events_input(events) -> List[Dict]:
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
        return []
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

        # Parse date/time with timezone
        dt_result = _parse_event_datetime(event_dict)

        # Build the ICS calendar object
        cal = _create_ics_calendar()
        event = _create_ics_event(event_dict, dt_result)
        cal.add_component(event)

        ics_content = _format_ics_output(cal)
        return ICSBuildResult(
            success=True,
            ics_content=ics_content,
            warning=dt_result.warning
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
    missing_keys = REQUIRED_EVENT_FIELDS - set(event_dict.keys())
    if missing_keys:
        event_title = event_dict.get('title', f'Event {index + 1}')
        warning_msg = f"Skipping '{event_title}' - missing required fields: {missing_keys}"
        logger.warning(warning_msg)
        return warning_msg
    return None


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
        event_date = parser.parse(event_dict["date"]).date()
        end_date_raw = event_dict.get("end_date") or event_dict.get("date")
        end_date = parser.parse(end_date_raw).date()

        # Parse start and end times
        start_time_str_raw = normalize_time_string(event_dict["start_time"])
        end_time_str_raw = normalize_time_string(event_dict["end_time"])

        base_tz_str = event_dict.get("timezone", "local") or "local"
        start_tz_str = event_dict.get("start_timezone") or base_tz_str
        end_tz_str = event_dict.get("end_timezone") or start_tz_str

        # If the LLM embedded timezone in time strings, prefer that.
        start_time_str, start_tz_from_time = extract_timezone_from_time_string(start_time_str_raw)
        end_time_str, end_tz_from_time = extract_timezone_from_time_string(end_time_str_raw)
        if start_tz_from_time:
            start_tz_str = start_tz_from_time
        if end_tz_from_time:
            end_tz_str = end_tz_from_time

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

            # Zero-duration input: the LLM echoed the start time as the end time
            # (only a start time was stated). Assume a 1-hour event rather than
            # rolling the end date forward into a full 24-hour block.
            if naive_duration == timedelta(0):
                candidate_end_dt = start_dt + timedelta(hours=1)
                if hasattr(end_tz, "normalize"):
                    candidate_end_dt = end_tz.normalize(candidate_end_dt)
                end_dt = candidate_end_dt
                end_dt_utc = candidate_end_dt.astimezone(pytz.utc)
                warnings.append("End time equals start time; assumed a 1-hour duration.")

            # DST edge cases can make an end time appear to be <= start time even when the
            # user provided a positive wall-time duration (e.g. 02:30–03:30 on spring-forward).
            # In that case, preserve the naive duration rather than rolling the end date.
            if naive_duration > timedelta(0) and tz_key(start_tz) == tz_key(end_tz):
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


def _create_ics_event(event_dict: Dict, dt_result: DateTimeResult) -> Event:
    """Create an ICS event component.

    Args:
        event_dict: Dictionary containing event data.
        dt_result: Parsed date/time result.

    Returns:
        An Event component ready to add to a calendar.
    """
    ve = Event()

    # Ensure UID is present and reasonably unique
    uid = event_dict.get("uid") or str(uuid.uuid4())
    ve.add("UID", uid)

    # Use current UTC time for DTSTAMP
    ve.add("DTSTAMP", datetime.now(pytz.utc))

    # Add start and end times
    ve.add("DTSTART", dt_result.start_utc)
    ve.add("DTEND", dt_result.end_utc)

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
