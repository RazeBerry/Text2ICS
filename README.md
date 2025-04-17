# Natural Language Calendar Creator

A PyQt6-based desktop application that lets you create calendar events using natural language and photos! Simply describe your event(s) in plain English or drag & drop event photos/flyers, and the app will generate and add them to your calendar automatically. Supports creating multiple events in a single entry!

## Features

- Natural language event creation
- **Photo-to-Calendar Integration** - Drag & drop event flyers or photos to create events
- **Multi-event processing** - Create multiple events from text or images in a single description
- Modern UI with light mode
- Automatic calendar integration
- Rate limiting and retry handling
- Progress indicators and status updates
- Modular code architecture with separation of concerns

## Requirements

- Python 3.8 or higher
- PyQt6
- Google Generative AI (Gemini) API key
- macOS (calendar integration currently optimized for macOS)

## Installation

1. Clone the repository:
```bash
git clone https://github.com/username/EventCalenderGenerator
cd EventCalenderGenerator
```

2. Create and activate a virtual environment (recommended):
```bash
# On macOS/Linux
python3 -m venv venv
source venv/bin/activate

# On Windows
python -m venv venv
.\venv\Scripts\activate
```

3. Install required packages:
```bash
pip install PyQt6 google-generativeai
```

## Setting Up the Gemini API Key

The application requires a Google Gemini API key to function. You can set it up in several ways:

### Option 1: Environment Variable (Recommended)

#### macOS/Linux:
```bash
# Add to ~/.bashrc, ~/.zshrc, or equivalent
export GEMINI_API_KEY='your-api-key-here'
```
Then restart your terminal or run:
```bash
source ~/.bashrc  # or ~/.zshrc
```

#### Windows (Command Prompt):
```cmd
setx GEMINI_API_KEY "your-api-key-here"
```
Then restart your command prompt.

#### Windows (PowerShell):
```powershell
[Environment]::SetEnvironmentVariable("GEMINI_API_KEY", "your-api-key-here", "User")
```
Then restart PowerShell.

### Option 2: .env File
Create a `.env` file in the project root:
```
GEMINI_API_KEY=your-api-key-here
```

Then install and use python-dotenv:
```bash
pip install python-dotenv
```

Add to the top of your script:
```python
from dotenv import load_dotenv
load_dotenv()
```

## Running the Application

1. Ensure your environment variable is set and virtual environment is activated
2. Run the application:
```bash
python Calender.py
```

## Testing the API Client

To verify that the API client works correctly:

```bash
python test_api_client.py
```

This will test the basic functionality of the API client with a simple example.

## Project Structure

The project is organized as follows:

- `Calender.py` - Main application with UI components and event handling
- `api_client.py` - Separated API interaction module for better modularity
- `test_api_client.py` - Testing script for the API client

## Usage

1. Launch the application using the command above

2. Create events in two ways:

   ### Text Input
   Type your event description(s) in natural language. You can create multiple events in a single entry! For example:
   - Single event: "Team standup on Monday at 10am for 30 minutes"
   - Single event: "Lunch with Sarah at Cafe Luna next Thursday 12:30pm"
   - Multiple events: "Daily standup meetings Monday through Friday at 9:30am for 30 minutes"
   - Multiple events: "Yoga classes every Tuesday and Thursday at 6pm for the next 4 weeks"
   - Multiple events: "Doctor appointment on March 15th at 2pm and follow-up visit on March 29th same time"

   ### Photo Input
   - Simply drag & drop event flyers, screenshots, or photos into the attachment area
   - Supports multiple image formats (.png, .jpg, .jpeg, .gif)
   - The app will analyze the images and extract event details automatically
   - Perfect for conference schedules, event posters, or meeting invitations
   - Combine with text input for additional details or modifications

3. Click "Create Event" 
4. The event(s) will be created and opened in your default calendar application
5. For multiple events or images, you'll see a status indicator showing progress

## Troubleshooting

### API Key Issues
- Verify your API key is correctly set by printing the environment variable:
  ```python
  import os
  print(os.getenv("GEMINI_API_KEY"))
  ```
- Ensure there are no extra spaces or quotes in your API key
- Try restarting your terminal/IDE after setting the environment variable

### Calendar Integration
- Ensure you have default calendar application set up
- Check file permissions in the directory where .ics files are being created
- For multiple events, each event will open separately in your calendar application
- Verify your system can handle the `open` command (macOS) or equivalent

### UI Issues
- Ensure PyQt6 is properly installed
- Check for any system-specific UI scaling issues
- Verify you have the required icon file or remove the icon setting line
- For image drag & drop issues, ensure proper file permissions and supported formats

## Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

## License

This project is licensed under the MIT License - see the LICENSE file for details.
