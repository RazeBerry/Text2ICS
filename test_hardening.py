"""Regression tests for security, boundary, and cleanup hardening."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import pytest
import pytz
from icalendar import Calendar

from eventcalendar.core.api_client import (
    CalendarAPIClient,
    UploadedImageBatch,
)
from eventcalendar.core.event_model import CalendarEvent
from eventcalendar.core.ics_builder import build_ics_batch, build_ics_from_events
from eventcalendar.core.image_preprocessing import validate_image_file
from eventcalendar.core.timezone_utils import attach_timezone_with_warnings, resolve_timezone
from eventcalendar.exceptions.errors import (
    APIResponseError,
    EventValidationError,
    ImageProcessingError,
    TimezoneResolutionError,
)
from eventcalendar.ui.error_messages import get_user_friendly_error


def _vevent(ics_text: str):
    return next(component for component in Calendar.from_ical(ics_text).walk() if component.name == "VEVENT")


def _valid_event(**updates):
    event = {
        "title": "Review",
        "start_time": "10:00 AM",
        "end_time": "11:00 AM",
        "date": "2026-07-30",
        "timezone": "UTC",
    }
    event.update(updates)
    return event


def _bare_client() -> CalendarAPIClient:
    client = object.__new__(CalendarAPIClient)
    client._closed = False
    client.max_retries = 1
    client.base_delay = 0
    return client


@pytest.mark.parametrize("value", ["2026/07/30", "July 30 2026", "2026-02-30"])
def test_event_model_requires_iso_dates(value: str) -> None:
    with pytest.raises(EventValidationError):
        CalendarEvent.from_dict(_valid_event(date=value))


def test_event_model_rejects_time_ranges_and_preserves_travel_fields() -> None:
    with pytest.raises(EventValidationError, match="one clock time"):
        CalendarEvent.from_dict(_valid_event(start_time="10:00-11:00"))

    event = CalendarEvent.from_dict(
        _valid_event(
            end_date="2026-07-31",
            start_timezone="Europe/Paris",
            end_timezone="America/New_York",
        )
    )
    assert event.to_dict()["end_date"] == "2026-07-31"
    assert event.to_dict()["end_timezone"] == "America/New_York"


@pytest.mark.parametrize("value", ["tomorrow at 10", "25:00", "10:99", "2026-07-30 10:00"])
def test_event_model_requires_a_standalone_valid_clock(value: str) -> None:
    with pytest.raises(EventValidationError):
        CalendarEvent.from_dict(_valid_event(start_time=value))


def test_batch_builder_skips_malformed_elements_with_separate_reasons() -> None:
    result = build_ics_batch([42, {"title": "Missing"}, _valid_event()])
    assert len(result.ics_strings) == 1
    assert len(result.created_events) == 1
    assert len(result.skipped_events) == 2
    assert result.warnings == []


def test_unknown_and_ambiguous_timezones_are_blocked() -> None:
    for zone in ("CST", "BST", "IST", "Not/AZone"):
        with pytest.raises(TimezoneResolutionError):
            resolve_timezone(zone)

    ics, warnings = build_ics_from_events([_valid_event(timezone="CST")])
    assert ics == []
    assert any("ambiguous abbreviation" in warning for warning in warnings)


def test_explicit_abbreviations_are_fixed_but_generic_region_tracks_dst() -> None:
    est, _ = resolve_timezone("EST")
    eastern, _ = resolve_timezone("ET")
    winter = datetime(2026, 1, 15, 10)
    summer = datetime(2026, 7, 15, 10)

    assert attach_timezone_with_warnings(est, winter)[0].utcoffset().total_seconds() == -5 * 3600
    assert attach_timezone_with_warnings(est, summer)[0].utcoffset().total_seconds() == -5 * 3600
    assert attach_timezone_with_warnings(eastern, winter)[0].utcoffset().total_seconds() == -5 * 3600
    assert attach_timezone_with_warnings(eastern, summer)[0].utcoffset().total_seconds() == -4 * 3600


def test_embedded_start_zone_is_inherited_by_end() -> None:
    ics, warnings = build_ics_from_events([
        _valid_event(start_time="10:00 AM PST", end_time="11:00 AM", timezone="local")
    ])
    assert warnings == []
    event = _vevent(ics[0])
    assert event["DTSTART"].dt.astimezone(pytz.utc).hour == 18
    assert event["DTEND"].dt.astimezone(pytz.utc).hour == 19


def test_equal_wall_clocks_across_zones_roll_end_date_instead_of_assuming_one_hour() -> None:
    ics, warnings = build_ics_from_events([
        _valid_event(
            start_time="10:00 AM",
            end_time="10:00 AM",
            start_timezone="PST",
            end_timezone="EST",
        )
    ])
    event = _vevent(ics[0])
    duration = event["DTEND"].dt.astimezone(pytz.utc) - event["DTSTART"].dt.astimezone(pytz.utc)
    assert duration.total_seconds() == 21 * 3600
    assert not any("1-hour duration" in warning for warning in warnings)


def test_image_validation_uses_contents_not_extension(tmp_path: Path) -> None:
    fake = tmp_path / "fake.png"
    fake.write_bytes(b"not a png")
    with pytest.raises(ImageProcessingError):
        validate_image_file(str(fake))


def test_image_validation_enforces_byte_limit(tmp_path: Path) -> None:
    from PIL import Image

    image_path = tmp_path / "real.png"
    Image.new("RGB", (4, 4), "white").save(image_path)
    with pytest.raises(ImageProcessingError, match="limit"):
        validate_image_file(str(image_path), max_bytes=4)


def test_current_sdk_client_receives_timeout_and_single_attempt(monkeypatch: pytest.MonkeyPatch) -> None:
    from google import genai

    captured = {}

    class FakeSDKClient:
        def __init__(self, **kwargs):
            captured.update(kwargs)

        def close(self):
            pass

    monkeypatch.setattr(genai, "Client", FakeSDKClient)
    client = CalendarAPIClient("AIzaConstructionOnly")
    assert captured["http_options"].timeout == 60_000
    assert captured["http_options"].retry_options.attempts == 1
    assert client.generation_config.response_mime_type == "application/json"


def test_response_parser_validates_top_level_and_each_event() -> None:
    client = _bare_client()
    with pytest.raises(APIResponseError, match="JSON array"):
        client._parse_response(json.dumps(_valid_event()))
    with pytest.raises(APIResponseError, match="failed validation"):
        client._parse_response(json.dumps([{"title": "Incomplete"}]))
    assert client._parse_response(json.dumps([_valid_event()]))[0]["title"] == "Review"


def test_status_callback_failures_do_not_change_success(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _bare_client()
    monkeypatch.setattr(client, "_prepare_images", lambda *_args: UploadedImageBatch())
    monkeypatch.setattr(client, "_call_api", lambda *_args: json.dumps([_valid_event()]))
    monkeypatch.setattr(client, "_delete_remote_files", lambda _files: None)

    result = client.extract_events("Review tomorrow", [], lambda _message: (_ for _ in ()).throw(RuntimeError()))
    assert len(result.events) == 1


def test_remote_files_are_deleted_after_invalid_response(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _bare_client()
    uploaded = SimpleNamespace(name="files/test")
    deleted = []
    monkeypatch.setattr(client, "_prepare_images", lambda *_args: UploadedImageBatch([uploaded]))
    monkeypatch.setattr(client, "_call_api", lambda *_args: "{}")
    monkeypatch.setattr(client, "_delete_remote_files", lambda files: deleted.extend(files))

    with pytest.raises(APIResponseError):
        client.extract_events("Review", [("image.png", "image/png", None)])
    assert deleted == [uploaded]


def test_all_failed_images_are_not_silently_ignored(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _bare_client()
    monkeypatch.setattr(
        client,
        "_prepare_images",
        lambda *_args: UploadedImageBatch([], ["image.png: invalid image"]),
    )
    with pytest.raises(ImageProcessingError, match="invalid image"):
        client.extract_events("", [("image.png", "image/png", None)])


def test_invalid_response_is_not_misreported_as_an_api_key_problem() -> None:
    message = get_user_friendly_error(APIResponseError("invalid JSON object"))
    assert "unexpected response" in message
    assert "API key" not in message


def test_key_source_and_loader_share_nonfrozen_priority(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    import eventcalendar.storage.key_manager as key_manager

    user_path = tmp_path / "user.env"
    legacy_path = tmp_path / "legacy.env"
    monkeypatch.delenv("GEMINI_API_KEY_FREE", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.setattr(key_manager, "load_from_keyring", lambda: None)
    monkeypatch.setattr(key_manager, "get_env_file_path", lambda: user_path)
    monkeypatch.setattr(key_manager, "get_legacy_env_path", lambda: legacy_path)
    monkeypatch.setattr(
        key_manager,
        "load_from_env_file",
        lambda path: "legacy-key" if path == legacy_path else None,
    )
    monkeypatch.setattr(key_manager, "migrate_legacy_key", lambda: (True, "migrated"))
    monkeypatch.delattr(key_manager.sys, "frozen", raising=False)

    key, source = key_manager.get_api_key_source()
    assert key == key_manager.load_api_key() == "legacy-key"
    assert source.startswith("LEGACY (Insecure)")
    assert "Executable Directory" not in source


def test_frozen_executable_key_is_loaded_before_legacy(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    import eventcalendar.storage.key_manager as key_manager

    user_path = tmp_path / "user.env"
    executable_path = tmp_path / "bundle.env"
    legacy_path = tmp_path / "legacy.env"
    monkeypatch.delenv("GEMINI_API_KEY_FREE", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.setattr(key_manager, "load_from_keyring", lambda: None)
    monkeypatch.setattr(key_manager, "get_env_file_path", lambda: user_path)
    monkeypatch.setattr(key_manager, "get_executable_dir_env_path", lambda: executable_path)
    monkeypatch.setattr(key_manager, "get_legacy_env_path", lambda: legacy_path)
    monkeypatch.setattr(key_manager.sys, "frozen", True, raising=False)
    monkeypatch.setattr(
        key_manager,
        "load_from_env_file",
        lambda path: {executable_path: "bundle-key", legacy_path: "legacy-key"}.get(path),
    )

    key, source = key_manager.get_api_key_source()
    assert key == key_manager.load_api_key() == "bundle-key"
    assert source.startswith("Executable Directory")


def test_confirmed_legacy_cleanup_preserves_unrelated_settings(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    import eventcalendar.storage.key_manager as key_manager

    legacy_path = tmp_path / ".env"
    legacy_path.write_text(
        "GEMINI_API_KEY_FREE=test-only-key\nOTHER_SETTING=keep-me\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(key_manager, "get_legacy_env_path", lambda: legacy_path)

    success, message = key_manager.delete_legacy_key_file()
    assert success
    assert "preserved other settings" in message
    remaining = legacy_path.read_text(encoding="utf-8")
    assert "GEMINI_API_KEY" not in remaining
    assert "OTHER_SETTING=keep-me" in remaining
