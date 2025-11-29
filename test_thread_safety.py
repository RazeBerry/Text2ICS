"""Thread safety tests for EventCalendarGenerator.

These tests verify that critical thread safety fixes are working correctly.
"""

import threading
import time
import unittest
from unittest.mock import Mock, patch, MagicMock
from concurrent.futures import ThreadPoolExecutor, wait

# Test the ThemeManager class
from Calender import ThemeManager


class TestThemeManagerThreadSafety(unittest.TestCase):
    """Test that ThemeManager is thread-safe."""

    def setUp(self):
        """Reset theme to light before each test."""
        ThemeManager.set_theme("light")

    def test_concurrent_theme_reads(self):
        """Verify multiple threads can read theme safely."""
        results = []
        errors = []

        def read_theme():
            try:
                for _ in range(100):
                    theme = ThemeManager.get_theme()
                    if theme not in ("light", "dark"):
                        errors.append(f"Invalid theme value: {theme}")
                    results.append(theme)
            except Exception as e:
                errors.append(str(e))

        threads = [threading.Thread(target=read_theme) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.assertEqual(len(errors), 0, f"Errors during concurrent reads: {errors}")
        self.assertEqual(len(results), 1000)  # 10 threads * 100 reads

    def test_concurrent_theme_writes(self):
        """Verify multiple threads can write theme without corruption."""
        errors = []
        write_count = {"light": 0, "dark": 0}

        def toggle_theme():
            try:
                for _ in range(50):
                    new_theme = ThemeManager.toggle_theme()
                    if new_theme not in ("light", "dark"):
                        errors.append(f"Invalid theme after toggle: {new_theme}")
            except Exception as e:
                errors.append(str(e))

        threads = [threading.Thread(target=toggle_theme) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.assertEqual(len(errors), 0, f"Errors during concurrent writes: {errors}")
        # Final theme should be valid
        final_theme = ThemeManager.get_theme()
        self.assertIn(final_theme, ("light", "dark"))

    def test_toggle_returns_correct_theme(self):
        """Verify toggle returns the new theme, not the old one."""
        ThemeManager.set_theme("light")
        new_theme = ThemeManager.toggle_theme()
        self.assertEqual(new_theme, "dark")
        self.assertEqual(ThemeManager.get_theme(), "dark")

        new_theme = ThemeManager.toggle_theme()
        self.assertEqual(new_theme, "light")
        self.assertEqual(ThemeManager.get_theme(), "light")


class TestRetryLogic(unittest.TestCase):
    """Test the smart retry logic."""

    def test_retryable_error_patterns(self):
        """Verify retryable errors are correctly identified."""
        from api_client import _is_retryable_error

        # These should be retryable
        retryable_errors = [
            Exception("Connection timeout"),
            Exception("Network error occurred"),
            Exception("Service unavailable"),
            Exception("deadline exceeded"),
            TimeoutError("Request timed out"),
        ]
        for error in retryable_errors:
            self.assertTrue(
                _is_retryable_error(error),
                f"Expected {error} to be retryable"
            )

    def test_non_retryable_error_patterns(self):
        """Verify non-retryable errors are correctly identified."""
        from api_client import _is_retryable_error

        # These should NOT be retryable
        non_retryable_errors = [
            Exception("Invalid API key"),
            Exception("Permission denied"),
            Exception("Quota exceeded for the day"),
            Exception("Authentication failed"),
            Exception("Unauthorized access"),
        ]
        for error in non_retryable_errors:
            self.assertFalse(
                _is_retryable_error(error),
                f"Expected {error} to NOT be retryable"
            )


class TestCalendarEventModel(unittest.TestCase):
    """Test the CalendarEvent data model."""

    def test_from_dict_valid_data(self):
        """Verify CalendarEvent can be created from valid dict."""
        from api_client import CalendarEvent

        data = {
            "uid": "test-123",
            "title": "Test Event",
            "start_time": "10:00 AM",
            "end_time": "11:00 AM",
            "date": "2025-01-15",
            "timezone": "America/New_York",
            "description": "A test event",
            "location": "Conference Room A",
        }

        event = CalendarEvent.from_dict(data)
        self.assertEqual(event.uid, "test-123")
        self.assertEqual(event.title, "Test Event")
        self.assertEqual(event.start_time, "10:00 AM")
        self.assertEqual(event.end_time, "11:00 AM")
        self.assertEqual(event.date, "2025-01-15")
        self.assertEqual(event.timezone, "America/New_York")
        self.assertEqual(event.description, "A test event")
        self.assertEqual(event.location, "Conference Room A")

    def test_from_dict_missing_fields(self):
        """Verify CalendarEvent raises EventValidationError for missing fields."""
        from api_client import CalendarEvent
        from exceptions import EventValidationError

        data = {
            "title": "Test Event",
            # Missing: uid, start_time, end_time, date, timezone
        }

        with self.assertRaises(EventValidationError) as context:
            CalendarEvent.from_dict(data)

        self.assertIn("uid", context.exception.missing_fields)
        self.assertIn("start_time", context.exception.missing_fields)

    def test_from_dict_generates_uid_if_empty(self):
        """Verify empty UID is replaced with generated UUID."""
        from api_client import CalendarEvent

        data = {
            "uid": "",  # Empty string
            "title": "Test Event",
            "start_time": "10:00 AM",
            "end_time": "11:00 AM",
            "date": "2025-01-15",
            "timezone": "local",
        }

        event = CalendarEvent.from_dict(data)
        self.assertIsNotNone(event.uid)
        self.assertNotEqual(event.uid, "")
        # Check it looks like a UUID
        self.assertGreater(len(event.uid), 10)

    def test_to_dict_roundtrip(self):
        """Verify to_dict produces data that can recreate the event."""
        from api_client import CalendarEvent

        original = CalendarEvent(
            uid="test-123",
            title="Test Event",
            start_time="10:00 AM",
            end_time="11:00 AM",
            date="2025-01-15",
            timezone="local",
            description="A test",
            location="Room 1",
        )

        data = original.to_dict()
        recreated = CalendarEvent.from_dict(data)

        self.assertEqual(original.uid, recreated.uid)
        self.assertEqual(original.title, recreated.title)
        self.assertEqual(original.start_time, recreated.start_time)
        self.assertEqual(original.description, recreated.description)


class TestCustomExceptions(unittest.TestCase):
    """Test custom exception classes."""

    def test_timezone_resolution_error(self):
        """Verify TimezoneResolutionError stores timezone info."""
        from exceptions import TimezoneResolutionError

        error = TimezoneResolutionError("XYZ", "UTC")
        self.assertEqual(error.tz_name, "XYZ")
        self.assertEqual(error.fallback, "UTC")
        self.assertIn("XYZ", str(error))
        self.assertIn("UTC", str(error))

    def test_event_validation_error(self):
        """Verify EventValidationError stores field info."""
        from exceptions import EventValidationError

        error = EventValidationError({"uid", "date"}, "My Event")
        self.assertEqual(error.missing_fields, {"uid", "date"})
        self.assertEqual(error.event_title, "My Event")
        self.assertIn("uid", str(error))
        self.assertIn("My Event", str(error))

    def test_retry_exhausted_error(self):
        """Verify RetryExhaustedError stores attempt info."""
        from exceptions import RetryExhaustedError

        original_error = ValueError("API failed")
        error = RetryExhaustedError(attempts=5, last_error=original_error)
        self.assertEqual(error.attempts, 5)
        self.assertEqual(error.last_error, original_error)
        self.assertIn("5", str(error))


if __name__ == "__main__":
    unittest.main()
