import os
import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
import time
from typing import Optional, List, Tuple, Dict
from string import Formatter
import json
import uuid
import pytz
import textwrap
from icalendar import Calendar, Event, vText, Alarm
import re
from dateutil import parser
import tzlocal

from exceptions import (
    CalendarAPIError,
    TimezoneResolutionError,
    EventValidationError,
    ImageProcessingError,
    APIResponseError,
    RetryExhaustedError,
)

logger = logging.getLogger(__name__)

# Configuration constants
API_TIMEOUT_SECONDS = 60  # Timeout for API calls
MAX_BACKOFF_SECONDS = 10  # Cap exponential backoff
DEFAULT_MAX_RETRIES = 5
DEFAULT_BASE_DELAY = 1.0

# Error classification for smart retry logic
# These errors should NOT be retried (permanent failures)
NON_RETRYABLE_ERROR_PATTERNS = [
    "invalid api key",
    "api_key_invalid",
    "permission denied",
    "quota exceeded",
    "invalid argument",
    "authentication",
    "unauthorized",
]

# These errors SHOULD be retried (transient failures)
RETRYABLE_ERROR_PATTERNS = [
    "timeout",
    "deadline exceeded",
    "service unavailable",
    "resource exhausted",
    "connection",
    "network",
    "temporarily unavailable",
]


def _is_retryable_error(error: Exception) -> bool:
    """Determine if an error should be retried based on error type and message."""
    error_str = str(error).lower()
    error_type = type(error).__name__.lower()

    # Check for non-retryable patterns first (explicit deny)
    for pattern in NON_RETRYABLE_ERROR_PATTERNS:
        if pattern in error_str or pattern in error_type:
            return False

    # Check for retryable patterns (explicit allow)
    for pattern in RETRYABLE_ERROR_PATTERNS:
        if pattern in error_str or pattern in error_type:
            return True

    # Default: retry for unknown errors (safer for transient issues)
    # But log a warning for investigation
    logger.debug("Unknown error type, defaulting to retry: %s - %s", type(error).__name__, error)
    return True


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
    REQUIRED_FIELDS = {"uid", "title", "start_time", "end_time", "date", "timezone"}

    @classmethod
    def from_dict(cls, data: Dict) -> "CalendarEvent":
        """Create a CalendarEvent from a dictionary, validating required fields."""
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
        """Convert back to a dictionary for compatibility."""
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


