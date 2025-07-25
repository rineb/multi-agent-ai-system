import json
import os
from datetime import datetime
from typing import Type
import pytz

import requests
from crewai.tools import BaseTool
from pydantic import BaseModel, Field

class GoogleCalendarBusyPeriodsToolInput(BaseModel):
    """Input schema for GoogleCalendarBusyPeriodsToolInput."""
    calendar_id: str = Field(..., description="Google Calendar ID")
    start_date: str = Field(..., description="Start date in YYYY-MM-DD format")
    end_date: str = Field(..., description="End date in YYYY-MM-DD format")
    timezone: str = Field(default="Europe/Berlin", description="Timezone")

class GoogleCalendarBusyPeriodsTool(BaseTool):
    name: str = 'Google Calendar Busy Periods Finder'
    description: str = "Fetches busy periods from Google Calendar based on existing calendar events."
    args_schema: Type[BaseModel] = GoogleCalendarBusyPeriodsToolInput

    def _run(self, calendar_id: str, start_date: str, end_date: str, timezone: str = "UTC") -> str:
        """Fetch calendar events and return structured busy periods."""
        
        api_key = os.getenv("GOOGLE_CALENDAR_API_KEY")
        if not api_key:
            return json.dumps({"error": "GOOGLE_CALENDAR_API_KEY not set", "busy_periods": []})

        try:
            start_datetime = f"{start_date}T00:00:00Z"
            end_datetime = f"{end_date}T23:59:59Z"

            # Make call to Google Calendar API endpoint to fetch event list
            url = f"https://www.googleapis.com/calendar/v3/calendars/{calendar_id}/events"
            params = {
                'key': api_key,
                'timeMin': start_datetime,
                'timeMax': end_datetime,
                'singleEvents': 'true',
                'orderBy': 'startTime',
                'maxResults': 2500
            }
            headers = {
                'Accept': 'application/json'
            }

            response = requests.get(url, params=params, headers=headers, timeout=30)
            response.raise_for_status()

            events = response.json().get('items', [])
            busy_periods = self.extract_busy_periods(events, timezone)

            return json.dumps({
                "calendar_id": calendar_id,
                "date_range": {"start": start_date, "end": end_date},
                "timezone": timezone,
                "busy_periods": busy_periods
            }, indent=2)
        except Exception as e:
            return json.dumps({
                "error": str(e),
                "busy_periods": [],
            })

    def extract_busy_periods(self, events, timezone):
        busy_periods = []
        tz = pytz.timezone(timezone)

        for event in events:
            start_info = event.get('start', {})
            end_info = event.get('end', {})

            if not start_info or not end_info:
                continue

            # set event_type based on the duration of the event ("timed" or "all_day")
            if 'dateTime' in start_info:
                start_dt = datetime.fromisoformat(start_info['dateTime'].replace('Z', '+00:00')).astimezone(tz)
                end_dt = datetime.fromisoformat(end_info['dateTime'].replace('Z', '+00:00')).astimezone(tz)
                event_type = "timed"
            else:
                start_dt = datetime.fromisoformat(start_info['date']).replace(tzinfo=tz)
                end_dt = datetime.fromisoformat(end_info['date']).replace(tzinfo=tz)
                event_type = "all_day"

            busy_periods.append({
                "start": start_dt.isoformat(),
                "end": end_dt.isoformat(),
                "title": event.get('summary', 'No title or event details are private'),
                "type": event_type
            })

        busy_periods.sort(key=lambda x: x['start'])

        return busy_periods
