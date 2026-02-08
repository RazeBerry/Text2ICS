import os
import subprocess
import sys
from datetime import datetime
from typing import Any

import pytest
from icalendar import Calendar

# Ensure local imports work without requiring an editable install.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))

from eventcalendar.core.ics_builder import combine_ics_strings
from eventcalendar.ui.preview import parse_event_text, format_date_display
from eventcalendar.ui.theme.colors import COLORS


def _pyqt6_importable() -> bool:
    """Check PyQt6 importability in a subprocess to avoid hard crashes in-process."""
    result = subprocess.run(
        [sys.executable, "-c", "import PyQt6.QtWidgets"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    return result.returncode == 0


RUN_UI_TESTS = os.environ.get("EVENTCALENDAR_RUN_UI_TESTS") == "1"
UI_AVAILABLE = RUN_UI_TESTS and _pyqt6_importable()


@pytest.fixture(scope="module")
def qt_app() -> Any:
    if not UI_AVAILABLE:
        pytest.skip("UI tests disabled (set EVENTCALENDAR_RUN_UI_TESTS=1 to enable).")
    from PyQt6.QtWidgets import QApplication

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

    combined = combine_ics_strings([ics_one, ics_two])
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
        combine_ics_strings([])


def test_parse_event_text_extracts_components() -> None:
    ref = datetime(2024, 4, 1, 12, 0, 0)
    parsed = parse_event_text("Dinner with Mia next Tuesday at 7pm", reference_date=ref)

    assert parsed["title"] == "Dinner Mia at"
    assert parsed["date"] == "Apr 09"
    assert parsed["time"] == "7pm"
    assert parsed["location"] is None


def test_parse_event_text_handles_simple_title() -> None:
    parsed = parse_event_text("Project kickoff", reference_date=datetime(2024, 4, 1, 12, 0, 0))

    assert parsed["title"] == "Project kickoff"
    assert parsed["date"] is None
    assert parsed["time"] is None


def test_format_date_display_handles_relative_terms() -> None:
    ref = datetime(2024, 4, 1, 12, 0, 0)
    assert format_date_display("today", reference_date=ref) == "Apr 01"
    assert format_date_display("tomorrow", reference_date=ref) == "Apr 02"
    assert format_date_display("next friday", reference_date=ref) == "Apr 12"
    assert format_date_display("March 30", reference_date=ref) == "Mar 30"


@pytest.mark.skipif(not UI_AVAILABLE, reason="UI tests disabled (set EVENTCALENDAR_RUN_UI_TESTS=1 to enable).")
def test_process_event_uses_executor(qt_app: Any) -> None:
    """Verify process_event uses ThreadPoolExecutor for background work."""
    from eventcalendar.ui.main_window import NLCalendarCreator

    window = NLCalendarCreator()
    window.api_client = object()
    window.text_input.setPlainText("Test event at 7pm tomorrow")

    submitted_tasks: list[dict[str, Any]] = []

    class MockFuture:
        def add_done_callback(self, callback: Any) -> None:
            pass

    def mock_submit(fn: Any, *args: Any, **kwargs: Any) -> MockFuture:
        submitted_tasks.append({"fn": fn, "args": args, "kwargs": kwargs})
        return MockFuture()

    window._executor.submit = mock_submit
    window.process_event()

    assert len(submitted_tasks) == 1
    assert submitted_tasks[0]["fn"] == window._create_event_thread
    assert hasattr(window, "_executor")
    assert window._executor is not None

    window.close()


@pytest.mark.skipif(not UI_AVAILABLE, reason="UI tests disabled (set EVENTCALENDAR_RUN_UI_TESTS=1 to enable).")
def test_update_live_preview_populates_content(qt_app: Any) -> None:
    from eventcalendar.ui.main_window import NLCalendarCreator

    window = NLCalendarCreator()
    ref = datetime(2024, 4, 1, 12, 0, 0)
    window.parse_event_text = lambda text: parse_event_text(text, reference_date=ref)  # type: ignore[assignment]

    window.text_input.setPlainText("Dinner with Mia next Tuesday at 7pm")
    window.update_live_preview()

    assert window.preview_event_title.text() == "Dinner Mia at \u2022 Apr 09 \u2022 7pm"
    assert f"color: {COLORS['text_primary']}" in window.preview_event_title.styleSheet()

    window.close()


@pytest.mark.skipif(not UI_AVAILABLE, reason="UI tests disabled (set EVENTCALENDAR_RUN_UI_TESTS=1 to enable).")
def test_update_live_preview_resets_to_placeholder(qt_app: Any) -> None:
    from eventcalendar.ui.main_window import NLCalendarCreator

    window = NLCalendarCreator()
    ref = datetime(2024, 4, 1, 12, 0, 0)
    window.parse_event_text = lambda text: parse_event_text(text, reference_date=ref)  # type: ignore[assignment]

    window.text_input.setPlainText("Project kickoff")
    window.update_live_preview()

    assert window.preview_event_title.text() == "Project kickoff \u2022 Date \u2022 Time"
    assert f"color: {COLORS['text_primary']}" in window.preview_event_title.styleSheet()

    window.text_input.setPlainText("")
    window.update_live_preview()

    assert window.preview_event_title.text() == "Event title \u2022 Date \u2022 Time"
    assert f"color: {COLORS['text_tertiary']}" in window.preview_event_title.styleSheet()

    window.close()