class CalendarAPIClient:
    # Class-level constant for SYSTEM instructions
    SYSTEM_PROMPT = """
Follow these steps to extract event details and return them as a JSON array:

1. Carefully parse the event details (text and any image context) to identify if multiple distinct events are described. If so, process each one separately.

2. For each event, extract all relevant information such as event title, date, time, location, and description. 

   **IMPORTANT TIME HANDLING**:
   - Extract times EXACTLY as mentioned in the input (e.g., "3 PM", "19:30", "7:30pm")
   - Do NOT attempt timezone conversions - preserve the original time as stated
   - If a timezone is explicitly mentioned, include it in the time string
   - If no timezone is specified, assume it's in the user's local timezone
   - For relative dates like "tomorrow", "next Friday", calculate based on the provided current date
   - If end time is not specified, estimate a reasonable duration (e.g., 1 hour for meetings, 2-3 hours for dinners)

3. Return a **JSON array**, one object per event.
   Keys REQUIRED per event:
     - "uid"          : stable unique string (use UUID if needed, no @domain required)
     - "title"        : human title
     - "start_time"   : time string as extracted (e.g., "7:30 PM", "19:30", "3:00 PM EST")
     - "end_time"     : time string as extracted or estimated (e.g., "9:00 PM", "21:30")
     - "date"         : date string (e.g., "2024-08-15", "March 30, 2024")
     - "timezone"     : timezone if explicitly mentioned, otherwise "local"
     - "description"  : plain text (no special escaping needed)
     - "location"     : plain text address or venue name, or "" if none provided

   Example JSON Output:
   ```json
   [
     {
       "uid": "uuid-some-unique-id-1",
       "title": "Dinner with Mia",
       "start_time": "7:30 PM",
       "end_time": "9:00 PM",
       "date": "2024-08-15",
       "timezone": "local",
       "description": "Catch up dinner.",
       "location": "Balthasar Restaurant"
     }
   ]
   ```

4. Ensure the output is ONLY the JSON array, with no introductory text or explanations.
"""

    # Class-level template for USER prompts (with dynamic placeholders)
    USER_PROMPT_TEMPLATE = """
<event_description>
{event_description}
</event_description>

Today's date is {day_name}, {formatted_date}.
Current timezone: {user_timezone}
"""

    def __init__(self, api_key: str):
        # Import genai here for lazy loading and store as instance variable
        import google.generativeai as genai
        self.genai = genai
        
        # Configure the API key
        self.genai.configure(api_key=api_key)
        
        self.generation_config = {
            "temperature": 0,
            "top_p": 0.3,
            "top_k": 64,
            "max_output_tokens": 8192,
            "response_mime_type": "text/plain",
        }

        # Validation layer: Ensure USER_PROMPT_TEMPLATE contains the required keys.
        template_keys = [fn for _, fn, _, _ in Formatter().parse(self.USER_PROMPT_TEMPLATE) if fn]
        required_keys = {'event_description', 'day_name', 'formatted_date', 'user_timezone'}
        assert set(template_keys) == required_keys, f"Template mismatch! Expected keys {required_keys} but got {set(template_keys)}"

        self.model = self.genai.GenerativeModel(
            model_name="gemini-2.0-flash",
            generation_config=self.generation_config,
            system_instruction=self.SYSTEM_PROMPT
        )
        self.base_delay = DEFAULT_BASE_DELAY
        self.max_retries = DEFAULT_MAX_RETRIES
        self.timeout_seconds = API_TIMEOUT_SECONDS

    def upload_to_gemini(self, path, mime_type=None):
        """Uploads the given file to Gemini."""
        # Add basic check for file existence
        if not os.path.exists(path):
             logger.error("File not found for upload: %s", path)
             raise FileNotFoundError(f"File not found: {path}")
        try:
            file = self.genai.upload_file(path, mime_type=mime_type)
            logger.debug("Uploaded file '%s' as: %s", file.display_name, file.uri)
            return file
        except Exception as e:
            logger.error("Error uploading file %s: %s", path, e)
            raise # Re-raise the exception after logging

    def get_event_data(self, event_description: str, image_data: list[tuple[str, str, str]],
                       status_callback: callable) -> Optional[List[Dict]]:
        """
        Get event data from the LLM without building ICS files.
        Returns a list of event dictionaries for review/editing.
        """
        # If no text is provided but there are attached images, use a default description.
        if not event_description and image_data:
            event_description = "Event details are provided via attached images."

        current_date = datetime.now()
        day_name = current_date.strftime("%A")
        formatted_date = current_date.strftime("%B %d, %Y")
        
        # Get user's timezone
        user_timezone = str(current_date.astimezone().tzinfo)

        # Build the dynamic prompt using the class-level USER_PROMPT_TEMPLATE.
        api_prompt = self.USER_PROMPT_TEMPLATE.format(
            event_description=event_description,
            day_name=day_name,
            formatted_date=formatted_date,
            user_timezone=user_timezone
        )

        for attempt in range(self.max_retries):
            try:
                status_callback(f"Attempting to get event details... (Try {attempt + 1}/{self.max_retries})")
                logger.debug("Attempt %d/%d", attempt + 1, self.max_retries)
                logger.debug("Generated API prompt (first 200 chars): %s", api_prompt[:200])

                # Prepare chat history (add any uploaded image parts if images are provided)
                history = []
                if image_data:
                    image_parts = []
                    for img in image_data:
                        file_path, mime_type, _ = img
                        # Ensure file exists before trying to upload
                        if os.path.exists(file_path):
                            try:
                                uploaded_file = self.upload_to_gemini(file_path, mime_type=mime_type)
                                image_parts.append(uploaded_file)
                            except Exception as upload_err:
                                logger.warning("Failed to upload image %s: %s", file_path, upload_err)
                        else:
                             logger.warning("Image file not found, skipping: %s", file_path)

                    if image_parts: # Only add history if images were successfully prepared
                        history.append({
                            "role": "user",
                            "parts": image_parts
                        })

                # Start the chat session with the provided image history (if any)
                chat_session = self.model.start_chat(history=history)
                # Send the text prompt as the follow-up message.
                message = chat_session.send_message(api_prompt)

                # Try to obtain the text response. Handle potential missing text attribute.
                response_text = getattr(message, 'text', None)
                if response_text is None:
                     # If no 'text', try to get it from parts if available
                    try:
                        # Ensure message.parts exists and is iterable
                        if hasattr(message, 'parts') and message.parts:
                             response_text = "".join(part.text for part in message.parts if hasattr(part, 'text'))
                        else:
                             response_text = str(message) # Fallback if no parts or parts have no text
                    except Exception as e:
                         logger.warning("Failed to extract text from message parts: %s", e)
                         response_text = str(message) # Fallback to string representation

                # Handle case where response_text might still be None or empty after attempts
                if not response_text:
                     logger.debug("Received empty response from API.")
                     # Decide whether to retry or raise an error
                     raise ValueError("Received empty response from API")

                logger.debug("Raw API Response: %s", response_text)

                # Remove potential markdown code block fences
                cleaned_response_text = response_text.strip().removeprefix("```json").removesuffix("```").strip()

                # Parse the JSON response
                try:
                    events = json.loads(cleaned_response_text) # raises on bad JSON
                except json.JSONDecodeError as json_err:
                    logger.debug("Failed to decode JSON: %s", json_err)
                    logger.debug("Received text was: %s", cleaned_response_text)
                    # Reraise or handle specific retry logic for bad JSON format
                    raise ValueError(f"LLM returned invalid JSON: {json_err}") from json_err

                logger.debug("Successfully parsed %d event(s).", len(events))
                status_callback(f"Successfully extracted {len(events)} event(s).")
                return events # Return the list of event dictionaries

            except Exception as e:
                logger.debug("Exception on attempt %d: %s (%s)", attempt + 1, e, type(e).__name__)

                # Check if this error should be retried
                if not _is_retryable_error(e):
                    logger.debug("Non-retryable error detected, not retrying: %s", type(e).__name__)
                    status_callback(f"Error: {type(e).__name__} - this error cannot be retried.")
                    raise

                if attempt < self.max_retries - 1:
                    # Cap the exponential backoff to prevent excessive waits
                    delay = min(self.base_delay * (2 ** attempt), MAX_BACKOFF_SECONDS)
                    status_callback(f"Error occurred ({type(e).__name__}), retrying in {delay:.0f} seconds...")
                    logger.debug("Retrying in %.0f seconds...", delay)
                    time.sleep(delay)
                    continue

                logger.debug("Max retries reached. Raising exception.")
                status_callback("Error: Max retries reached. Failed to create event.")
                # Raise custom retry exhausted exception
                raise RetryExhaustedError(attempts=self.max_retries, last_error=e) from e

        logger.debug("Failed to create calendar event after retries.")
        status_callback("Error: Failed to create event after retries.")
        return None # Explicitly return None if loop completes without success

    def create_calendar_event(self, event_description: str, image_data: list[tuple[str, str, str]],
                              status_callback: callable) -> str:
        """
        Backwards-compatible helper that returns ICS text for the requested events.
        Internally delegates to get_event_data and build_ics_from_events.
        """
        events = self.get_event_data(event_description, image_data, status_callback)
        if not events:
            raise Exception("API returned no event data.")

        ics_strings, warnings = build_ics_from_events(events)
        if not ics_strings:
            raise Exception("Failed to build ICS content from event data.")

        if warnings:
            warning_text = " | ".join(warnings)
            try:
                status_callback(f"Warnings: {warning_text}")
            except Exception as e:
                logger.warning("Failed to send status callback for warnings: %s. Warnings: %s", e, warning_text)

        return "\r\n".join(ics_strings)


