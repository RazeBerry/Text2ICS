# Natural Language Calendar Creator

A PyQt6-based desktop application that lets you create calendar events using natural language. Simply describe your event in plain English, and the app will generate and add it to your calendar automatically.

## Features

- Natural language event creation
- Modern dark mode UI
- Global keyboard shortcut (Ctrl+Shift+E)
- Automatic calendar integration
- Rate limiting and retry handling
- Progress indicators and status updates

## Requirements

- Python 3.8 or higher
- PyQt6
- Anthropic API key
- macOS (calendar integration currently optimized for macOS)

## Installation

1. Clone the repository:
```bash
git clone https://github.com/RazeBerry/Calender2ICS
cd Calender2ICS
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
pip install PyQt6 anthropic
```

## Setting Up the Anthropic API Key

The application requires an Anthropic API key to function. You can set it up in several ways:

### Option 1: Environment Variable (Recommended)

#### macOS/Linux:
```bash
# Add to ~/.bashrc, ~/.zshrc, or equivalent
export ANTHROPIC_API_KEY='your-api-key-here'
```
Then restart your terminal or run:
```bash
source ~/.bashrc  # or ~/.zshrc
```

#### Windows (Command Prompt):
```cmd
setx ANTHROPIC_API_KEY "your-api-key-here"
```
Then restart your command prompt.

#### Windows (PowerShell):
```powershell
[Environment]::SetEnvironmentVariable("ANTHROPIC_API_KEY", "your-api-key-here", "User")
```
Then restart PowerShell.

### Option 2: .env File
Create a `.env` file in the project root:
```
ANTHROPIC_API_KEY=your-api-key-here
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
python calender.py
```

## Usage

1. Launch the application using the command above or the global shortcut (Ctrl+Shift+E)
2. Type your event description in natural language, for example:
   - "Team standup on Monday at 10am for 30 minutes"
   - "Lunch with Sarah at Cafe Luna next Thursday 12:30pm"
   - "Dentist appointment on March 15th at 2pm"
3. Click "Create Event" or press Enter
4. The event will be created and opened in your default calendar application

## Troubleshooting

### API Key Issues
- Verify your API key is correctly set by printing the environment variable:
  ```python
  import os
  print(os.getenv("ANTHROPIC_API_KEY"))
  ```
- Ensure there are no extra spaces or quotes in your API key
- Try restarting your terminal/IDE after setting the environment variable

### Calendar Integration
- Ensure you have default calendar application set up
- Check file permissions in the directory where .ics files are being created
- Verify your system can handle the `open` command (macOS) or equivalent

### UI Issues
- Ensure PyQt6 is properly installed
- Check for any system-specific UI scaling issues
- Verify you have the required icon file or remove the icon setting line

## Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

## License

This project is licensed under the MIT License - see the LICENSE file for details.
