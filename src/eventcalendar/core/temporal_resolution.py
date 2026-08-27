"""Resolve validated calendar events into concrete date/time windows.

This module owns calendar semantics such as DST handling, cross-midnight
inference, and timezone jumps.  Output serializers consume the resolved
window without having to reinterpret the source event.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Union

import pytz
from dateutil import parser

from eventcalendar.core.event_model import CalendarEvent
from eventcalendar.core.timezone_utils import (
    attach_timezone_with_warnings,
    extract_timezone_from_time_string,
    normalize_time_string,
    resolve_timezone,
)

logger = logging.getLogger(__name__)

ResolvedBoundary = Union[date, datetime]


@dataclass(frozen=True)
class ResolvedEventWindow:
    """A validated event's concrete start/end values and diagnostics."""

    start: ResolvedBoundary
    end: ResolvedBoundary
    all_day: bool
    warning: str | None = None


def resolve_event_window(event: CalendarEvent) -> ResolvedEventWindow:
    """Resolve an event without coupling calendar policy to an exporter."""
    if event.all_day:
        start, end = _resolve_all_day_dates(event)
        return ResolvedEventWindow(start=start, end=end, all_day=True)

    start, end, warning = _resolve_timed_window(event)
    return ResolvedEventWindow(
        start=start,
        end=end,
        all_day=False,
        warning=warning,
    )


def _resolve_all_day_dates(event: CalendarEvent) -> tuple[date, date]:
    """Return RFC 5545 start and exclusive end dates for an all-day event."""
    start_day = date.fromisoformat(event.date)
    last_day = date.fromisoformat(event.end_date) if event.end_date else start_day
    if last_day < start_day:
        raise ValueError(
            f"All-day end date ({last_day.isoformat()}) is before start date "
            f"({start_day.isoformat()})."
        )
    return start_day, last_day + timedelta(days=1)


def _resolve_timed_window(event: CalendarEvent) -> tuple[datetime, datetime, str | None]:
    """Resolve a timed event into UTC while preserving established inference rules."""
    try:
        if event.start_time is None or event.end_time is None:
            raise ValueError("Timed events require start_time and end_time")

        warnings: list[str] = []
        event_date = date.fromisoformat(event.date)
        end_date = date.fromisoformat(event.end_date or event.date)

        start_time_raw = normalize_time_string(event.start_time)
        end_time_raw = normalize_time_string(event.end_time)

        base_tz_str = event.timezone or "local"
        start_tz_str = event.start_timezone or base_tz_str
        explicit_end_timezone = event.end_timezone is not None
        end_tz_str = event.end_timezone or start_tz_str

        start_time_str, start_tz_from_time = extract_timezone_from_time_string(start_time_raw)
        end_time_str, end_tz_from_time = extract_timezone_from_time_string(end_time_raw)
        if start_tz_from_time:
            start_tz_str = start_tz_from_time
        if end_tz_from_time:
            end_tz_str = end_tz_from_time
        elif not explicit_end_timezone:
            end_tz_str = start_tz_str

        start_tz, start_tz_warning = resolve_timezone(start_tz_str, event.title)
        end_tz, end_tz_warning = resolve_timezone(end_tz_str, event.title)
        if start_tz_warning:
            warnings.append(f"Start time: {start_tz_warning}")
        if end_tz_warning and end_tz_warning != start_tz_warning:
            warnings.append(f"End time: {end_tz_warning}")

        start_time = parser.parse(start_time_str).time()
        end_time = parser.parse(end_time_str).time()
        start_naive = datetime.combine(event_date, start_time)
        end_naive = datetime.combine(end_date, end_time)

        start_dt, start_dst_warning = attach_timezone_with_warnings(start_tz, start_naive)
        end_dt, end_dst_warning = attach_timezone_with_warnings(end_tz, end_naive)
        if start_dst_warning:
            warnings.append(f"Start time: {start_dst_warning}")
        if end_dst_warning:
            warnings.append(f"End time: {end_dst_warning}")

        start_utc = start_dt.astimezone(pytz.utc)
        end_utc = end_dt.astimezone(pytz.utc)

        if end_utc <= start_utc:
            if event.end_date is not None:
                raise ValueError(
                    f"End time ({end_utc.isoformat()}) is not after start time "
                    f"({start_utc.isoformat()}) after timezone conversion."
                )

            naive_duration = end_naive - start_naive
            same_timezone = _timezone_key(start_tz) == _timezone_key(end_tz)

            if naive_duration == timedelta(0) and same_timezone:
                candidate_end = start_dt + timedelta(hours=1)
                if hasattr(end_tz, "normalize"):
                    candidate_end = end_tz.normalize(candidate_end)
                end_dt = candidate_end
                end_utc = candidate_end.astimezone(pytz.utc)
                warnings.append("End time equals start time; assumed a 1-hour duration.")

            if naive_duration > timedelta(0) and same_timezone:
                candidate_end = start_dt + naive_duration
                if hasattr(end_tz, "normalize"):
                    candidate_end = end_tz.normalize(candidate_end)
                candidate_utc = candidate_end.astimezone(pytz.utc)
                if candidate_utc > start_utc:
                    end_dt = candidate_end
                    end_utc = candidate_utc
                    warnings.append(
                        "End time was not after start after DST/timezone resolution; "
                        "preserved the original duration instead of rolling the end date."
                    )

            if end_utc <= start_utc:
                adjusted = False
                for days in (1, 2):
                    candidate_naive = end_naive + timedelta(days=days)
                    candidate_end, candidate_warning = attach_timezone_with_warnings(
                        end_tz,
                        candidate_naive,
                    )
                    candidate_utc = candidate_end.astimezone(pytz.utc)
                    if candidate_utc <= start_utc:
                        continue

                    end_dt = candidate_end
                    end_utc = candidate_utc
                    adjusted = True
                    warnings.append(
                        "End time occurred before start after timezone conversion; "
                        f"assumed the end date is {candidate_naive.date().isoformat()}."
                    )
                    if candidate_warning:
                        warnings.append(f"End time: {candidate_warning}")
                    break

                if not adjusted:
                    raise ValueError(
                        f"End time ({end_utc.isoformat()}) is not after start time "
                        f"({start_utc.isoformat()}) after timezone conversion."
                    )

        return start_utc, end_utc, "\n".join(warnings) if warnings else None
    except Exception as exc:
        logger.warning(
            "Skipping event '%s' due to date/time parsing error: %s",
            event.title,
            exc,
        )
        raise


def _timezone_key(tzobj: object) -> str:
    """Return a stable comparison key for pytz, zoneinfo, and dateutil zones."""
    return str(getattr(tzobj, "zone", getattr(tzobj, "key", str(tzobj))))
