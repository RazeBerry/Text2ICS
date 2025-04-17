#!/usr/bin/env python3
import os
import sys
from api_client import CalendarAPIClient

def main():
    """Simple test function to verify that the API client works correctly."""
    print("Testing CalendarAPIClient...")
    
    # Check for API key
    api_key = os.environ.get('GEMINI_API_KEY')
    if not api_key:
        print("Error: GEMINI_API_KEY environment variable not set.")
        print("Please set it before running this test.")
        sys.exit(1)
    
    # Initialize the client
    try:
        client = CalendarAPIClient(api_key=api_key)
        print("Successfully initialized the API client.")
    except Exception as e:
        print(f"Error initializing the API client: {e}")
        sys.exit(1)
    
    # Test a simple event creation
    event_description = "Coffee with John tomorrow at 10am"
    
    print(f"Testing event creation with description: '{event_description}'")
    try:
        result = client.create_calendar_event(
            event_description=event_description,
            image_data=[],
            status_callback=lambda msg: print(f"Status: {msg}")
        )
        
        print("\nAPI Response:")
        print("-" * 50)
        print(result[:500] + "..." if len(result) > 500 else result)
        print("-" * 50)
        print("Test completed successfully!")
    except Exception as e:
        print(f"Error creating calendar event: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main() 