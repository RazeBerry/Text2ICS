"""Entry point for running eventcalendar as a module.

Usage: python -m eventcalendar
"""

import sys
import logging


def main():
    """Main entry point for the application."""
    # Configure logging
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )

    # Import PyQt6 and create application
    from PyQt6.QtWidgets import QApplication
    from eventcalendar.ui.main_window import NLCalendarCreator
    from eventcalendar.storage.key_manager import load_api_key
    from eventcalendar.ui.widgets.api_key_dialog import APIKeySetupDialog

    app = QApplication(sys.argv)
    app.setApplicationName("EventCalendarGenerator")

    # Check for API key and show setup if needed
    api_key = load_api_key()
    if not api_key:
        dialog = APIKeySetupDialog()
        if not dialog.exec():
            sys.exit(0)

    # Create and show main window
    window = NLCalendarCreator()
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
