"""Validated event data model shared by the AI and ICS boundaries."""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from datetime import date
from typing import Any, ClassVar, Dict, Optional, Set

from dateutil import parser

from eventcalendar.core.timezone_utils import extract_timezone_from_time_string, normalize_time_string
from eventcalendar.exceptions.errors import EventValidationError

_TIME_RANGE_PATTERN = re.compile(r"[-–—]")
_CLOCK_PATTERN = re.compile(
    r"^(?:"
    r"(?P<hour>\d{1,2})(?::(?P<minute>\d{2}))?\s*(?P<ampm>[ap]\.?m\.?)?"
    r"|noon|midnight"
    r")$",
    re.IGNORECASE,
)


@dataclass
class CalendarEvent:
    """Type-safe representation of one calendar event."""

    uid: str
    title: str
    start_time: Optional[str]
    end_time: Optional[str]
    date: str
    timezone: str
    description: Optional[str] = None
    location: Optional[str] = None
    all_day: bool = False
    end_date: Optional[str] = None
    start_timezone: Optional[str] = None
    end_timezone: Optional[str] = None

    REQUIRED_FIELDS: ClassVar[Set[str]] = frozenset({"title", "start_time", "end_time", "date"})
    ALL_DAY_REQUIRED_FIELDS: ClassVar[Set[str]] = frozenset({"title", "date"})

    @staticmethod
    def _parse_all_day_flag(value: Any) -> bool:
        if isinstance(value, bool):
            return value
        if value is None:
            return False
        if isinstance(value, str):
            normalized = value.strip().lower()
            if normalized in {"true", "yes", "1"}:
                return True
            if normalized in {"false", "no", "0", ""}:
                return False
        raise EventValidationError(reason="all_day must be a boolean")

    @staticmethod
    def _require_text(data: Dict[str, Any], field: str, title: str) -> str:
        value = data.get(field)
        if not isinstance(value, str) or not value.strip():
            raise EventValidationError(event_title=title, reason=f"{field} must be non-empty text")
        return value.strip()

    @staticmethod
    def _validate_iso_date(value: str, field: str, title: str) -> str:
        try:
            parsed = date.fromisoformat(value)
        except (TypeError, ValueError) as exc:
            raise EventValidationError(
                event_title=title,
                reason=f"{field} must use YYYY-MM-DD",
            ) from exc
        if parsed.isoformat() != value:
            raise EventValidationError(event_title=title, reason=f"{field} must use YYYY-MM-DD")
        return value

    @staticmethod
    def _validate_clock(value: str, field: str, title: str) -> str:
        normalized = normalize_time_string(value)
        if _TIME_RANGE_PATTERN.search(normalized):
            raise EventValidationError(
                event_title=title,
                reason=f"{field} must contain one clock time, not a range",
            )
        try:
            clock_only, _embedded_timezone = extract_timezone_from_time_string(normalized)
            clock_match = _CLOCK_PATTERN.fullmatch(clock_only.strip())
            if clock_match is None:
                raise ValueError("not a standalone clock time")
            if clock_match.group("hour") is not None:
                hour = int(clock_match.group("hour"))
                minute = int(clock_match.group("minute") or 0)
                max_hour = 12 if clock_match.group("ampm") else 23
                if hour > max_hour or minute > 59 or (clock_match.group("ampm") and hour == 0):
                    raise ValueError("clock value is out of range")
            parsed = parser.parse(clock_only, fuzzy=False)
        except (TypeError, ValueError, OverflowError) as exc:
            raise EventValidationError(
                event_title=title,
                reason=f"{field} is not a valid clock time",
            ) from exc
        # dateutil fills today's date even for a pure clock.  Reject strings that
        # visibly contain a calendar date; those belong in date/end_date.
        if re.search(r"\b\d{4}[-/]\d{1,2}[-/]\d{1,2}\b", normalized):
            raise EventValidationError(event_title=title, reason=f"{field} must not contain a date")
        parsed.time()  # explicit documentation of the expected parse product
        return value.strip()

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "CalendarEvent":
        """Validate a mapping received from any external boundary."""
        if not isinstance(data, dict):
            raise EventValidationError(reason="event must be a JSON object")

        provisional_title = data.get("title")
        title = provisional_title.strip() if isinstance(provisional_title, str) else "Unknown"
        all_day = cls._parse_all_day_flag(data.get("all_day", False))
        required = cls.ALL_DAY_REQUIRED_FIELDS if all_day else cls.REQUIRED_FIELDS
        missing = {field for field in required if field not in data or data.get(field) is None}
        if missing:
            raise EventValidationError(missing_fields=missing, event_title=title)

        title = cls._require_text(data, "title", title)
        event_date = cls._validate_iso_date(
            cls._require_text(data, "date", title), "date", title
        )

        end_date_value = data.get("end_date")
        end_date = None
        if end_date_value not in (None, ""):
            end_date = cls._validate_iso_date(str(end_date_value).strip(), "end_date", title)
            if end_date < event_date:
                raise EventValidationError(event_title=title, reason="end_date is before date")

        start_time = None
        end_time = None
        if not all_day:
            start_time = cls._validate_clock(
                cls._require_text(data, "start_time", title), "start_time", title
            )
            end_time = cls._validate_clock(
                cls._require_text(data, "end_time", title), "end_time", title
            )

        timezone = data.get("timezone", "local")
        if not isinstance(timezone, str) or not timezone.strip():
            raise EventValidationError(event_title=title, reason="timezone must be non-empty text")

        def optional_text(field: str) -> Optional[str]:
            value = data.get(field)
            if value in (None, ""):
                return None
            if not isinstance(value, str):
                raise EventValidationError(event_title=title, reason=f"{field} must be text")
            return value.strip() or None

        uid_value = data.get("uid")
        uid = str(uid_value).strip() if uid_value not in (None, "") else str(uuid.uuid4())

        return cls(
            uid=uid,
            title=title,
            start_time=start_time,
            end_time=end_time,
            date=event_date,
            timezone=timezone.strip(),
            description=optional_text("description"),
            location=optional_text("location"),
            all_day=all_day,
            end_date=end_date,
            start_timezone=optional_text("start_timezone"),
            end_timezone=optional_text("end_timezone"),
        )

    def to_dict(self) -> Dict[str, Any]:
        """Convert the validated event back to its public mapping form."""
        result: Dict[str, Any] = {
            "uid": self.uid,
            "title": self.title,
            "date": self.date,
            "timezone": self.timezone,
            "all_day": self.all_day,
        }
        for field in (
            "start_time",
            "end_time",
            "end_date",
            "start_timezone",
            "end_timezone",
            "description",
            "location",
        ):
            value = getattr(self, field)
            if value is not None:
                result[field] = value
        return result
