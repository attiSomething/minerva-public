"""What's coming up, for the panel on Home: deadlines for planned
submissions, venues whose reading period opens or closes soon, pieces with
a final draft that aren't out anywhere, and submissions past the date a
reply was expected."""

import calendar
import datetime
import re

from . import sharing, submissions

WINDOW_DAYS = 30
READY_LIMIT = 8

MONTHS = {name.lower(): i for i, name in enumerate(calendar.month_name) if name}
MONTHS.update({name.lower(): i for i, name in enumerate(calendar.month_abbr) if name})
MONTHS["sept"] = 9

_MONTH = r"(jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|june?|july?|aug(?:ust)?|sept?(?:ember)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)\.?"
_DAY = r"(?:\s+(\d{1,2})(?:st|nd|rd|th)?)?"
_RANGE_RE = re.compile(_MONTH + _DAY + r"\s*(?:to|through|thru|until|till|-|–|—)\s*" + _MONTH + _DAY, re.IGNORECASE)
_SINGLE_RE = re.compile(r"^(?:in\s+|during\s+)?" + _MONTH + r"(?:\s+only)?$", re.IGNORECASE)
_ALWAYS_RE = re.compile(r"\b(all year|year[- ]round|rolling|always open|open all year|any ?time)\b", re.IGNORECASE)


def _month(name):
    key = name.lower().rstrip(".")
    return MONTHS.get(key) or MONTHS[key[:3]]


def parse_periods(text):
    """Reading periods written the way venues write them ("September to
    November, February 1 - April 30", "March", "year-round") as a list of
    ((month, day), (month, day)) ranges, or "always". Parts Minerva can't
    read are skipped."""
    text = (text or "").strip()
    if not text:
        return []
    if _ALWAYS_RE.search(text):
        return "always"
    out = []
    for part in re.split(r"[,;/]|\band\b|\n", text):
        part = part.strip()
        if not part:
            continue
        m = _RANGE_RE.search(part)
        if m:
            m1, d1, m2, d2 = _month(m.group(1)), m.group(2), _month(m.group(3)), m.group(4)
            out.append(((m1, int(d1) if d1 else 1), (m2, int(d2) if d2 else 0)))
            continue
        m = _SINGLE_RE.match(part)
        if m:
            mo = _month(m.group(1))
            out.append(((mo, 1), (mo, 0)))
    return out


def _day(year, month, day):
    """day 0 is the month's last day; days past the end are clamped."""
    last = calendar.monthrange(year, month)[1]
    return datetime.date(year, month, last if day == 0 else min(day, last))


def period_events(text, today, days=WINDOW_DAYS):
    """Opens and closes of a venue's reading periods within the window:
    a list of {"event": "opens"|"closes", "on": date}, soonest first."""
    periods = parse_periods(text)
    if periods == "always":
        return []
    end = today + datetime.timedelta(days=days)
    seen = {}
    for (m1, d1), (m2, d2) in periods:
        for year in (today.year - 1, today.year, today.year + 1):
            start = _day(year, m1, d1)
            stop = _day(year + (1 if (m2, d2 or 99) < (m1, d1) else 0), m2, d2)
            if today < start <= end:
                seen[("opens", start)] = True
            if start <= today <= stop <= end:
                seen[("closes", stop)] = True
    return [{"event": e, "on": d} for e, d in sorted(seen, key=lambda k: k[1])]


def is_open(text, today):
    periods = parse_periods(text)
    if periods == "always":
        return True
    for (m1, d1), (m2, d2) in periods:
        for year in (today.year - 1, today.year):
            start = _day(year, m1, d1)
            stop = _day(year + (1 if (m2, d2 or 99) < (m1, d1) else 0), m2, d2)
            if start <= today <= stop:
                return True
    return False


def coming_up(conn, today=None):
    today = today or datetime.date.today()
    end = today + datetime.timedelta(days=WINDOW_DAYS)
    iso_today = today.isoformat()
    rows = submissions.search(conn, {"open": "1"})

    deadlines = sorted(
        ({"sub": r, "on": r["deadline"], "days": (datetime.date.fromisoformat(r["deadline"]) - today).days}
         for r in rows if r["status"] == "Planned" and r["deadline"] and iso_today <= r["deadline"] <= end.isoformat()),
        key=lambda d: d["on"])

    overdue = sorted(
        ({"sub": r, "days": (today - datetime.date.fromisoformat(r["expected_by"])).days}
         for r in rows if r["overdue"]),
        key=lambda d: -d["days"])

    reading = []
    for v in conn.execute("SELECT name, reading_periods FROM venues WHERE COALESCE(reading_periods, '') != ''"):
        for ev in period_events(v["reading_periods"], today):
            reading.append({"venue": v["name"], "event": ev["event"], "on": ev["on"].isoformat(),
                            "days": (ev["on"] - today).days, "periods": v["reading_periods"]})
    reading.sort(key=lambda r: (r["on"], r["venue"].lower()))

    out_now = {r["entry_id"] for r in rows if r["entry_id"]}
    out_now |= {r["entry_id"] for r in conn.execute(
        "SELECT entry_id FROM submissions WHERE status = 'Accepted' AND entry_id IS NOT NULL")}
    ready = []
    for r in conn.execute("SELECT * FROM entries WHERE COALESCE(published, 0) = 0 ORDER BY draft_modified DESC"):
        if r["id"] in out_now or not sharing.has_final(r):
            continue
        ready.append({"id": r["id"], "title": r["title"], "category": r["top_folder"]})

    return {"window_days": WINDOW_DAYS, "deadlines": deadlines, "reading": reading, "overdue": overdue,
            "ready": ready[:READY_LIMIT], "ready_total": len(ready)}
