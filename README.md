# Natural Language Calendar Creator

A PyQt6 desktop application that turns natural-language descriptions and event images into validated ICS calendar imports. It supports multiple events in one request and opens the resulting import in the system's default calendar application.

## Features

- Natural language event creation
- **Photo-to-Calendar Integration** - Drag & drop event flyers or photos to create events
- **Multi-event processing** - Create multiple events from text or images in a single description
- Modern UI with light mode
- Validated, all-or-partial calendar import with clear skipped-event reasons
- Strict time-zone handling, including travel across time zones
- Content-verified image attachments with count, byte, and pixel limits
- Rate limiting and retry handling
- Progress indicators and status updates
- Modular code architecture with separation of concerns

## Requirements

- Python 3.10 or higher
- PyQt6
- Google Gemini API key
- macOS, Windows, or Linux with a default application for `.ics` files

## Installation

1. Clone the repository:
```bash
git clone https://github.com/RazeBerry/Text2ICS.git
cd Text2ICS
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
# Recommended (installs runtime deps from pyproject.toml)
pip install -e .

# For development/tests
pip install -e ".[dev]"

# Alternative (runtime-only)
pip install -r requirements.txt

# Reproducible runtime environment
pip install -r requirements.lock
```

## Setting Up the Gemini API Key

**Security First:** The application uses **OS-level encrypted storage** (Keychain on macOS) for your API key. Your key is never stored in plain text in the project directory.

### 🔒 Automatic Security Features

- **Safe Migration:** A legacy project `.env` is migrated to secure storage, then the app asks before deleting the plaintext file
- **Input Validation:** API keys are sanitized to remove quotes, spaces, and invalid characters
- **Secure Permissions:** Fallback `.env` files are created with 0o600 permissions (owner-only access)
- **No Git Exposure:** Legacy `.env` files in the project directory are gitignored to prevent accidental commits

### Recommended Setup (Easiest & Most Secure)

**Just run the app!** On first launch, you'll see a setup dialog:
1. Click "Open Google AI Studio" to get your free API key
2. Copy the key and paste it into the app
3. Click "Save & Continue"

Your key will be stored in your **OS secure credential storage** (macOS Keychain, Windows Credential Manager, or Linux Secret Service) when available and persist across sessions.

### Option 1: Environment Variable (Advanced - Overrides everything)

#### macOS/Linux:
```bash
# Add to ~/.bashrc, ~/.zshrc, or equivalent
export GEMINI_API_KEY_FREE='your-api-key-here'  # preferred
# or
export GEMINI_API_KEY='your-api-key-here'
```
Then restart your terminal or run:
```bash
source ~/.bashrc  # or ~/.zshrc
```

#### Windows (Command Prompt):
```cmd
setx GEMINI_API_KEY_FREE "your-api-key-here"
REM or
setx GEMINI_API_KEY "your-api-key-here"
```
Then restart your command prompt.

#### Windows (PowerShell):
```powershell
[Environment]::SetEnvironmentVariable("GEMINI_API_KEY_FREE", "your-api-key-here", "User")
# or
[Environment]::SetEnvironmentVariable("GEMINI_API_KEY", "your-api-key-here", "User")
```
Then restart PowerShell.

### Option 2: Manual Fallback .env File (Advanced)

**Note:** The app handles this automatically - you usually don't need to do this manually.

If keyring is unavailable, the app will create a secure `.env` file in your user config directory:
- macOS: `~/Library/Application Support/EventCalendarGenerator/.env`
- Linux: `$XDG_CONFIG_HOME/EventCalendarGenerator/.env` (or `~/.config/EventCalendarGenerator/.env`)
- Windows: `%APPDATA%\\EventCalendarGenerator\\.env`

The app automatically sets secure permissions (0o600 - owner-only access) on this file.

## Running the Application

1. Activate your virtual environment (if using one)
2. Run the application:
```bash
python -m eventcalendar
# or (after pip install -e .)
eventcalendar-gui

# Legacy (deprecated, emits warning)
python Calender.py
```
3. On first launch, you'll be prompted to enter your API key - it will be securely stored

### 🔐 Security Notes

- **Never commit `.env` files** with real API keys to version control
- The app stores keys in your **OS secure storage** (macOS Keychain / Windows Credential Manager / Linux Secret Service)
- Legacy `.env` files in the project directory are migrated to secure storage
- You'll be warned if plaintext storage remains and offered a confirmed deletion

## Testing the API Client

To verify that the API client works correctly:

```bash
python test_api_client.py
```

This will test the basic functionality of the API client with a simple example.

## Quality Checks

Run all quality gates locally before pushing:

```bash
ruff check .
vulture src/eventcalendar Calender.py api_client.py config.py exceptions.py
QT_QPA_PLATFORM=offscreen EVENTCALENDAR_RUN_UI_TESTS=1 pytest
```

## Profiling

Use the built-in profiler harness:

```bash
python scripts/profile_performance.py
# machine-readable output
python scripts/profile_performance.py --json > profile.json
```

## Project Structure

The installed app lives entirely in `src/eventcalendar/`. Root-level files such
as `Calender.py` and `api_client.py` are deprecated, source-checkout-only shims;
installed code should import from `eventcalendar`.

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
   - Supports multiple image formats (.png, .jpg, .jpeg, .gif, .webp, .bmp)
   - Accepts up to 8 verified images, 20 MB and 40 megapixels each
   - The app will analyze the images and extract event details automatically
   - Perfect for conference schedules, event posters, or meeting invitations
   - Combine with text input for additional details or modifications

3. Click "Create Event" 
4. A combined import will open in your default calendar application for your confirmation
5. For multiple events or images, you'll see a status indicator showing progress

## Troubleshooting

### API Key Issues
- Verify where the app finds a key without printing the secret:
  ```python
  from eventcalendar.storage.key_manager import get_api_key_source
  print(get_api_key_source()[1])
  ```
- Ensure there are no extra spaces or quotes in your API key
- Try restarting your terminal/IDE after setting the environment variable

### Calendar Integration
- Ensure you have default calendar application set up
- Check file permissions in the directory where .ics files are being created
- Multiple events are merged into one import file
- Verify your desktop has a default handler for `.ics` files

### UI Issues
- Ensure PyQt6 is properly installed
- Check for any system-specific UI scaling issues
- Verify you have the required icon file or remove the icon setting line
- For image drag & drop issues, ensure proper file permissions and supported formats

## Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

## License

This project is licensed under the MIT License - see the LICENSE file for details.
