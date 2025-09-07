from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Optional, Iterable

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import StreamingResponse

from forecast.calendar import expand_calendar, _default_db_path


router = APIRouter()


def _money(cents: int) -> str:
    try:
        return f"$ {cents/100:,.2f}"
    except Exception:
        return str(cents)


def _ical_dt(d: datetime) -> str:
    # UTC timestamp format for DTSTAMP
    return d.strftime("%Y%m%dT%H%M%SZ")


def _ical_date(d: date) -> str:
    # All-day event date value
    return d.strftime("%Y%m%d")


def _generate_ical(start: date, end: date) -> Iterable[str]:
    # Header
    yield "BEGIN:VCALENDAR\r\n"
    yield "VERSION:2.0\r\n"
    yield "PRODID:-//Budget Buddy//Calendar Export//EN\r\n"
    yield "CALSCALE:GREGORIAN\r\n"
    yield "METHOD:PUBLISH\r\n"

    # Load entries and filter to commitments + key events
    dbp = _default_db_path()
    entries = expand_calendar(start, end, db_path=dbp)
    now = datetime.utcnow()
    for e in entries:
        if e.type not in ("commitment", "key_event"):
            continue
        uid = f"{e.type}-{e.source_id}-{e.date.isoformat()}@budgetbuddy"
        summary_type = "Commitment" if e.type == "commitment" else "Key Event"
        # Build VEVENT
        yield "BEGIN:VEVENT\r\n"
        yield f"UID:{uid}\r\n"
        yield f"DTSTAMP:{_ical_dt(now)}\r\n"
        # All-day event: DTSTART/DTEND as VALUE=DATE (DTEND exclusive)
        yield f"DTSTART;VALUE=DATE:{_ical_date(e.date)}\r\n"
        yield f"DTEND;VALUE=DATE:{_ical_date(e.date + timedelta(days=1))}\r\n"
        # Summary and description
        summary = f"{summary_type}: {e.name}"
        yield f"SUMMARY:{summary}\r\n"
        amount = _money(e.amount_cents)
        # Escape commas and semicolons minimally per iCal text rules
        desc = (
            f"Type: {e.type}\\n"
            f"Amount: {amount}\\n"
            f"Shift policy: {e.policy or 'AS_SCHEDULED'}\\n"
            f"Shift applied: {str(bool(e.shift_applied)).lower()}"
        )
        yield f"DESCRIPTION:{desc}\r\n"
        cat = "Commitment" if e.type == "commitment" else "Key Event"
        yield f"CATEGORIES:{cat}\r\n"
        yield "END:VEVENT\r\n"

    # Footer
    yield "END:VCALENDAR\r\n"


@router.get("/api/calendar/ical")
def get_calendar_ical(
    from_: str = Query(..., alias="from", description="Start date YYYY-MM-DD"),
    to: str = Query(..., alias="to", description="End date YYYY-MM-DD"),
):
    try:
        start = date.fromisoformat(from_)
        end = date.fromisoformat(to)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid date format; use YYYY-MM-DD")
    if end < start:
        raise HTTPException(status_code=400, detail="to must be on or after from")

    filename = f"budget_calendar_{start.isoformat()}_{end.isoformat()}.ics"
    stream = _generate_ical(start, end)
    return StreamingResponse(
        stream,
        media_type="text/calendar; charset=utf-8",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )

