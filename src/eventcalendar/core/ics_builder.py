"""ICS file building and merging utilities."""

import copy
import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import List, Optional, Tuple

import pytz
from icalendar import Calendar, Event, vText, Alarm

from eventcalendar.config.constants import (
    ICS_PRODID,
    ICS_VERSION,
    ICS_CALSCALE,
    DEFAULT_REMINDER_MINUTES,
)
from eventcalendar.core.event_model import CalendarEvent
from eventcalendar.core.temporal_resolution import ResolvedEventWindow, resolve_event_window

logger = logging.getLogger(__name__)


@dataclass
class ICSBatchResult:
    """Structured result for a multi-event build."""

    ics_strings: List[str]
    created_events: List[dict]
    skipped_events: List[str]
    warnings: List[str]


@dataclass
class ICSMergedResult:
    """A directly assembled calendar plus partial-success diagnostics."""

    ics_content: Optional[str]
    created_events: List[dict]
    skipped_events: List[str]
    warnings: List[str]


@dataclass
class _ComponentBuildResult:
    """Internal typed component result used by both public build paths."""

    event: Optional[CalendarEvent]
    component: Optional[Event]
    warning: Optional[str] = None


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
    """Build individual ICS documents while preserving the public legacy API."""
    normalized = _normalize_events_input(events)
    ics_strings: List[str] = []
    created_events: List[dict] = []
    skipped_events: List[str] = []
    warnings: List[str] = []

    if normalized is None:
        return ICSBatchResult([], [], ["Event payload must be an object or a list of objects."], [])

    for index, raw_event in enumerate(normalized):
        result = _build_event_component(raw_event, index)
        if result.component is None or result.event is None:
            if result.warning:
                skipped_events.append(result.warning)
            continue

        try:
            calendar = _create_ics_calendar()
            calendar.add_component(result.component)
            ics_strings.append(_format_ics_output(calendar))
        except Exception as exc:
            skipped_events.append(_build_error_message(index, result.event.title, exc))
            continue

        created_events.append(result.event.to_dict())
        if result.warning:
            warnings.append(result.warning)

    return ICSBatchResult(ics_strings, created_events, skipped_events, warnings)


def build_merged_ics(events) -> ICSMergedResult:
    """Build one calendar directly, avoiding serialize/parse/deep-copy churn."""
    normalized = _normalize_events_input(events)
    if normalized is None:
        return ICSMergedResult(
            None,
            [],
            ["Event payload must be an object or a list of objects."],
            [],
        )

    calendar = _create_ics_calendar()
    created_events: List[dict] = []
    skipped_events: List[str] = []
    warnings: List[str] = []

    for index, raw_event in enumerate(normalized):
        result = _build_event_component(raw_event, index)
        if result.component is None or result.event is None:
            if result.warning:
                skipped_events.append(result.warning)
            continue

        # The historical UI merge path assigns fresh import UIDs. Keep that
        # behavior here while the public single-document builder preserves its UID.
        result.component["UID"] = f"{uuid.uuid4()}@nl-calendar"
        calendar.add_component(result.component)
        created_events.append(result.event.to_dict())
        if result.warning:
            warnings.append(result.warning)

    content = _format_ics_output(calendar) if created_events else None
    return ICSMergedResult(content, created_events, skipped_events, warnings)


def _normalize_events_input(events) -> Optional[List[object]]:
    """Normalize the compatibility input shape without validating twice.

    Args:
        events: Input that should be a list of event dicts.

    Returns:
        Normalized list of event mappings or already-validated models.
    """
    if isinstance(events, (dict, CalendarEvent)):
        return [events]
    if isinstance(events, tuple):
        return list(events)
    if not isinstance(events, list):
        logger.error("Expected a list of events, but got %s", type(events))
        return None
    return events


def _build_event_component(raw_event: object, index: int) -> _ComponentBuildResult:
    """Lower one compatibility input into a typed VEVENT component."""
    if not isinstance(raw_event, (dict, CalendarEvent)):
        return _ComponentBuildResult(
            None,
            None,
            f"Skipping event {index + 1} - expected an object, got {type(raw_event).__name__}.",
        )

    if isinstance(raw_event, CalendarEvent):
        event = raw_event
    else:
        try:
            event = CalendarEvent.from_dict(raw_event)
        except Exception as exc:
            title = raw_event.get("title") or f"Event {index + 1}"
            return _ComponentBuildResult(None, None, f"Skipping '{title}' - {exc}")

    try:
        window = resolve_event_window(event)
        component = _create_ics_event(event, window)
        return _ComponentBuildResult(event, component, window.warning)
    except Exception as exc:
        message = _build_error_message(index, event.title, exc)
        logger.error(message)
        return _ComponentBuildResult(None, None, message)


def _build_error_message(index: int, title: str, error: Exception) -> str:
    return f"Error building ICS for event {index + 1} ({title}): {error}"


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


def _create_ics_event(event: CalendarEvent, window: ResolvedEventWindow) -> Event:
    """Create an ICS event component.

    Args:
        event: Validated source event.
        window: Resolved date or UTC datetime boundaries.

    Returns:
        An Event component ready to add to a calendar.
    """
    ve = Event()

    ve.add("UID", event.uid)

    # Use current UTC time for DTSTAMP
    ve.add("DTSTAMP", datetime.now(pytz.utc))

    # Add start and end. icalendar serializes date objects as VALUE=DATE.
    ve.add("DTSTART", window.start)
    ve.add("DTEND", window.end)

    # Add summary (title)
    ve.add("SUMMARY", vText(event.title))

    # Add optional location
    if event.location:
        ve.add("LOCATION", vText(event.location))

    # Add optional description
    if event.description:
        ve.add("DESCRIPTION", vText(event.description))

    # Add a reminder alarm
    alarm = Alarm()
    alarm.add("ACTION", "DISPLAY")
    alarm.add("DESCRIPTION", "Reminder")
    if window.all_day:
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
