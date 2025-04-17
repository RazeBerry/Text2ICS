import os
from datetime import datetime
import time
from typing import Optional, List, Tuple
from string import Formatter


class CalendarAPIClient:
    # Class-level constant for SYSTEM instructions
    SYSTEM_PROMPT = """
Follow these steps to create the .ics file content:

1. Carefully parse the event details to identify if there are multiple events described. If so, separate them for individual processing.

2. For each event, extract all relevant information such as event title, date, time, location, description, and any other provided details. If the event involves flights between different cities, be aware that the departure and arrival times may be in different time zones. Adjust the event times accordingly by converting them to UTC, ensuring accurate reflection of time differences. Employ a chain-of-thought process with reflection and verification to ensure proper handling of these time differences.

3. Generate the .ics file content using the following strict formatting rules:
   REQUIRED CALENDAR STRUCTURE:
   - BEGIN:VCALENDAR
   - VERSION:2.0 (mandatory)
   - PRODID:-//Your identifier//EN (mandatory)
   
   REQUIRED EVENT FORMATTING:
   - BEGIN:VEVENT
   - UID: Generate unique using format YYYYMMDDTHHMMSSZ-identifier@domain
   - DTSTAMP: Current time in format YYYYMMDDTHHMMSSZ
   - DTSTART: Event start in format YYYYMMDDTHHMMSSZ
   - DTEND: Event end in format YYYYMMDDTHHMMSSZ
   - SUMMARY: Event title
   - DESCRIPTION: Properly escaped text using backslash before commas, semicolons, and newlines (\, \; \n)
   
   OPTIONAL BUT RECOMMENDED:
   - LOCATION: Venue details with proper escaping
   - CATEGORIES: Event type/category
   
   REMINDER STRUCTURE:
   - BEGIN:VALARM
   - ACTION:DISPLAY
   - DESCRIPTION:Reminder
   - TRIGGER:-PT30M (or your preferred timing)
   - END:VALARM
   
   CRITICAL FORMATTING RULES:
   1. DATETIME FIELD REQUIREMENTS (STRICTLY ENFORCED):
      - MANDATORY 'T' separator between date and time components
      - Format must be: YYYYMMDD'T'HHMMSS'Z'
      - Examples of CORRECT format:
        * 20241025T130000Z  ✓ (correct with T separator)
        * 20250101T090000Z  ✓ (correct with T separator)
      - Examples of INCORRECT format:
        * 20241025130000Z   ✗ (missing T separator)
        * 2024-10-25T13:00:00Z  ✗ (contains hyphens and colons)
        * 20241025 130000Z  ✗ (contains space instead of T)
      - The 'Z' suffix is required for UTC timezone
      - This format is REQUIRED for ALL datetime fields:
        * DTSTART
        * DTEND
        * DTSTAMP
        * UID (when using timestamp)

   2. EXAMPLE OF CORRECT FORMATTING:
      ```ics
      BEGIN:VCALENDAR
      VERSION:2.0
      PRODID:-//Example Corp//Calendar App//EN
      BEGIN:VEVENT
      UID:20240325T123000Z-flight123@example.com
      DTSTAMP:20240325T123000Z
      DTSTART:20240401T090000Z
      DTEND:20240401T100000Z
      SUMMARY:Flight BA123
      DESCRIPTION:British Airways | Economy\\nDeparture: T2\\nArrival: T5
      END:VEVENT
      END:VCALENDAR
      ```

   3. VALIDATION REQUIREMENTS:
      - Every datetime field MUST include the T separator
      - No exceptions are allowed for any datetime fields
      - Calendar applications will reject files without proper T separators
      - Always validate before creating the ICS file

4. Ensure all text is properly escaped, replacing any newline characters in the SUMMARY, LOCATION, or DESCRIPTION fields with "\\n".
5. Wrap each complete .ics file content in numbered <ics_file_X> tags, where X is the event number (starting from 1).

Here's a detailed breakdown of the .ics file structure:

BEGIN:VCALENDAR\r\n
VERSION:2.0\r\n
PRODID:-//Your Company//Your Product//EN\r\n
BEGIN:VEVENT\r\n
UID:YYYYMMDDTHHMMSSZ-identifier@domain.com\r\n
DTSTAMP:20250207T120000Z           # Current time, must include T and Z\r\n
DTSTART:20250207T200000Z           # Must include T and Z\r\n
DTEND:20250207T210000Z             # Must include T and Z\r\n
SUMMARY:Event Title\r\n
LOCATION:Location with\\, escaped commas\r\n
DESCRIPTION:Description with\\, escaped commas\\; and semicolons\\nand newlines\r\n
BEGIN:VALARM\r\n
ACTION:DISPLAY\r\n
DESCRIPTION:Reminder\r\n
TRIGGER:-PT30M\r\n
END:VALARM\r\n
END:VEVENT\r\n
END:VCALENDAR
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
        file = self.genai.upload_file(path, mime_type=mime_type)
        print(f"Uploaded file '{file.display_name}' as: {file.uri}")
        return file

    def create_calendar_event(self, event_description: str, image_data: list[tuple[str, str, str]],
                              status_callback: callable) -> Optional[str]:
        """
        Create calendar event with enhanced error handling and status updates.
        This method supports both text and image attachments.
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
                status_callback(f"Attempting to create event... (Try {attempt + 1}/{self.max_retries})")
                print(f"DEBUG: Attempt {attempt + 1}/{self.max_retries}")
                print("DEBUG: Generated API prompt (first 200 chars):", api_prompt[:200])

                # Prepare chat history (add any uploaded image parts if images are provided)
                history = []
                if image_data:
                    image_parts = []
                    for img in image_data:
                        # Unpack tuple: (file_path, mime_type, base64_data)
                        file_path, mime_type, _ = img  
                        uploaded_file = self.upload_to_gemini(file_path, mime_type=mime_type)
                        image_parts.append(uploaded_file)
                    history.append({
                        "role": "user",
                        "parts": image_parts
                    })

                # Start the chat session with the provided image history (if any)
                chat_session = self.model.start_chat(history=history)
                # Send the text prompt as the follow-up message.
                message = chat_session.send_message(api_prompt)
                
                # Try to obtain the text response.
                response_text = getattr(message, 'text', None)
                if response_text is None:
                    response_text = str(message)
                
                print("DEBUG: API Response:", response_text)
                print("DEBUG: API call successful on attempt", attempt + 1)
                return response_text

            except Exception as e:
                print(f"DEBUG: Exception on attempt {attempt + 1}: {e}")
                if attempt < self.max_retries - 1:
                    delay = self.base_delay * (2 ** attempt)
                    status_callback(f"Error occurred, retrying in {delay} seconds...")
                    print(f"DEBUG: Retrying in {delay} seconds...")
                    time.sleep(delay)
                    continue
                print("DEBUG: Max retries reached. Raising exception.")
                raise

        print("DEBUG: Failed to create calendar event after retries.")
        return None 