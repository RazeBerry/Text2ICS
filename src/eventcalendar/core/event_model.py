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
    start_time: str
    end_time: str
    date: str
    timezone: str
    description: Optional[str] = None
    location: Optional[str] = None

    # Required fields for validation
    REQUIRED_FIELDS: Set[str] = frozenset({
        "uid", "title", "start_time", "end_time", "date", "timezone"
    })

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
        missing = cls.REQUIRED_FIELDS - set(data.keys())
        if missing:
            raise EventValidationError(
                missing_fields=missing,
                event_title=data.get('title', 'Unknown')
            )
        return cls(
            uid=data.get("uid") or str(uuid.uuid4()),
            title=data["title"],
            start_time=data["start_time"],
            end_time=data["end_time"],
            date=data["date"],
            timezone=data.get("timezone", "local"),
            description=data.get("description"),
            location=data.get("location"),
        )

    def to_dict(self) -> Dict:
        """Convert back to a dictionary for compatibility.

        Returns:
            Dictionary representation of the event.
        """
        result = {
            "uid": self.uid,
            "title": self.title,
            "start_time": self.start_time,
            "end_time": self.end_time,
            "date": self.date,
            "timezone": self.timezone,
        }
        if self.description:
            result["description"] = self.description
        if self.location:
            result["location"] = self.location
        return result
