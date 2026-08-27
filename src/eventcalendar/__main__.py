"""Entry point for running eventcalendar as a module.

Usage: python -m eventcalendar
"""

import sys
import logging
from pathlib import Path


def main():
    """Main entry point for the application."""
    # Configure logging
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )

    # Import PyQt6 and create application
    from PyQt6.QtWidgets import QApplication
    from PyQt6.QtGui import QIcon
    from eventcalendar.ui.main_window import NLCalendarCreator

    app = QApplication(sys.argv)
    app.setApplicationName("EventCalendarGenerator")

    # Set application icon (resolved relative to package, not cwd)
    icon_path = Path(__file__).parent / "resources" / "icon.png"
    if icon_path.exists():
        app.setWindowIcon(QIcon(str(icon_path)))

    # Show the shell first; credential discovery and first-run onboarding are
    # scheduled by the window after the event loop starts.
    window = NLCalendarCreator(prompt_for_api_key=True)
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
