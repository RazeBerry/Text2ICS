"""Event data model for calendar events."""

import uuid
from dataclasses import dataclass
from typing import Dict, Optional, Set

from eventcalendar.exceptions.errors import EventValidationError


@dataclass
class CalendarEvent:
    """Type-safe representation of a calendar event."""

    uid: str
    title: str
    start_time: Optional[str]
    end_time: Optional[str]
    date: str
    timezone: str
    description: Optional[str] = None
    location: Optional[str] = None
    all_day: bool = False

    # Required fields for validation. "uid" and "timezone" are defaulted in
    # from_dict, so their absence is not fatal. All-day events carry no times.
    REQUIRED_FIELDS: Set[str] = frozenset({
        "title", "start_time", "end_time", "date"
    })
    ALL_DAY_REQUIRED_FIELDS: Set[str] = frozenset({"title", "date"})

    @staticmethod
    def _parse_all_day_flag(value) -> bool:
        """Interpret the optional all_day flag, tolerating LLM string booleans."""
        if isinstance(value, str):
            return value.strip().lower() in {"true", "yes", "1"}
        return bool(value)

    @classmethod
    def from_dict(cls, data: Dict) -> "CalendarEvent":
        """Create a CalendarEvent from a dictionary, validating required fields.

        Args:
            data: Dictionary containing event data.

        Returns:
            A validated CalendarEvent instance.

        Raises:
            EventValidationError: If required fields are missing.
        """
        all_day = cls._parse_all_day_flag(data.get("all_day", False))
        required = cls.ALL_DAY_REQUIRED_FIELDS if all_day else cls.REQUIRED_FIELDS
        missing = required - set(data.keys())
        if missing:
            raise EventValidationError(
                missing_fields=missing,
                event_title=data.get('title', 'Unknown')
            )
        return cls(
            uid=data.get("uid") or str(uuid.uuid4()),
            title=data["title"],
            start_time=data.get("start_time"),
            end_time=data.get("end_time"),
            date=data["date"],
            timezone=data.get("timezone", "local"),
            description=data.get("description"),
            location=data.get("location"),
            all_day=all_day,
        )

    def to_dict(self) -> Dict:
        """Convert back to a dictionary for compatibility.

        Returns:
            Dictionary representation of the event.
        """
        result = {
            "uid": self.uid,
            "title": self.title,
            "date": self.date,
            "timezone": self.timezone,
        }
        if self.start_time:
            result["start_time"] = self.start_time
        if self.end_time:
            result["end_time"] = self.end_time
        if self.all_day:
            result["all_day"] = True
        if self.description:
            result["description"] = self.description
        if self.location:
            result["location"] = self.location
        return result
