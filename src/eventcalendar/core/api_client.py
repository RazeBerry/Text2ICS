"""Gemini API client for calendar event extraction."""

import json
import logging
import os
import time
from datetime import datetime
from string import Formatter
from typing import Callable, Dict, List, Optional, Tuple

from eventcalendar.config.settings import API_CONFIG
from eventcalendar.config.constants import (
    STATUS_ATTEMPTING,
    STATUS_SUCCESS,
    STATUS_MAX_RETRIES,
    STATUS_FAILED,
)
from eventcalendar.exceptions.errors import CalendarAPIError, RetryExhaustedError
from eventcalendar.core.retry import is_retryable_error, wrap_api_key_error, is_api_key_error
from eventcalendar.core.ics_builder import build_ics_from_events
from eventcalendar.utils.masking import mask_key

logger = logging.getLogger(__name__)


class CalendarAPIClient:
    """Client for interacting with Google's Gemini API to extract calendar events."""

    # System prompt for the LLM
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

    # Template for user prompts (with dynamic placeholders)
    USER_PROMPT_TEMPLATE = """
<event_description>
{event_description}
</event_description>

Today's date is {day_name}, {formatted_date}.
Current timezone: {user_timezone}
"""

    def __init__(self, api_key: str):
        """Initialize the API client with the given API key.

        Args:
            api_key: The Gemini API key.
        """
        # Import genai here for lazy loading
        import google.generativeai as genai
        self.genai = genai
        self.api_key = api_key
        self.api_key_masked = mask_key(api_key)

        # Configure the API key
        self.genai.configure(api_key=api_key)

        # Use configuration from settings
        self.generation_config = {
            "temperature": API_CONFIG.temperature,
            "top_p": API_CONFIG.top_p,
            "top_k": API_CONFIG.top_k,
            "max_output_tokens": API_CONFIG.max_output_tokens,
            "response_mime_type": "text/plain",
        }

        # Validate template keys
        self._validate_prompt_template()

        # Initialize the model
        self.model = self.genai.GenerativeModel(
            model_name=API_CONFIG.model_name,
            generation_config=self.generation_config,
            system_instruction=self.SYSTEM_PROMPT
        )

        # Retry configuration
        self.base_delay = API_CONFIG.base_delay
        self.max_retries = API_CONFIG.max_retries
        self.timeout_seconds = API_CONFIG.timeout_seconds

    def _validate_prompt_template(self) -> None:
        """Validate that the prompt template has required keys."""
        template_keys = [
            fn for _, fn, _, _ in Formatter().parse(self.USER_PROMPT_TEMPLATE) if fn
        ]
        required_keys = {'event_description', 'day_name', 'formatted_date', 'user_timezone'}
        found_keys = set(template_keys)
        if found_keys != required_keys:
            raise ValueError(
                f"Template mismatch! Expected keys {required_keys} but got {found_keys}"
            )

    def upload_to_gemini(self, path: str, mime_type: Optional[str] = None):
        """Upload a file to Gemini.

        Args:
            path: Path to the file to upload.
            mime_type: Optional MIME type of the file.

        Returns:
            The uploaded file object.

        Raises:
            FileNotFoundError: If the file doesn't exist.
            CalendarAPIError: If there's an API key error.
        """
        if not os.path.exists(path):
            logger.error("File not found for upload: %s", path)
            raise FileNotFoundError(f"File not found: {path}")

        try:
            file = self.genai.upload_file(path, mime_type=mime_type)
            logger.debug("Uploaded file '%s' as: %s", file.display_name, file.uri)
            return file
        except Exception as e:
            logger.error("Error uploading file %s: %s", path, e)
            if is_api_key_error(e):
                raise wrap_api_key_error(e, self.api_key_masked) from e
            raise

    def get_event_data(
        self,
        event_description: str,
        image_data: List[Tuple[str, str, Optional[str]]],
        status_callback: Callable[[str], None]
    ) -> Optional[List[Dict]]:
        """Get event data from the LLM without building ICS files.

        Args:
            event_description: Natural language description of the event(s).
            image_data: List of (file_path, mime_type, base64_data) tuples.
            status_callback: Callback function for status updates.

        Returns:
            List of event dictionaries, or None if extraction failed.

        Raises:
            CalendarAPIError: If there's a permanent API error.
            RetryExhaustedError: If all retries are exhausted.
        """
        prompt = self._build_prompt(event_description)

        for attempt in range(self.max_retries):
            try:
                status_callback(
                    STATUS_ATTEMPTING.format(
                        attempt=attempt + 1,
                        max_retries=self.max_retries
                    )
                )
                logger.debug("Attempt %d/%d", attempt + 1, self.max_retries)

                history = self._prepare_image_history(image_data)
                response_text = self._call_api(prompt, history)
                events = self._parse_response(response_text)

                logger.debug("Successfully parsed %d event(s).", len(events))
                status_callback(STATUS_SUCCESS.format(count=len(events)))
                return events

            except CalendarAPIError:
                # Don't retry permanent failures
                raise
            except Exception as e:
                if not self._handle_retry(e, attempt, status_callback):
                    raise

        logger.debug("Failed to create calendar event after retries.")
        status_callback(STATUS_FAILED)
        return None

    def _build_prompt(self, event_description: str) -> str:
        """Build the user prompt with current date context.

        Args:
            event_description: The event description from the user.

        Returns:
            The formatted prompt string.
        """
        if not event_description:
            event_description = "Event details are provided via attached images."

        current_date = datetime.now()
        return self.USER_PROMPT_TEMPLATE.format(
            event_description=event_description,
            day_name=current_date.strftime("%A"),
            formatted_date=current_date.strftime("%B %d, %Y"),
            user_timezone=str(current_date.astimezone().tzinfo)
        )

    def _prepare_image_history(
        self,
        image_data: List[Tuple[str, str, Optional[str]]]
    ) -> List[Dict]:
        """Upload images and prepare chat history.

        Args:
            image_data: List of (file_path, mime_type, base64_data) tuples.

        Returns:
            Chat history list for the API call.
        """
        if not image_data:
            return []

        image_parts = []
        for file_path, mime_type, _ in image_data:
            if os.path.exists(file_path):
                try:
                    uploaded = self.upload_to_gemini(file_path, mime_type=mime_type)
                    image_parts.append(uploaded)
                except CalendarAPIError:
                    raise
                except Exception as e:
                    logger.warning("Failed to upload image %s: %s", file_path, e)

        if image_parts:
            return [{"role": "user", "parts": image_parts}]
        return []

    def _call_api(self, prompt: str, history: List[Dict]) -> str:
        """Make the API call and extract response text.

        Args:
            prompt: The user prompt.
            history: Chat history with uploaded images.

        Returns:
            The response text from the API.

        Raises:
            ValueError: If the response is empty.
            CalendarAPIError: If there's an API key error.
        """
        logger.debug("Generated API prompt (first 200 chars): %s", prompt[:200])

        chat = self.model.start_chat(history=history)
        message = chat.send_message(prompt)

        response_text = self._extract_text(message)
        if not response_text:
            logger.debug("Received empty response from API.")
            raise ValueError("Received empty response from API")

        logger.debug("Raw API Response: %s", response_text)
        return response_text

    def _extract_text(self, message) -> Optional[str]:
        """Extract text from API response message.

        Args:
            message: The API response message.

        Returns:
            The extracted text, or None if extraction failed.
        """
        response_text = getattr(message, 'text', None)
        if response_text is not None:
            return response_text

        # Try to get text from parts
        try:
            if hasattr(message, 'parts') and message.parts:
                return "".join(
                    part.text for part in message.parts if hasattr(part, 'text')
                )
            return str(message)
        except Exception as e:
            logger.warning("Failed to extract text from message parts: %s", e)
            return str(message)

    def _parse_response(self, response_text: str) -> List[Dict]:
        """Parse JSON response into event list.

        Args:
            response_text: The raw response text.

        Returns:
            List of event dictionaries.

        Raises:
            ValueError: If JSON parsing fails.
        """
        # Remove potential markdown code block fences (Python 3.8 compatible).
        cleaned = response_text.strip()
        if cleaned.startswith("```"):
            first_newline = cleaned.find("\n")
            cleaned = cleaned[first_newline + 1:] if first_newline != -1 else cleaned[3:]
            if cleaned.endswith("```"):
                cleaned = cleaned[:-3]
            cleaned = cleaned.strip()

        try:
            return json.loads(cleaned)
        except json.JSONDecodeError as e:
            logger.debug("Failed to decode JSON: %s", e)
            logger.debug("Received text was: %s", cleaned)
            raise ValueError(f"LLM returned invalid JSON: {e}") from e

    def _handle_retry(
        self,
        error: Exception,
        attempt: int,
        status_callback: Callable[[str], None]
    ) -> bool:
        """Handle retry logic for errors.

        Args:
            error: The exception that occurred.
            attempt: Current attempt number (0-indexed).
            status_callback: Callback for status updates.

        Returns:
            True if we should continue retrying, False otherwise.

        Raises:
            CalendarAPIError: If this is an API key error.
            RetryExhaustedError: If max retries reached.
        """
        logger.debug(
            "Exception on attempt %d: %s (%s)",
            attempt + 1, error, type(error).__name__
        )

        # Check for API key errors
        if is_api_key_error(error):
            raise wrap_api_key_error(error, self.api_key_masked) from error

        # Check if this error should be retried
        if not is_retryable_error(error):
            logger.debug("Non-retryable error detected: %s", type(error).__name__)
            status_callback(
                f"Error: {type(error).__name__} - this error cannot be retried."
            )
            return False

        if attempt >= self.max_retries - 1:
            logger.debug("Max retries reached. Raising exception.")
            status_callback(STATUS_MAX_RETRIES)
            raise RetryExhaustedError(
                attempts=self.max_retries,
                last_error=error
            ) from error

        # Calculate backoff delay
        delay = min(self.base_delay * (2 ** attempt), API_CONFIG.max_backoff)
        status_callback(
            f"Error occurred ({type(error).__name__}), retrying in {delay:.0f} seconds..."
        )
        logger.debug("Retrying in %.0f seconds...", delay)
        time.sleep(delay)

        return True

    def create_calendar_event(
        self,
        event_description: str,
        image_data: List[Tuple[str, str, Optional[str]]],
        status_callback: Callable[[str], None]
    ) -> str:
        """Backwards-compatible helper that returns ICS text for the requested events.

        Internally delegates to get_event_data and build_ics_from_events.

        Args:
            event_description: Natural language description of the event(s).
            image_data: List of (file_path, mime_type, base64_data) tuples.
            status_callback: Callback function for status updates.

        Returns:
            ICS content string.

        Raises:
            Exception: If event extraction or ICS building fails.
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
                logger.warning(
                    "Failed to send status callback for warnings: %s. Warnings: %s",
                    e, warning_text
                )

        return "\r\n".join(ics_strings)