# --- ICS Builder Function (outside the class) ---
def build_ics_from_events(events: list[dict]) -> tuple[list[str], list[str]]:
    """
    Builds a list of .ics file content strings (CRLF-terminated) from event data.
    Returns: (ics_strings, warnings) tuple
    """
    out = []
    warnings = []
    if not isinstance(events, list):
        logger.error("Expected a list of events, but got %s", type(events))
        if isinstance(events, dict):
             events = [events] # Try processing it as a single event list
        else:
             return [], [] # Return empty if it's not a list or dict

    for i, ev in enumerate(events):
        try:
            # Basic validation of required keys
            required_keys = {"uid", "title", "start_time", "end_time", "date", "timezone"}
            missing_keys = required_keys - set(ev.keys())
            if missing_keys:
                event_title = ev.get('title', f'Event {i+1}')
                warning_msg = f"Skipping '{event_title}' - missing required fields: {missing_keys}"
                logger.warning(warning_msg)
                warnings.append(warning_msg)
                continue

            cal = Calendar()
            cal.add("PRODID", "-//NL Calendar Creator//EN")
            cal.add("VERSION", "2.0")

            ve = Event()

            # Ensure UID is present and reasonably unique - use provided or generate UUID
            uid = ev.get("uid") or str(uuid.uuid4())
            ve.add("UID", uid)

            # Use current UTC time for DTSTAMP
            ve.add("DTSTAMP", datetime.now(pytz.utc))

            # Parse date, time, and timezone properly
            try:
                # Parse the date first
                event_date = parser.parse(ev["date"]).date()
                
                # Parse start and end times
                start_time_str = ev["start_time"]
                end_time_str = ev["end_time"]
                
                # Handle timezone
                tz_str_raw = ev.get("timezone", "local") or "local"

                # Normalise to upper-case once for mapping look-up (but keep original for debug)
                tz_upper = tz_str_raw.upper()

                # Map common (and DST) abbreviations to canonical IANA zones that understand DST.
                ABBR_TO_TZ = {
                    # North America
                    "EST": "America/New_York", "EDT": "America/New_York",
                    "CST": "America/Chicago", "CDT": "America/Chicago",
                    "MST": "America/Denver",  "MDT": "America/Denver",
                    "PST": "America/Los_Angeles", "PDT": "America/Los_Angeles",
                    # United Kingdom / Europe
                    "GMT": "Europe/London", "BST": "Europe/London",
                    "CET": "Europe/Paris",  "CEST": "Europe/Paris",
                    "EET": "Europe/Athens", "EEST": "Europe/Athens",
                    # Australia
                    "AEST": "Australia/Sydney", "AEDT": "Australia/Sydney",
                    # Asia
                    "IST": "Asia/Kolkata",  # India (UTC+5:30 – no DST)
                    # Fallback examples may be added as needed
                }

                if tz_upper == "LOCAL":
                    # User's system zone (DST aware)
                    local_tz_obj = tzlocal.get_localzone()
                    tz_name = getattr(local_tz_obj, "zone", str(local_tz_obj))
                else:
                    tz_name = ABBR_TO_TZ.get(tz_upper, tz_str_raw)

                try:
                    local_tz = pytz.timezone(tz_name)
                except pytz.UnknownTimeZoneError:
                    # Last-ditch attempt with dateutil (may return fixed offset)
                    from dateutil import tz as du_tz
                    local_tz = du_tz.gettz(tz_name)
                    if local_tz is None:
                        local_tz = pytz.utc
                        warning_msg = f"Couldn't resolve timezone '{tz_str_raw}' for event '{ev.get('title', 'Unknown')}' - using UTC. Please verify the time in your calendar."
                        logger.warning(warning_msg)
                        warnings.append(warning_msg)
                
                # Parse times and combine with date
                start_time = parser.parse(start_time_str).time()
                end_time = parser.parse(end_time_str).time()
                
                # Combine date and time (still naive at this point)
                start_dt_naive = datetime.combine(event_date, start_time)
                end_dt_naive = datetime.combine(event_date, end_time)

                # Attach timezone – handle both pytz and dateutil/zoneinfo objects.
                def _attach_tz(tzobj, naive_dt):
                    """Return timezone-aware dt, using proper DST rules where possible."""
                    if hasattr(tzobj, "localize"):
                        # pytz – honour DST rules automatically; let pytz raise on ambiguous times
                        try:
                            return tzobj.localize(naive_dt, is_dst=None)
                        except Exception:
                            # Fall back to is_dst=True on ambiguity (earlier) – still better than wrong offset
                            return tzobj.localize(naive_dt, is_dst=True)
                    else:
                        # zoneinfo/dateutil – just set tzinfo; these implement DST via utcoffset()
                        return naive_dt.replace(tzinfo=tzobj)

                start_dt = _attach_tz(local_tz, start_dt_naive)
                end_dt = _attach_tz(local_tz, end_dt_naive)
                
                # Convert to UTC for storage
                start_dt_utc = start_dt.astimezone(pytz.utc)
                end_dt_utc = end_dt.astimezone(pytz.utc)
                
            except Exception as dt_err:
                logger.warning("Skipping event '%s' due to date/time parsing error: %s", ev.get('title', 'Unknown'), dt_err)
                continue

            ve.add("DTSTART", start_dt_utc)
            ve.add("DTEND", end_dt_utc)

            ve.add("SUMMARY", vText(str(ev.get("title", "No Title"))))

            location = ev.get("location")
            if location:
                ve.add("LOCATION", vText(str(location)))

            description = ev.get("description")
            if description:
                 ve.add("DESCRIPTION", vText(str(description)))

            # Add a 30-minute reminder (VALARM)
            alarm = Alarm()
            alarm.add("ACTION", "DISPLAY")
            alarm.add("DESCRIPTION", "Reminder")
            alarm.add("TRIGGER", timedelta(minutes=-30))
            ve.add_component(alarm)

            cal.add_component(ve)

            # Generate ICS content and ensure CRLF line endings
            raw_ical = cal.to_ical()
            decoded_ical = raw_ical.decode("utf-8", errors="replace")
            crlf_ical = decoded_ical.replace("\r\n", "\n").replace("\n", "\r\n")

            out.append(crlf_ical)

        except Exception as build_err:
            error_msg = f"Error building ICS for event {i+1} ({ev.get('title', 'Unknown Title')}): {build_err}"
            logger.error(error_msg)
            warnings.append(error_msg)

    return out, warnings 
