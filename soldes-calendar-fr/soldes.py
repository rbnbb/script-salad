#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Generate an .ics calendar with French sales (soldes) dates for the next 100 years.

Rules encoded (metropolitan France, general case):
- Winter: starts the second Wednesday of January at 08:00 local convention,
          BUT if that second Wednesday falls after January 12, start is the first Wednesday.
- Summer: starts the last Wednesday of June at 08:00,
          BUT if that last Wednesday falls after June 28, start is the previous (penultimate) Wednesday.
- Each period lasts exactly 4 weeks (28 days).

We create all-day *date* events spanning 28 days (DTEND exclusive), which import cleanly in Google Calendar.
If you prefer time-based events at 08:00, you can switch DTSTART/DTEND to datetime with a TZID.

Output: soldes_france_<startyear>_<endyear>.ics
"""

from datetime import date, timedelta, datetime
from icalendar import Calendar, Event
import calendar
import uuid

# ---------- Config ----------
YEARS_AHEAD = 100           # generate starting from current year, inclusive
CAL_NAME = "Soldes France (métropole) – 4 semaines"
CAL_DESC = "Soldes d'hiver et d'été (règle légale générale) – chaque période dure 4 semaines."
FILE_NAME_TEMPLATE = "soldes_france_{start}_{end}.ics"
# Use all-day events (no TZ issues). Set to True if you want timed events at 08:00.
ALL_DAY_EVENTS = True
START_HOUR = 8  # used only if ALL_DAY_EVENTS == False


# ---------- Date helpers ----------
def nth_weekday_of_month(year: int, month: int, weekday: int, n: int) -> date:
    """
    Return the date of the n-th given weekday (0=Monday .. 6=Sunday) in a given month.
    Example: 2nd Wednesday of Jan 2025 -> weekday=2 (Wednesday), n=2.
    """
    first_weekday, days_in_month = calendar.monthrange(year, month)
    # day of month for first occurrence of target weekday
    first_occurrence = 1 + ((weekday - first_weekday) % 7)
    day = first_occurrence + (n - 1) * 7
    if day > days_in_month:
        raise ValueError("n-th weekday does not exist in this month")
    return date(year, month, day)


def last_weekday_of_month(year: int, month: int, weekday: int) -> date:
    """
    Return the date of the last given weekday (0=Monday .. 6=Sunday) in a given month.
    """
    last_day = calendar.monthrange(year, month)[1]
    last_date = date(year, month, last_day)
    offset = (last_date.weekday() - weekday) % 7
    return last_date - timedelta(days=offset)


# ---------- Legal rule implementations ----------
def winter_sales_start(year: int) -> date:
    """
    Winter: second Wednesday of January at 8:00,
    but if that date is after Jan 12 -> use first Wednesday of January.
    We return a date (no time) because we're creating all-day events by default.
    """
    second_wed = nth_weekday_of_month(year, 1, weekday=2, n=2)  # Wednesday=2
    if second_wed.day > 12:
        return nth_weekday_of_month(year, 1, weekday=2, n=1)
    return second_wed


def summer_sales_start(year: int) -> date:
    """
    Summer: last Wednesday of June at 8:00,
    but if that date is after June 28 -> use the penultimate Wednesday (minus 7 days).
    """
    last_wed = last_weekday_of_month(year, 6, weekday=2)  # Wednesday=2
    if last_wed.day > 28:
        return last_wed - timedelta(days=7)
    return last_wed


# ---------- ICS generation ----------
def make_event(summary: str, start_d: date, duration_days: int, description: str) -> Event:
    """
    Create an iCalendar VEVENT. For all-day: use date-only DTSTART/DTEND.
    DTEND is exclusive, so add `duration_days` to start.
    """
    evt = Event()
    evt.add("summary", summary)
    evt.add("uid", f"{uuid.uuid4()}@soldes-france")
    evt.add("dtstamp", datetime.utcnow())

    if ALL_DAY_EVENTS:
        evt.add("dtstart", start_d)
        evt.add("dtend", start_d + timedelta(days=duration_days))
    else:
        # If you prefer a timed event at 08:00 (local), set TZID or keep it floating.
        start_dt = datetime(start_d.year, start_d.month, start_d.day, START_HOUR, 0, 0)
        end_dt = start_dt + timedelta(days=duration_days)
        evt.add("dtstart", start_dt)  # could add parameters like {"tzid": "Europe/Paris"} with icalendar
        evt.add("dtend", end_dt)

    evt.add("description", description)
    return evt


def build_calendar(start_year: int, years_ahead: int) -> Calendar:
    cal = Calendar()
    cal.add("prodid", "-//Soldes France//Calendar 1.0//FR")
    cal.add("version", "2.0")
    cal.add("X-WR-CALNAME", CAL_NAME)
    cal.add("X-WR-CALDESC", CAL_DESC)

    for y in range(start_year, start_year + years_ahead):
        # Winter
        w_start = winter_sales_start(y)
        w_evt = make_event(
            summary=f"Soldes d’hiver {y}",
            start_d=w_start,
            duration_days=28,
            description=(
                "Soldes d’hiver (règle légale générale, métropole) : "
                "début le 2e mercredi de janvier à 08:00, "
                "avancé au 1er mercredi si le 2e intervient après le 12. "
                "Durée : 4 semaines."
            ),
        )
        cal.add_component(w_evt)

        # Summer
        s_start = summer_sales_start(y)
        s_evt = make_event(
            summary=f"Soldes d’été {y}",
            start_d=s_start,
            duration_days=28,
            description=(
                "Soldes d’été (règle légale générale, métropole) : "
                "début le dernier mercredi de juin à 08:00, "
                "avancé à l’avant-dernier mercredi si le dernier intervient après le 28. "
                "Durée : 4 semaines."
            ),
        )
        cal.add_component(s_evt)

    return cal


def main():
    today = date.today()
    start_year = today.year
    end_year = start_year + YEARS_AHEAD - 1
    cal = build_calendar(start_year, YEARS_AHEAD)
    file_name = FILE_NAME_TEMPLATE.format(start=start_year, end=end_year)
    with open(file_name, "wb") as f:
        f.write(cal.to_ical())
    print(f"ICS generated: {file_name}")


if __name__ == "__main__":
    main()
