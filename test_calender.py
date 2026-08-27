import os
import subprocess
import sys
import tempfile
import threading
import time
from datetime import datetime, timedelta
from typing import Any

import pytest
from icalendar import Calendar

# Ensure local imports work without requiring an editable install.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))

from eventcalendar.core.ics_builder import build_ics_from_events, combine_ics_strings
from eventcalendar.core.timezone_utils import (
    _parse_utc_offset_seconds,
    extract_timezone_from_time_string,
)
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


def _wait_for_ui(qt_app: Any, predicate, timeout: float = 2.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        qt_app.processEvents()
        if predicate():
            return
        time.sleep(0.005)
    raise AssertionError("condition was not reached before timeout")


@pytest.fixture(autouse=True)
def isolate_ui_storage_threads(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep UI integration tests deterministic by disabling background keyring warmup."""
    if not UI_AVAILABLE:
        return

    from eventcalendar.ui import main_window

    monkeypatch.setattr(main_window, "load_api_key", lambda: "AIzaUiTestKey")
    monkeypatch.setattr(main_window, "check_and_warn_legacy_storage", lambda: None)
    monkeypatch.setattr(main_window.NLCalendarCreator, "_warm_storage_state_async", lambda self: None)


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


def test_combine_ics_strings_produces_structurally_valid_output() -> None:
    """Guard against merged headers leaking VEVENT/VALARM properties (Fix 1).

    Validated textually rather than through icalendar's lenient parser, which
    would silently tolerate an unbalanced BEGIN/END structure.
    """
    events = [
        {
            "uid": "u1", "title": "Dinner", "start_time": "7:00 PM",
            "end_time": "9:00 PM", "date": "2026-07-09",
            "timezone": "America/New_York", "location": "Cafe", "description": "x",
        },
        {
            "uid": "u2", "title": "Flight", "start_time": "8:00 AM",
            "end_time": "4:30 PM", "date": "2026-07-10",
            "timezone": "America/Los_Angeles", "end_timezone": "America/New_York",
        },
    ]

    ics_strings, _warnings = build_ics_from_events(events)
    combined = combine_ics_strings(ics_strings)
    lines = [line for line in combined.split("\r\n") if line]

    assert lines.count("BEGIN:VCALENDAR") == 1
    assert lines.count("END:VCALENDAR") == 1
    assert lines[0] == "BEGIN:VCALENDAR"
    assert lines[-1] == "END:VCALENDAR"

    assert lines.count("BEGIN:VEVENT") == lines.count("END:VEVENT") == 2
    assert lines.count("BEGIN:VALARM") == lines.count("END:VALARM") == 2

    first_vevent = lines.index("BEGIN:VEVENT")
    forbidden = (
        "DTSTART", "DTEND", "DTSTAMP", "SUMMARY", "UID",
        "ACTION", "TRIGGER", "DESCRIPTION", "LOCATION", "END:VALARM",
    )
    for line in lines[:first_vevent]:
        assert not any(line.startswith(prefix) for prefix in forbidden), (
            f"Header leak before first VEVENT: {line!r}"
        )


def test_zero_duration_event_assumes_one_hour() -> None:
    """A start == end time should yield a 1-hour event, not a 24-hour one (Fix 3)."""
    events = [{
        "uid": "z1", "title": "Dinner", "start_time": "7:00 PM",
        "end_time": "7:00 PM", "date": "2026-07-09", "timezone": "America/New_York",
    }]

    ics_strings, warnings = build_ics_from_events(events)
    assert len(ics_strings) == 1

    vevent = list(Calendar.from_ical(ics_strings[0].encode("utf-8")).walk("VEVENT"))[0]
    dtstart = vevent.get("DTSTART").dt
    dtend = vevent.get("DTEND").dt

    assert dtend - dtstart == timedelta(hours=1)
    assert any("1-hour duration" in w for w in warnings)


def test_cross_midnight_event_rolls_end_date() -> None:
    """A genuine cross-midnight event must still roll the end date (Fix 3 regression)."""
    events = [{
        "uid": "cm1", "title": "Late night", "start_time": "11:00 PM",
        "end_time": "1:00 AM", "date": "2026-07-09", "timezone": "America/New_York",
    }]

    ics_strings, _warnings = build_ics_from_events(events)
    assert len(ics_strings) == 1

    vevent = list(Calendar.from_ical(ics_strings[0].encode("utf-8")).walk("VEVENT"))[0]
    dtstart = vevent.get("DTSTART").dt
    dtend = vevent.get("DTEND").dt

    assert dtend > dtstart
    assert dtend - dtstart == timedelta(hours=2)


def test_all_day_event_uses_value_date() -> None:
    ics_strings, warnings = build_ics_from_events([
        {"title": "Street Festival", "date": "2026-08-15", "all_day": True}
    ])

    assert warnings == []
    assert len(ics_strings) == 1
    lines = ics_strings[0].split("\r\n")
    assert "DTSTART;VALUE=DATE:20260815" in lines
    # RFC 5545: all-day DTEND is exclusive (the day after the last day).
    assert "DTEND;VALUE=DATE:20260816" in lines
    assert "TRIGGER:PT9H" in lines


def test_all_day_multi_day_event_has_exclusive_end() -> None:
    ics_strings, warnings = build_ics_from_events([
        {"title": "Festival", "date": "2026-08-15", "end_date": "2026-08-17", "all_day": True}
    ])

    assert warnings == []
    lines = ics_strings[0].split("\r\n")
    assert "DTSTART;VALUE=DATE:20260815" in lines
    assert "DTEND;VALUE=DATE:20260818" in lines


def test_missing_uid_and_timezone_are_defaulted() -> None:
    ics_strings, warnings = build_ics_from_events([
        {"title": "Meeting", "start_time": "10:00", "end_time": "11:00", "date": "2026-08-15"}
    ])

    assert warnings == []
    assert len(ics_strings) == 1
    assert any(line.startswith("UID:") for line in ics_strings[0].split("\r\n"))


@pytest.mark.parametrize(
    "time_str,expected",
    [
        ("19:30-20:00", ("19:30-20:00", None)),
        ("10:00-11:30", ("10:00-11:30", None)),
        ("7:30 PM - 9:00 PM", ("7:30 PM - 9:00 PM", None)),
        ("19:30+0200", ("19:30", "+0200")),
        ("19:30Z", ("19:30", "Z")),
        ("7pm CET", ("7pm", "CET")),
        ("7:30 PM EST", ("7:30 PM", "EST")),
        ("10:00 (America/Los_Angeles)", ("10:00", "America/Los_Angeles")),
    ],
)
def test_extract_timezone_from_time_string(time_str: str, expected: tuple) -> None:
    assert extract_timezone_from_time_string(time_str) == expected


@pytest.mark.parametrize(
    "offset,expected",
    [
        ("+15:00", None),
        ("-13:00", None),
        ("+14:00", 50400),
        ("-12:00", -43200),
        ("+05:45", 20700),
    ],
)
def test_parse_utc_offset_seconds_range(offset: str, expected: Any) -> None:
    assert _parse_utc_offset_seconds(offset) == expected


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
def test_process_event_submits_to_creation_controller(qt_app: Any) -> None:
    """Verify process_event crosses the explicit controller boundary."""
    from eventcalendar.ui.main_window import NLCalendarCreator

    window = NLCalendarCreator()
    window.text_input.setPlainText("Test event at 7pm tomorrow")
    window._prefetched_api_key = "AIzaControllerTest"
    window._ensure_api_client = lambda: True  # type: ignore[assignment]

    submitted: list[tuple[Any, ...]] = []

    window._creation_controller.submit = lambda *args: submitted.append(args)  # type: ignore[method-assign]
    window.process_event()

    assert len(submitted) == 1
    assert submitted[0][0] == "Test event at 7pm tomorrow"
    assert submitted[0][2] == "AIzaControllerTest"

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


@pytest.mark.skipif(not UI_AVAILABLE, reason="UI tests disabled (set EVENTCALENDAR_RUN_UI_TESTS=1 to enable).")
def test_overlay_is_built_lazily(qt_app: Any) -> None:
    from eventcalendar.ui.main_window import NLCalendarCreator

    window = NLCalendarCreator()
    window.show()
    qt_app.processEvents()
    assert window.overlay is None

    window._show_progress(True)
    qt_app.processEvents()
    assert window.overlay is not None
    assert window.overlay.isVisible()

    window.resize(window.width() + 40, window.height() + 20)
    qt_app.processEvents()
    assert window.overlay.geometry() == window.centralWidget().rect()

    window._show_progress(False)
    assert not window.overlay.isVisible()
    window.close()


@pytest.mark.skipif(not UI_AVAILABLE, reason="UI tests disabled (set EVENTCALENDAR_RUN_UI_TESTS=1 to enable).")
def test_ensure_api_client_only_checks_key_not_client_init(qt_app: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    from eventcalendar.ui.main_window import NLCalendarCreator

    window = NLCalendarCreator()
    monkeypatch.setattr("eventcalendar.ui.main_window.load_api_key", lambda: "AIzaFakeForTest")

    assert window._ensure_api_client() is True
    assert window.api_client is None
    assert window._prefetched_api_key == "AIzaFakeForTest"
    window.close()


@pytest.mark.skipif(not UI_AVAILABLE, reason="UI tests disabled (set EVENTCALENDAR_RUN_UI_TESTS=1 to enable).")
def test_process_event_passes_api_key_to_worker(qt_app: Any) -> None:
    from eventcalendar.ui.main_window import NLCalendarCreator

    window = NLCalendarCreator()
    window.text_input.setPlainText("Test event tomorrow at 7pm")
    window._prefetched_api_key = "AIzaFromPrefetch"
    window._ensure_api_client = lambda: True  # type: ignore[assignment]

    submitted: list[tuple[Any, ...]] = []
    window._creation_controller.submit = lambda *args: submitted.append(args)  # type: ignore[method-assign]
    window.process_event()

    assert len(submitted) == 1
    assert submitted[0][2] == "AIzaFromPrefetch"
    window.close()


@pytest.mark.skipif(not UI_AVAILABLE, reason="UI tests disabled (set EVENTCALENDAR_RUN_UI_TESTS=1 to enable).")
def test_worker_initializes_client_and_handles_empty_events(
    qt_app: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    from eventcalendar.ui.main_window import NLCalendarCreator
    import eventcalendar.core.api_client as api_client_module

    window = NLCalendarCreator()
    window._setup_overlay()
    statuses: list[str] = []
    terminal_statuses: list[str] = []
    enabled: list[bool] = []
    progress: list[bool] = []
    window._creation_controller.status_changed.connect(statuses.append)
    window._update_status = terminal_statuses.append  # type: ignore[method-assign]
    window._set_ui_enabled = enabled.append  # type: ignore[method-assign]
    window._show_progress = progress.append  # type: ignore[method-assign]

    class FakeClient:
        def __init__(self, api_key: str):
            self.api_key = api_key

        def extract_events(
            self,
            event_description: str,
            image_data: list[Any],
            status_callback: Any,
            cancel_event: Any,
        ) -> Any:
            from eventcalendar.core.api_client import ExtractionResult

            assert event_description == "demo"
            assert image_data == []
            assert not cancel_event.is_set()
            return ExtractionResult([])

        def close(self) -> None:
            pass

    monkeypatch.setattr(api_client_module, "CalendarAPIClient", FakeClient)
    extraction = window._creation_controller._run("demo", (), "AIzaFakeKey")
    window._handle_creation_completed(extraction)
    qt_app.processEvents()

    assert isinstance(window.api_client, FakeClient)
    assert statuses[0] == "Initializing AI client..."
    assert terminal_statuses == ["No events found"]
    assert enabled[-1] is True
    assert progress[-1] is False
    window.close()


@pytest.mark.skipif(not UI_AVAILABLE, reason="UI tests disabled (set EVENTCALENDAR_RUN_UI_TESTS=1 to enable).")
def test_overlay_cancel_restores_usable_window(qt_app: Any) -> None:
    from concurrent.futures import CancelledError

    from eventcalendar.ui.event_creation_controller import JobState
    from eventcalendar.ui.main_window import NLCalendarCreator

    started = threading.Event()

    class FakeClient:
        def extract_events(self, *_args: Any, cancel_event: threading.Event, **_kwargs: Any):
            started.set()
            assert cancel_event.wait(2)
            raise CancelledError("cancelled by user")

        def close(self) -> None:
            pass

    window = NLCalendarCreator()
    window.text_input.setPlainText("Meeting tomorrow at 7pm")
    window._prefetched_api_key = "AIzaCancelTest"
    window._ensure_api_client = lambda: True  # type: ignore[assignment]
    window._creation_controller.set_client_for_testing(FakeClient())
    window.show()
    qt_app.processEvents()

    window.process_event()
    assert started.wait(1)
    _wait_for_ui(qt_app, lambda: window.overlay is not None and window.overlay.isVisible())
    assert window.overlay is not None
    window.overlay.cancel_button.click()
    _wait_for_ui(
        qt_app,
        lambda: (
            window._creation_controller.state is JobState.IDLE
            and not window.overlay.isVisible()
        ),
    )

    assert not window.overlay.isVisible()
    assert window.text_input.isEnabled()
    assert window.create_button.isEnabled()
    window.close()


@pytest.mark.skipif(not UI_AVAILABLE, reason="UI tests disabled (set EVENTCALENDAR_RUN_UI_TESTS=1 to enable).")
def test_build_merged_ics_uses_non_blocking_warning_notice(
    qt_app: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    from eventcalendar.ui.main_window import NLCalendarCreator
    from PyQt6.QtWidgets import QMessageBox
    import eventcalendar.core.ics_builder as ics_builder_module

    window = NLCalendarCreator()
    notices: list[tuple[str, int]] = []
    window._show_transient_notice = lambda message, timeout_ms=6000: notices.append((message, timeout_ms))  # type: ignore[assignment]

    monkeypatch.setattr(
        ics_builder_module,
        "build_merged_ics",
        lambda events: ics_builder_module.ICSMergedResult(
            "BEGIN:VCALENDAR\r\nEND:VCALENDAR\r\n",
            events,
            [],
            ["Timezone warning"],
        ),
    )

    def fail_if_modal(*_args: Any, **_kwargs: Any) -> None:
        raise AssertionError("Blocking warning dialog should not be used.")

    monkeypatch.setattr(QMessageBox, "warning", fail_if_modal)
    merged, created_count, warnings = window._build_merged_ics([{"uid": "1"}])

    assert merged.startswith("BEGIN:VCALENDAR")
    assert created_count == 1
    assert warnings == ["Timezone warning"]

    window._clear_inputs = lambda: None  # type: ignore[assignment]
    window._show_success(created_count, 1, warnings)

    assert notices
    assert "with warning:" in notices[0][0]
    window.close()


@pytest.mark.skipif(not UI_AVAILABLE, reason="UI tests disabled (set EVENTCALENDAR_RUN_UI_TESTS=1 to enable).")
def test_show_success_reports_skipped_events_persistently(qt_app: Any) -> None:
    from eventcalendar.ui.main_window import NLCalendarCreator

    window = NLCalendarCreator()
    notices: list[tuple[str, int]] = []
    cleared: list[bool] = []
    window._show_transient_notice = lambda message, timeout_ms=6000: notices.append((message, timeout_ms))  # type: ignore[assignment]
    window._clear_inputs = lambda: cleared.append(True)  # type: ignore[assignment]

    window._show_success(3, 5, ["Skipping 'X' - missing required fields: {'date'}"])

    assert notices
    message, timeout_ms = notices[0]
    assert message.startswith("Opened 3 of 5 events for import")
    assert "2 skipped" in message
    assert timeout_ms == 0  # persistent until the next status message replaces it
    assert cleared == [True]  # prevents a retry from duplicating successful imports
    window.close()


@pytest.mark.skipif(not UI_AVAILABLE, reason="UI tests disabled (set EVENTCALENDAR_RUN_UI_TESTS=1 to enable).")
def test_show_success_uses_non_blocking_notice(qt_app: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    from eventcalendar.ui.main_window import NLCalendarCreator
    from PyQt6.QtWidgets import QMessageBox

    window = NLCalendarCreator()
    notices: list[str] = []
    cleared: list[bool] = []
    window._show_transient_notice = lambda message, timeout_ms=6000: notices.append(message)  # type: ignore[assignment]
    window._clear_inputs = lambda: cleared.append(True)  # type: ignore[assignment]

    def fail_if_modal(*_args: Any, **_kwargs: Any) -> None:
        raise AssertionError("Blocking success dialog should not be used.")

    monkeypatch.setattr(QMessageBox, "information", fail_if_modal)
    window._show_success(2)

    assert notices == ["2 events opened for calendar import."]
    assert cleared == [True]
    window.close()


@pytest.mark.skipif(not UI_AVAILABLE, reason="UI tests disabled (set EVENTCALENDAR_RUN_UI_TESTS=1 to enable).")
def test_image_area_click_dialog_selects_image(qt_app: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    from eventcalendar.ui.widgets.image_area import ImageAttachmentArea
    from PyQt6.QtWidgets import QFileDialog

    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
        image_path = tmp.name
    from PIL import Image
    Image.new("RGB", (8, 8), "white").save(image_path, format="PNG")

    area = ImageAttachmentArea()
    try:
        monkeypatch.setattr(QFileDialog, "getOpenFileNames", lambda *args, **kwargs: ([image_path], ""))
        area._select_images_from_dialog()

        _wait_for_ui(qt_app, lambda: bool(area.image_data))
        assert len(area.image_data) == 1
        assert area.primary_label.text() == "1 image ready"
        area.reset_state()
        area.close()
    finally:
        os.unlink(image_path)


@pytest.mark.skipif(not UI_AVAILABLE, reason="UI tests disabled (set EVENTCALENDAR_RUN_UI_TESTS=1 to enable).")
def test_image_area_rejects_spoofed_extension(qt_app: Any) -> None:
    from eventcalendar.ui.widgets.image_area import ImageAttachmentArea

    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
        tmp.write(b"not-an-image")
        image_path = tmp.name
    area = ImageAttachmentArea()
    try:
        assert area._create_payload_from_url(image_path) is None
        assert area.image_data == []
    finally:
        area.close()
        os.unlink(image_path)


@pytest.mark.skipif(not UI_AVAILABLE, reason="UI tests disabled (set EVENTCALENDAR_RUN_UI_TESTS=1 to enable).")
def test_api_key_is_hidden_until_user_reveals_it(qt_app: Any) -> None:
    from PyQt6.QtWidgets import QLineEdit
    from eventcalendar.ui.widgets.api_key_dialog import APIKeySetupDialog

    dialog = APIKeySetupDialog()
    try:
        assert dialog.api_key_input.echoMode() == QLineEdit.EchoMode.Password
        dialog.reveal_key_checkbox.setChecked(True)
        assert dialog.api_key_input.echoMode() == QLineEdit.EchoMode.Normal
    finally:
        dialog.close()


@pytest.mark.skipif(not UI_AVAILABLE, reason="UI tests disabled (set EVENTCALENDAR_RUN_UI_TESTS=1 to enable).")
def test_close_cancels_work_closes_client_and_removes_temp_ics(qt_app: Any) -> None:
    from eventcalendar.ui.main_window import NLCalendarCreator

    window = NLCalendarCreator()
    cancelled: list[bool] = []
    closed: list[bool] = []

    class FakeFuture:
        def cancel(self) -> None:
            cancelled.append(True)

    class FakeClient:
        def close(self) -> None:
            closed.append(True)
            raise RuntimeError("simulated transport-close failure")

    with tempfile.NamedTemporaryFile(suffix=".ics", delete=False) as tmp:
        temp_path = tmp.name
    window._creation_controller._futures.add(FakeFuture())
    window.api_client = FakeClient()
    window._temp_ics_paths.add(temp_path)
    window.close()

    assert cancelled == [True]
    assert closed == [True]
    assert not os.path.exists(temp_path)
    assert window._creation_controller._cancel_event.is_set()


@pytest.mark.skipif(not UI_AVAILABLE, reason="UI tests disabled (set EVENTCALENDAR_RUN_UI_TESTS=1 to enable).")
def test_stale_storage_warmup_cannot_overwrite_interactive_key(
    qt_app: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    from eventcalendar.ui.main_window import NLCalendarCreator
    import eventcalendar.ui.main_window as main_window_module

    started = threading.Event()
    release = threading.Event()

    def stale_load() -> None:
        started.set()
        assert release.wait(2)
        return None

    monkeypatch.setattr(main_window_module, "load_api_key", stale_load)
    window = NLCalendarCreator(prompt_for_api_key=True)
    prompts: list[bool] = []
    window.api_key_required_signal.connect(lambda: prompts.append(True))
    worker = threading.Thread(target=window._storage_warmup_worker)
    worker.start()
    assert started.wait(1)

    window._publish_interactive_api_key("NEWLY_SAVED_KEY")
    release.set()
    worker.join(timeout=2)
    qt_app.processEvents()

    assert not worker.is_alive()
    assert window._prefetched_api_key == "NEWLY_SAVED_KEY"
    assert window._prefetch_ready.is_set()
    assert prompts == []
    window.close()


@pytest.mark.skipif(not UI_AVAILABLE, reason="UI tests disabled (set EVENTCALENDAR_RUN_UI_TESTS=1 to enable).")
def test_finalization_prefers_extraction_models_without_revalidation(
    qt_app: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    from PyQt6.QtWidgets import QMessageBox
    from eventcalendar.core.api_client import ExtractionResult
    from eventcalendar.core.event_model import CalendarEvent
    from eventcalendar.ui.main_window import NLCalendarCreator

    raw = {
        "title": "Typed handoff",
        "start_time": "10:00",
        "end_time": "11:00",
        "date": "2026-09-01",
        "timezone": "Europe/Paris",
        "description": "Roadmap",
        "location": "Room 1",
    }
    model = CalendarEvent.from_dict(raw)
    extraction = ExtractionResult(events=[raw], event_models=(model,))
    window = NLCalendarCreator()
    captured: list[Any] = []
    errors: list[Any] = []
    monkeypatch.setattr(QMessageBox, "critical", lambda *args: errors.append(args))
    monkeypatch.setattr(window, "_update_status", lambda *_args: None)
    monkeypatch.setattr(
        window,
        "_build_merged_ics",
        lambda events: (captured.extend(events) or "ics", 1, []),
    )
    monkeypatch.setattr(window, "_open_in_calendar", lambda *_args: None)
    monkeypatch.setattr(
        CalendarEvent,
        "from_dict",
        classmethod(lambda cls, data: (_ for _ in ()).throw(AssertionError("revalidated"))),
    )

    window._finalize_events(extraction)

    assert errors == []
    assert captured == [model]
    window.close()


@pytest.mark.skipif(not UI_AVAILABLE, reason="UI tests disabled (set EVENTCALENDAR_RUN_UI_TESTS=1 to enable).")
def test_image_area_left_click_opens_picker(qt_app: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    from eventcalendar.ui.widgets.image_area import ImageAttachmentArea
    from PyQt6.QtCore import Qt

    area = ImageAttachmentArea()
    called: list[bool] = []
    monkeypatch.setattr(area, "_select_images_from_dialog", lambda: called.append(True))

    class DummyMouseEvent:
        def __init__(self) -> None:
            self.accepted = False

        def button(self):
            return Qt.MouseButton.LeftButton

        def accept(self) -> None:
            self.accepted = True

    event = DummyMouseEvent()
    area.mousePressEvent(event)

    assert called == [True]
    assert event.accepted is True
    area.close()
