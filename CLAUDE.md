# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

EventCalendarGenerator (v2.0.0) is a PyQt6 desktop application for macOS that converts natural language descriptions and images (event flyers, photos) into calendar events using Google's Gemini AI. Users input text like "Dinner with Sarah next Thursday at 7pm" or drag-and-drop event images, and the app extracts event details, generates ICS files, and opens them in the system calendar.

The codebase uses a modular Python package architecture (`src/eventcalendar/`) with an Anthropic-inspired design system.

## Commands

### Run the Application
```bash
# Preferred (v2.0.0+)
python -m eventcalendar

# Via installed entry point (after pip install -e .)
eventcalendar-gui

# Legacy (deprecated, emits warning)
python Calender.py
```

### Run Tests
```bash
pytest                           # All tests
pytest test_calender.py          # UI and ICS parsing tests
pytest test_thread_safety.py     # Thread safety and data model tests
python test_api_client.py        # Manual API integration test (requires GEMINI_API_KEY)
```

### Install Dependencies
```bash
pip install -r requirements.txt
pip install -e .                 # Editable install for entry points
```

## Package Architecture

```
src/eventcalendar/               # Main package (v2.0.0)
├── __init__.py                  # Public API exports
├── __main__.py                  # python -m entrypoint
├── config/
│   ├── constants.py             # Status messages, error patterns, ABBR_TO_TZ
│   └── settings.py              # APIConfig, UIConfig frozen dataclasses
├── core/
│   ├── api_client.py            # CalendarAPIClient (Gemini integration)
│   ├── event_model.py           # CalendarEvent dataclass
│   ├── ics_builder.py           # build_ics_from_events(), combine_ics_strings()
│   ├── retry.py                 # is_retryable_error(), smart retry logic
│   └── timezone_utils.py        # resolve_timezone(), normalize_tz()
├── storage/
│   ├── key_manager.py           # get_api_key(), save_api_key()
│   ├── keyring_storage.py       # OS secure storage (Keychain/Credential Manager/Secret Service)
│   └── env_storage.py           # .env file handling
├── ui/
│   ├── main_window.py           # NLCalendarCreator(QMainWindow)
│   ├── preview.py               # Event preview parsing
│   ├── error_messages.py        # get_user_friendly_error()
│   ├── theme/
│   │   ├── manager.py           # ThemeManager (thread-safe singleton)
│   │   ├── palettes.py          # LIGHT_PALETTE, DARK_PALETTE
│   │   ├── colors.py            # get_color(key), COLORS dict
│   │   └── scales.py            # FONT_FAMILIES, TYPOGRAPHY_SCALE, SPACING_SCALE
│   ├── styles/
│   │   ├── base.py              # px() helper
│   │   ├── manager.py           # StyleManager for widget refresh
│   │   └── button_styles.py     # ButtonStyles static methods
│   └── widgets/
│       ├── image_area.py        # ImageAttachmentArea (drag-drop)
│       └── api_key_dialog.py    # APIKeySetupDialog
├── utils/
│   ├── date_parsing.py          # Date/time extraction regexes
│   ├── masking.py               # mask_key() for secure logging
│   └── paths.py                 # get_config_dir(), get_data_dir()
└── exceptions/
    └── errors.py                # CalendarAPIError hierarchy
```

### Backward Compatibility Layer

Root-level files (`Calender.py`, `api_client.py`, `config.py`, `exceptions.py`) re-export from the `eventcalendar` package with `DeprecationWarning`. New code should import from the package:

```python
# Preferred
from eventcalendar import NLCalendarCreator
from eventcalendar.core.api_client import CalendarAPIClient

# Deprecated (still works, emits warning)
from Calender import NLCalendarCreator
```

## Key Modules Reference

### Configuration
- `eventcalendar.config.settings.API_CONFIG` - Model name, retries, backoff, temperature
- `eventcalendar.config.settings.UI_CONFIG` - Debounce timings, window size, executor workers
- `eventcalendar.config.constants` - All string constants, error patterns, ABBR_TO_TZ timezone map

### Core
- `CalendarAPIClient.get_event_data(text, images, status_callback)` - Main Gemini extraction call (returns event dicts)
- `CalendarAPIClient.create_calendar_event(text, images, status_callback)` - Back-compat helper (returns merged ICS string)
- `CalendarEvent.from_dict(data)` / `.to_dict()` - Event serialization with validation
- `build_ics_from_events(events)` - Convert events to ICS format
- `is_retryable_error(error)` - Determine if error is transient

