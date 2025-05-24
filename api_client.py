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
import re
from dateutil import parser
import tzlocal


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
        if isinstance(events, dict):
             events = [events] # Try processing it as a single event list
        else:
             return [] # Return empty if it's not a list or dict

    for i, ev in enumerate(events):
        try:
            # Basic validation of required keys
            required_keys = {"uid", "title", "start_time", "end_time", "date", "timezone"}
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
            ve.add("DTSTAMP", datetime.now(pytz.utc))

            # Parse date, time, and timezone properly
            try:
                # Parse the date first
                event_date = parser.parse(ev["date"]).date()
                
                # Parse start and end times
                start_time_str = ev["start_time"]
                end_time_str = ev["end_time"]
                
                # Handle timezone
                tz_str = ev.get("timezone", "local")
                if tz_str == "local":
                    # Use system timezone - handle both pytz and zoneinfo
                    local_tz_obj = tzlocal.get_localzone()
                    
                    # Convert to pytz timezone for consistency
                    if hasattr(local_tz_obj, 'zone'):
                        # It's already a pytz timezone
                        local_tz = local_tz_obj
                    else:
                        # It's a zoneinfo timezone, convert to pytz
                        try:
                            local_tz = pytz.timezone(str(local_tz_obj))
                        except:
                            # Fallback to UTC if conversion fails
                            local_tz = pytz.utc
                else:
                    try:
                        # Try to parse timezone (e.g., "EST", "PST", "America/New_York")
                        local_tz = pytz.timezone(tz_str)
                    except:
                        # If timezone parsing fails, fall back to UTC
                        print(f"Warning: Could not parse timezone '{tz_str}', using UTC")
                        local_tz = pytz.utc
                
                # Parse times and combine with date
                start_time = parser.parse(start_time_str).time()
                end_time = parser.parse(end_time_str).time()
                
                # Combine date and time, then localize to the timezone
                start_dt_naive = datetime.combine(event_date, start_time)
                end_dt_naive = datetime.combine(event_date, end_time)
                
                # Localize to the specified timezone
                start_dt = local_tz.localize(start_dt_naive)
                end_dt = local_tz.localize(end_dt_naive)
                
                # Convert to UTC for storage
                start_dt_utc = start_dt.astimezone(pytz.utc)
                end_dt_utc = end_dt.astimezone(pytz.utc)
                
            except Exception as dt_err:
                print(f"Warning: Skipping event '{ev.get('title', 'Unknown')}' due to date/time parsing error: {dt_err}")
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
            print(f"Error building ICS for event {i+1} ({ev.get('title', 'Unknown Title')}): {build_err}")

    return out 