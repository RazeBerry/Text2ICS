import os
from datetime import datetime, timedelta
import time
from typing import Optional, List, Tuple
from string import Formatter
import json
import uuid
import pytz
import textwrap
from icalendar import Calendar, Event, vText, Alarm


class CalendarAPIClient:
    # Class-level constant for SYSTEM instructions
    SYSTEM_PROMPT = """
Follow these steps to extract event details and return them as a JSON array:

1. Carefully parse the event details (text and any image context) to identify if multiple distinct events are described. If so, process each one separately.

2. For each event, extract all relevant information such as event title, date, time, location, and description. If the event involves travel between different cities, be aware that the departure and arrival times may be in different time zones. Adjust the event times accordingly by converting them to UTC, ensuring accurate reflection of time differences. Employ a chain-of-thought process with reflection and verification to ensure proper handling of these time differences.

3. Return a **JSON array**, one object per event.
   Keys REQUIRED per event:
     - "uid"          : stable unique string (use UUID if needed, no @domain required)
     - "title"        : human title
     - "start_utc"    : ISO-8601 UTC string, e.g., "2025-07-21T13:30:00Z"
     - "end_utc"      : ISO-8601 UTC string, e.g., "2025-07-21T14:30:00Z"
     - "description"  : plain text (no special escaping needed)
     - "location"     : plain text address or venue name, or "" if none provided

   Example JSON Output:
   ```json
   [
     {
       "uid": "uuid-some-unique-id-1",
       "title": "Dinner with Mia",
       "start_utc": "2024-08-15T19:30:00Z",
       "end_utc": "2024-08-15T21:00:00Z",
       "description": "Catch up dinner.",
       "location": "Balthasar Restaurant"
     },
     {
       "uid": "uuid-some-unique-id-2",
       "title": "Team Meeting",
       "start_utc": "2024-08-16T10:00:00Z",
       "end_utc": "2024-08-16T11:00:00Z",
       "description": "Discuss project milestones.",
       "location": "Office Conference Room B"
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
        required_keys = {'event_description', 'day_name', 'formatted_date'}
        assert set(template_keys) == required_keys, f"Template mismatch! Expected keys {required_keys} but got {set(template_keys)}"

        self.model = self.genai.GenerativeModel(
            model_name="gemini-2.0-flash",
            generation_config=self.generation_config,
            system_instruction=self.SYSTEM_PROMPT
        )
        self.base_delay = 1
        self.max_retries = 5

    def upload_to_gemini(self, path, mime_type=None):
        """Uploads the given file to Gemini."""
        # Add basic check for file existence
        if not os.path.exists(path):
             print(f"Error: File not found for upload: {path}")
             raise FileNotFoundError(f"File not found: {path}")
        try:
            file = self.genai.upload_file(path, mime_type=mime_type)
            print(f"Uploaded file '{file.display_name}' as: {file.uri}")
            return file
        except Exception as e:
            print(f"Error uploading file {path}: {e}")
            raise # Re-raise the exception after logging

    def create_calendar_event(self, event_description: str, image_data: list[tuple[str, str, str]],
                              status_callback: callable) -> Optional[List[str]]:
        """
        Create calendar event(s) by getting JSON from the LLM and building ICS files.
        Returns a list of ICS file content strings.
        """
        # If no text is provided but there are attached images, use a default description.
        if not event_description and image_data:
            event_description = "Event details are provided via attached images."

        current_date = datetime.now()
        day_name = current_date.strftime("%A")
        formatted_date = current_date.strftime("%B %d, %Y")

        # Build the dynamic prompt using the class-level USER_PROMPT_TEMPLATE.
        api_prompt = self.USER_PROMPT_TEMPLATE.format(
            event_description=event_description,
            day_name=day_name,
            formatted_date=formatted_date
        )

        for attempt in range(self.max_retries):
            try:
                status_callback(f"Attempting to get event details... (Try {attempt + 1}/{self.max_retries})")
                print(f"DEBUG: Attempt {attempt + 1}/{self.max_retries}")
                print("DEBUG: Generated API prompt (first 200 chars):", api_prompt[:200])

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
                                print(f"Warning: Failed to upload image {file_path}: {upload_err}")
                                # Optionally inform the user or log this more formally
                        else:
                             print(f"Warning: Image file not found, skipping: {file_path}")

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
                    except Exception:
                         response_text = str(message) # Fallback to string representation

                # Handle case where response_text might still be None or empty after attempts
                if not response_text:
                     print("DEBUG: Received empty response from API.")
                     # Decide whether to retry or raise an error
                     raise ValueError("Received empty response from API")

                print("DEBUG: Raw API Response:", response_text)

                # Remove potential markdown code block fences
                cleaned_response_text = response_text.strip().removeprefix("```json").removesuffix("```").strip()

                # Parse the JSON response
                try:
                    events = json.loads(cleaned_response_text) # raises on bad JSON
                except json.JSONDecodeError as json_err:
                    print(f"DEBUG: Failed to decode JSON: {json_err}")
                    print(f"DEBUG: Received text was: {cleaned_response_text}")
                    # Reraise or handle specific retry logic for bad JSON format
                    raise ValueError(f"LLM returned invalid JSON: {json_err}") from json_err

                # Build ICS strings from the parsed events
                ics_strings = build_ics_from_events(events) # list[str]

                print(f"DEBUG: Successfully parsed {len(events)} event(s) and generated {len(ics_strings)} ICS strings.")
                status_callback(f"Successfully processed {len(ics_strings)} event(s).")
                return ics_strings # Return the list of ICS strings

            except Exception as e:
                print(f"DEBUG: Exception on attempt {attempt + 1}: {e}")
                if attempt < self.max_retries - 1:
                    delay = self.base_delay * (2 ** attempt)
                    status_callback(f"Error occurred ({type(e).__name__}), retrying in {delay} seconds...")
                    print(f"DEBUG: Retrying in {delay} seconds...")
                    time.sleep(delay)
                    continue
                print("DEBUG: Max retries reached. Raising exception.")
                status_callback("Error: Max retries reached. Failed to create event.")
                # Re-raise the last exception to be caught by the caller
                raise Exception(f"Failed to create calendar event after {self.max_retries} retries: {e}") from e

        print("DEBUG: Failed to create calendar event after retries.")
        status_callback("Error: Failed to create event after retries.")
        return None # Explicitly return None if loop completes without success


# --- ICS Builder Function (outside the class) ---
def build_ics_from_events(events: list[dict]) -> list[str]:
    """Builds a list of .ics file content strings (CRLF-terminated) from event data."""
    out = []
    if not isinstance(events, list):
        print(f"Error: Expected a list of events, but got {type(events)}")
        # Potentially raise an error or return empty list depending on desired handling
        # For now, let's try to handle if it's a single dict wrapped unexpectedly
        if isinstance(events, dict):
             events = [events] # Try processing it as a single event list
        else:
             return [] # Return empty if it's not a list or dict

    for i, ev in enumerate(events):
        try:
            # Basic validation of required keys
            required_keys = {"uid", "title", "start_utc", "end_utc"}
            if not required_keys.issubset(ev.keys()):
                print(f"Warning: Skipping event {i+1} due to missing required keys ({required_keys - set(ev.keys())})")
                continue

            cal = Calendar()
            cal.add("PRODID", "-//NL Calendar Creator//EN")
            cal.add("VERSION", "2.0")

            ve = Event()

            # Ensure UID is present and reasonably unique - use provided or generate UUID
            uid = ev.get("uid") or str(uuid.uuid4())
            ve.add("UID", uid)

            # Use current UTC time for DTSTAMP
            ve.add("DTSTAMP", datetime.now(pytz.utc)) # Ensure DTSTAMP is timezone-aware (UTC)

            # Parse ISO 8601 strings for start/end times
            # The .replace handles cases where 'Z' is present; fromisoformat needs timezone offset
            try:
                start_dt = datetime.fromisoformat(ev["start_utc"].replace("Z", "+00:00"))
                end_dt = datetime.fromisoformat(ev["end_utc"].replace("Z", "+00:00"))
            except ValueError as dt_err:
                print(f"Warning: Skipping event '{ev.get('title', 'Unknown')}' due to invalid date format: {dt_err}")
                continue
            except KeyError as key_err:
                 print(f"Warning: Skipping event '{ev.get('title', 'Unknown')}' due to missing date key: {key_err}")
                 continue

            # Add timezone info if naive (assume UTC if specified as such)
            # Note: fromisoformat should handle the +00:00 offset correctly, making them aware.
            # Localizing naive datetimes might be needed if the format was different.
            # Let's ensure they are timezone aware, converting to UTC if necessary.
            if start_dt.tzinfo is None:
                 start_dt = pytz.utc.localize(start_dt)
            else:
                 start_dt = start_dt.astimezone(pytz.utc)

            if end_dt.tzinfo is None:
                 end_dt = pytz.utc.localize(end_dt)
            else:
                 end_dt = end_dt.astimezone(pytz.utc)


            ve.add("DTSTART", start_dt)
            ve.add("DTEND", end_dt)

            ve.add("SUMMARY", vText(str(ev.get("title", "No Title")))) # Use vText for proper escaping/folding

            location = ev.get("location")
            if location:
                ve.add("LOCATION", vText(str(location)))

            description = ev.get("description")
            if description:
                 # vText handles folding, direct assignment is generally sufficient.
                 # textwrap might be redundant unless specific manual folding is needed.
                 ve.add("DESCRIPTION", vText(str(description)))

            # Add a 30-minute reminder (VALARM)
            alarm = Alarm()
            alarm.add("ACTION", "DISPLAY")
            alarm.add("DESCRIPTION", "Reminder") # Standard description
            alarm.add("TRIGGER", timedelta(minutes=-30)) # Relative trigger
            ve.add_component(alarm)

            cal.add_component(ve)

            # Generate ICS content and ensure CRLF line endings
            raw_ical = cal.to_ical()
            # Ensure bytes are decoded correctly (icalendar outputs bytes)
            decoded_ical = raw_ical.decode("utf-8", errors="replace")
            # Ensure CRLF endings (replace LF not preceded by CR, then replace standalone LF)
            crlf_ical = decoded_ical.replace("\r\n", "\n").replace("\n", "\r\n")

            out.append(crlf_ical)

        except Exception as build_err:
            # Log error for the specific event but continue with others
            print(f"Error building ICS for event {i+1} ({ev.get('title', 'Unknown Title')}): {build_err}")
            # Consider adding this faulty event's data to an error log / returning it separately

    return out 