### Storage
- `load_api_key()` - Retrieve API key from priority chain
- `save_api_key(key)` - Store securely in keychain or config

### UI
- `NLCalendarCreator` - Main application window
- `ThemeManager.set_theme("dark"/"light")` - Toggle application theme
- `get_color("accent")` - Get theme-aware color value
- `ButtonStyles.accent()` - Get styled button stylesheet

## Design System (Anthropic-Inspired)

### Font Configuration
All fonts standardized to SF Mono via centralized constant:
```python
from eventcalendar.ui.theme.scales import FONT_FAMILIES, FONT_MONO
# FONT_FAMILIES = {"sans": "SF Mono...", "serif": "SF Mono...", "mono": "SF Mono..."}
```

### Color Access
Colors are theme-aware and accessed via `get_color()`:
```python
from eventcalendar.ui.theme.colors import get_color
bg = get_color("background")        # Returns current theme color
accent = get_color("accent")        # Terracotta: #CC5A47 (light), #E07058 (dark)
```

### Spacing & Sizing
```python
from eventcalendar.ui.theme.scales import SPACING_SCALE, BORDER_RADIUS
from eventcalendar.ui.styles.base import px
margin = px(SPACING_SCALE["md"])    # "16px"
radius = px(BORDER_RADIUS["lg"])    # "16px"
```

### Button Styling
```python
from eventcalendar.ui.styles.button_styles import ButtonStyles
button.setStyleSheet(ButtonStyles.accent())   # Primary action
button.setStyleSheet(ButtonStyles.ghost())    # Subtle action
button.setStyleSheet(ButtonStyles.danger())   # Destructive action
```

### Color Palette Keys
- **Backgrounds**: `background`, `background_secondary`, `background_tertiary`, `surface_elevated`
- **Text**: `text_primary`, `text_secondary`, `text_tertiary`, `text_placeholder`
- **Accents**: `accent`, `accent_hover`, `accent_muted`, `glow_accent`
- **Status**: `success`, `warning`, `error`
- **UI**: `border`, `border_subtle`, `divider`

## Threading Model

The app uses `ThreadPoolExecutor` for background API calls to keep the UI responsive:
- `NLCalendarCreator._executor` manages worker threads (max 2, configurable via `UI_CONFIG`)
- Signals (`update_status_signal`, `finalize_events_signal`) communicate results back to the main Qt thread
- `ThemeManager` uses a class-level lock for thread-safe theme state
- Futures tracked with `_threads_lock` for proper cleanup

## Exception Hierarchy

```
CalendarAPIError (base)
├── TimezoneResolutionError    # Failed to resolve timezone
├── EventValidationError       # Missing required fields
├── ImageProcessingError       # Image upload/processing failed
├── APIResponseError           # Invalid API response format
└── RetryExhaustedError        # Max retries exceeded
```

### Retry Classification
Defined in `eventcalendar.core.retry`:
- **Non-retryable**: Invalid API key, permission denied, quota exceeded
- **Retryable**: Timeout, service unavailable, network errors
- Uses pattern matching on error strings via `is_retryable_error()`

## API Key Storage Priority

1. `GEMINI_API_KEY_FREE` environment variable (preferred for free tier)
2. `GEMINI_API_KEY` environment variable
3. OS secure storage via `keyring` library:
   - macOS: Keychain
   - Windows: Credential Manager
   - Linux: Secret Service (requires libsecret)
4. User config directory `.env`:
   - macOS: `~/Library/Application Support/EventCalendarGenerator/.env`
   - Windows: `%APPDATA%\EventCalendarGenerator\.env`
   - Linux: `~/.config/EventCalendarGenerator/.env` (or `$XDG_CONFIG_HOME`)
5. Legacy: `.env` in project directory (auto-migrates to secure storage)

## Key Implementation Details

- All fonts standardized to SF Mono via `FONT_FAMILIES` constant in `ui/theme/scales.py`
- Times are parsed exactly as stated and converted to UTC for ICS storage
- `ABBR_TO_TZ` in `config/constants.py` maps timezone abbreviations (EST, PST, etc.) to IANA zones
- Multiple images can be attached; they're uploaded to Gemini before the text prompt
- ICS files use CRLF line endings per RFC5545
- Event UIDs are regenerated with `@nl-calendar` suffix when combining ICS documents
- Sensitive data masked before logging via `utils/masking.py`
