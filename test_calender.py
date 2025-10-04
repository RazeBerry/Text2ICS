from typing import Any

import pytest
from icalendar import Calendar
from PyQt6.QtWidgets import QApplication

import Calender


@pytest.fixture(scope="module")
def qt_app() -> QApplication:
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


def test_combine_ics_strings_preserves_timezone_and_rewrites_uids() -> None:
    long_uid = "event-two-super-long-uid-example-12345678901234567890"
    folded_uid = f"UID:{long_uid[:28]}\r\n {long_uid[28:]}"

    ics_one = (
        "BEGIN:VCALENDAR\r\n"
        "VERSION:2.0\r\n"
        "PRODID:-//Test//EN\r\n"
        "CALSCALE:GREGORIAN\r\n"
        "BEGIN:VTIMEZONE\r\n"
        "TZID:Europe/London\r\n"
        "BEGIN:STANDARD\r\n"
        "DTSTART:20241027T010000\r\n"
        "TZOFFSETFROM:+0100\r\n"
        "TZOFFSETTO:+0000\r\n"
        "TZNAME:GMT\r\n"
        "END:STANDARD\r\n"
        "END:VTIMEZONE\r\n"
        "BEGIN:VEVENT\r\n"
        "UID:event-one@example.com\r\n"
        "DTSTAMP:20240101T000000Z\r\n"
        "DTSTART;TZID=Europe/London:20241029T170000\r\n"
        "DTEND;TZID=Europe/London:20241029T180000\r\n"
        "SUMMARY:Event One\r\n"
        "END:VEVENT\r\n"
        "END:VCALENDAR\r\n"
    )

    ics_two = (
        "BEGIN:VCALENDAR\r\n"
        "VERSION:2.0\r\n"
        "PRODID:-//Second//EN\r\n"
        "METHOD:PUBLISH\r\n"
        "BEGIN:VEVENT\r\n"
        f"{folded_uid}\r\n"
        "DTSTAMP:20240101T010000Z\r\n"
        "DTSTART:20241030T160000Z\r\n"
        "DTEND:20241030T170000Z\r\n"
        "SUMMARY:Event Two\r\n"
        "END:VEVENT\r\n"
        "END:VCALENDAR\r\n"
    )

    combined = Calender.combine_ics_strings([ics_one, ics_two])
    merged = Calendar.from_ical(combined.encode("utf-8"))

    vevents = list(merged.walk("VEVENT"))
    assert len(vevents) == 2
    for event in vevents:
        uid = str(event.get("UID"))
        assert uid.endswith("@nl-calendar")
        assert "\n" not in uid

    timezones = [comp for comp in merged.walk("VTIMEZONE")]
    assert len(timezones) == 1
    assert str(timezones[0].get("TZID")) == "Europe/London"

    assert merged.get("METHOD") == "PUBLISH"

    lines = combined.splitlines()
    assert not any(line.startswith(" UID:") for line in lines)


def test_combine_ics_strings_requires_input() -> None:
    with pytest.raises(ValueError):
        Calender.combine_ics_strings([])


def test_process_event_uses_daemon_thread(qt_app: QApplication, monkeypatch: pytest.MonkeyPatch) -> None:
    window = Calender.NLCalendarCreator()
    window.api_client = object()
    window.text_input.setPlainText("Test event at 7pm tomorrow")

    created_thread: dict[str, Any] = {}

    class DummyThread:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            created_thread["args"] = args
            created_thread["kwargs"] = kwargs

        def start(self) -> None:
            created_thread["started"] = True

    monkeypatch.setattr(Calender.threading, "Thread", DummyThread)

    window.process_event()

    assert created_thread["kwargs"]["daemon"] is True

    with window._threads_lock:
        window._active_threads.clear()

    window.close()
