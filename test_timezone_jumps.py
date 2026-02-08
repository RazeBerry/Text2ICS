import os
import sys
from datetime import datetime

import pytz
from icalendar import Calendar

# Ensure local imports work without requiring an editable install.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))

from eventcalendar.core.ics_builder import build_ics_from_events


def _get_vevent(ics_text: str):
    cal = Calendar.from_ical(ics_text.encode("utf-8"))
    return next(comp for comp in cal.walk() if comp.name == "VEVENT")


def test_dst_nonexistent_time_shifts_forward() -> None:
    # America/New_York spring-forward (02:00 -> 03:00) in 2024 happens on March 10.
    event = {
        "uid": "dst-gap",
        "title": "DST Gap",
        "start_time": "2:30 AM",
        "end_time": "3:30 AM",
        "date": "2024-03-10",
        "timezone": "America/New_York",
    }

    ics_strings, warnings = build_ics_from_events([event])
    assert len(ics_strings) == 1
    assert any("DST gap:" in w for w in warnings)
    assert any("preserved the original duration" in w for w in warnings)

    vevent = _get_vevent(ics_strings[0])
    dtstart = vevent.get("DTSTART").dt.astimezone(pytz.utc)
    dtend = vevent.get("DTEND").dt.astimezone(pytz.utc)

    # 02:30 is in the DST spring-forward gap; it is shifted forward by one hour.
    assert dtstart == datetime(2024, 3, 10, 7, 30, 0, tzinfo=pytz.utc)
    # Preserve the original intended duration (1 hour) rather than rolling the date.
    assert dtend == datetime(2024, 3, 10, 8, 30, 0, tzinfo=pytz.utc)


def test_dst_ambiguous_time_chooses_later_occurrence_by_default() -> None:
    # America/New_York fall-back in 2024 happens on Nov 3; 01:30 occurs twice.
    event = {
        "uid": "dst-fallback",
        "title": "DST Fall Back",
        "start_time": "1:30 AM",
        "end_time": "2:30 AM",
        "date": "2024-11-03",
        "timezone": "America/New_York",
    }

    ics_strings, warnings = build_ics_from_events([event])
    assert len(ics_strings) == 1
    assert any("DST ambiguity:" in w for w in warnings)

    vevent = _get_vevent(ics_strings[0])
    dtstart = vevent.get("DTSTART").dt.astimezone(pytz.utc)
    dtend = vevent.get("DTEND").dt.astimezone(pytz.utc)

    # Default policy chooses the later (standard-time) instance: EST (UTC-5).
    assert dtstart == datetime(2024, 11, 3, 6, 30, 0, tzinfo=pytz.utc)
    # 02:30 after fall-back is EST (UTC-5): 02:30 -> 07:30Z
    assert dtend == datetime(2024, 11, 3, 7, 30, 0, tzinfo=pytz.utc)


def test_start_end_timezones_supported_for_travel() -> None:
    event = {
        "uid": "flight-1",
        "title": "Flight LA → NYC",
        "start_time": "10:00 AM",
        "end_time": "6:00 PM",
        "date": "2024-04-01",
        "timezone": "local",
        "start_timezone": "America/Los_Angeles",
        "end_timezone": "America/New_York",
    }

    ics_strings, warnings = build_ics_from_events([event])
    assert len(ics_strings) == 1
    assert warnings == []

    vevent = _get_vevent(ics_strings[0])
    dtstart = vevent.get("DTSTART").dt.astimezone(pytz.utc)
    dtend = vevent.get("DTEND").dt.astimezone(pytz.utc)

    # Apr 1, 2024: Los Angeles is PDT (UTC-7), New York is EDT (UTC-4)
    assert dtstart == datetime(2024, 4, 1, 17, 0, 0, tzinfo=pytz.utc)
    assert dtend == datetime(2024, 4, 1, 22, 0, 0, tzinfo=pytz.utc)


def test_end_before_start_rolls_to_next_day() -> None:
    event = {
        "uid": "overnight",
        "title": "Overnight",
        "start_time": "11:00 PM",
        "end_time": "1:00 AM",
        "date": "2024-04-01",
        "timezone": "UTC",
    }

    ics_strings, warnings = build_ics_from_events([event])
    assert len(ics_strings) == 1
    assert any("assumed the end date is 2024-04-02" in w for w in warnings)

    vevent = _get_vevent(ics_strings[0])
    dtstart = vevent.get("DTSTART").dt.astimezone(pytz.utc)
    dtend = vevent.get("DTEND").dt.astimezone(pytz.utc)

    assert dtstart == datetime(2024, 4, 1, 23, 0, 0, tzinfo=pytz.utc)
    assert dtend == datetime(2024, 4, 2, 1, 0, 0, tzinfo=pytz.utc)
