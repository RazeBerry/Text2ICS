"""Regression guards for typed temporal resolution and direct calendar assembly."""

from __future__ import annotations

from icalendar import Calendar

from eventcalendar.core.event_model import CalendarEvent
from eventcalendar.core.ics_builder import build_merged_ics


def _event(title: str = "Review") -> dict:
    return {
        "title": title,
        "start_time": "10:00",
        "end_time": "11:00",
        "date": "2026-09-01",
        "timezone": "Europe/Paris",
        "description": "Roadmap",
        "location": "Room 1",
    }


def test_build_merged_ics_constructs_one_valid_calendar_with_import_uids() -> None:
    result = build_merged_ics([_event("One"), _event("Two")])

    assert result.ics_content is not None
    assert result.skipped_events == []
    assert result.warnings == []
    calendar = Calendar.from_ical(result.ics_content)
    events = list(calendar.walk("VEVENT"))
    assert [str(event["SUMMARY"]) for event in events] == ["One", "Two"]
    uids = [str(event["UID"]) for event in events]
    assert len(set(uids)) == 2
    assert all(uid.endswith("@nl-calendar") for uid in uids)
    assert "\r\n" in result.ics_content


def test_build_merged_ics_preserves_partial_success_diagnostics() -> None:
    result = build_merged_ics([{"title": "Incomplete"}, _event()])

    assert result.ics_content is not None
    assert len(result.created_events) == 1
    assert len(result.skipped_events) == 1
    assert "Incomplete" in result.skipped_events[0]


def test_build_merged_ics_accepts_a_validated_model_without_revalidation(monkeypatch) -> None:
    model = CalendarEvent.from_dict(_event())

    def fail_revalidation(*_args, **_kwargs):
        raise AssertionError("validated models must not be parsed again")

    monkeypatch.setattr(CalendarEvent, "from_dict", fail_revalidation)
    result = build_merged_ics((model,))

    assert result.ics_content is not None
    assert len(result.created_events) == 1
