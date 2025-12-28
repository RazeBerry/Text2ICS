# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

EventCalendarGenerator is a PyQt6 desktop application for macOS that converts natural language descriptions and images (event flyers, photos) into calendar events using Google's Gemini AI. Users input text like "Dinner with Sarah next Thursday at 7pm" or drag-and-drop event images, and the app extracts event details, generates ICS files, and opens them in the system calendar.

## Commands

### Run the Application
```bash
python Calender.py
```

### Run Tests
```bash
# All tests with pytest
pytest

# Individual test files
python test_api_client.py          # Manual API integration test (requires GEMINI_API_KEY)
pytest test_calender.py            # UI and ICS parsing tests
pytest test_thread_safety.py       # Thread safety and data model tests
```

### Install Dependencies
```bash
pip install -r requirements.txt
```

## Architecture

### Core Components

**`Calender.py`** - Main application (~1200 lines)
- `NLCalendarCreator(QMainWindow)` - Main window with text input, image drop area, and live preview
- `ImageAttachmentArea(QLabel)` - Drag-and-drop widget that handles file URLs and in-memory image data
- `APIKeySetupDialog(QDialog)` - First-run setup dialog for Gemini API key
- `ThemeManager` - Thread-safe singleton for light/dark theme switching
- `combine_ics_strings()` - Merges multiple ICS documents preserving timezone data
- API key management functions with priority: env var → keyring → user config → legacy .env

**`api_client.py`** - Gemini API integration
- `CalendarAPIClient` - Handles LLM prompts with retry logic and exponential backoff
- `CalendarEvent` - Dataclass for validated event data with `from_dict()` and `to_dict()`
- `build_ics_from_events()` - Converts event dictionaries to ICS format with timezone handling
- Smart retry logic via `_is_retryable_error()` distinguishes transient vs permanent failures

**`config.py`** - Frozen dataclass configuration for API and UI settings

**`exceptions.py`** - Custom exception hierarchy: `CalendarAPIError`, `EventValidationError`, `RetryExhaustedError`, etc.

### Threading Model

The app uses `ThreadPoolExecutor` for background API calls to keep the UI responsive:
- `NLCalendarCreator._executor` manages worker threads
- Signals (`update_status_signal`, `finalize_events_signal`) communicate results back to the main Qt thread
- `ThemeManager` uses a class-level lock for thread-safe theme state

### API Key Storage Priority

1. `GEMINI_API_KEY_FREE` / `GEMINI_API_KEY` environment variables
2. macOS Keychain via `keyring` library
3. User config directory: `~/Library/Application Support/EventCalendarGenerator/.env`
4. Legacy: `.env` in project directory (auto-migrates to secure storage)

### Design System

Uses a custom design system with:
- `LIGHT_PALETTE` / `DARK_PALETTE` color dictionaries
- `TYPOGRAPHY_SCALE`, `SPACING_SCALE`, `BORDER_RADIUS` constants
- `get_color(key)` returns theme-aware colors
- `_DynamicColors` class provides backwards-compatible `COLORS` dict

## Key Implementation Details

- Times are parsed exactly as stated and converted to UTC for ICS storage
- Timezone abbreviations (EST, PST, etc.) are mapped to IANA zones via `ABBR_TO_TZ` in `api_client.py`
- Multiple images can be attached; they're uploaded to Gemini before the text prompt
- ICS files use CRLF line endings per RFC5545
- Event UIDs are regenerated with `@nl-calendar` suffix when combining ICS documents
