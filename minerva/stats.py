"""The numbers on the Home page.

Everything here is read from Minerva's index: entry sizes from the last sync,
writing activity from the file dates the sync records (activity_days), and
the library's size per day (library_days, one row per day Minerva synced).
"""

import datetime

from . import goals
from . import sharing
from . import submissions

WORD_MILESTONES = (1_000, 5_000, 10_000, 25_000, 50_000, 100_000, 250_000, 500_000,
                   750_000, 1_000_000, 1_500_000, 2_000_000, 3_000_000, 5_000_000, 10_000_000)
WEEKS = 12


def _activity(conn):
    return {r["day"]: r for r in conn.execute("SELECT * FROM activity_days").fetchall()}


def _sum(activity, start, end, *cols):
    total = 0
    for day, r in activity.items():
        if start.isoformat() <= day <= end.isoformat():
            total += sum(r[c] for c in cols)
    return total


def _streaks(activity, today):
    """(current, longest): runs of consecutive days with a saved draft. The
    current streak still counts if the last save was yesterday."""
    days = sorted(datetime.date.fromisoformat(d) for d, r in activity.items()
                  if r["drafts"] + r["revisions"] > 0)
    longest = run = 0
    prev = None
    for d in days:
        run = run + 1 if prev and (d - prev).days == 1 else 1
        longest = max(longest, run)
        prev = d
    current = 0
    if days and (today - days[-1]).days <= 1:
        current = run
    return current, longest


def _words_before(conn, day):
    r = conn.execute("SELECT words FROM library_days WHERE day < ? ORDER BY day DESC LIMIT 1",
                     (day.isoformat(),)).fetchone()
    return r["words"] if r else None


def build(conn, today=None):
    today = today or datetime.date.today()
    week_start = today - datetime.timedelta(days=today.weekday())
    last_week_start = week_start - datetime.timedelta(days=7)
    month_start = today.replace(day=1)
    last_month_end = month_start - datetime.timedelta(days=1)
    last_month_start = last_month_end.replace(day=1)

    rows = conn.execute("SELECT * FROM entries").fetchall()
    activity = _activity(conn)
    words = sum(r["word_count"] or 0 for r in rows)

    by_cat = {}
    for r in rows:
        c = by_cat.setdefault(r["top_folder"], {"name": r["top_folder"], "entries": 0, "words": 0})
        c["entries"] += 1
        c["words"] += r["word_count"] or 0

    weeks = []
    for i in range(WEEKS - 1, -1, -1):
        start = week_start - datetime.timedelta(days=7 * i)
        end = start + datetime.timedelta(days=6)
        weeks.append({"start": start.isoformat(),
                      "saves": _sum(activity, start, end, "drafts", "revisions"),
                      "started": _sum(activity, start, end, "started")})

    current, longest = _streaks(activity, today)
    month_base = _words_before(conn, month_start)
    next_milestone = next((m for m in WORD_MILESTONES if m > words), None)

    recent = sorted((r for r in rows if r["draft_modified"]),
                    key=lambda r: (r["draft_modified"], r["id"]), reverse=True)[:6]

    history = conn.execute(
        "SELECT day, words, entries FROM library_days WHERE day >= ? ORDER BY day",
        ((today - datetime.timedelta(days=180)).isoformat(),)).fetchall()

    subs = submissions.summary(submissions.search(conn, {"open": "1"}))

    return {
        "today": today.isoformat(),
        "goals": goals.progress(conn, today),
        "submissions": {"waiting": subs["waiting"], "overdue": subs["overdue"]},
        "totals": {
            "entries": len(rows),
            "words": words,
            "projects": conn.execute("SELECT COUNT(*) c FROM projects").fetchone()["c"],
            "finals": sum(1 for r in rows if sharing.has_final(r)),
            "published": sum(1 for r in rows if r["published"]),
            "to_edit": sum(1 for r in rows if r["to_edit"]),
            "to_record": sum(1 for r in rows if r["to_record"]),
        },
        "week": {"saves": _sum(activity, week_start, today, "drafts", "revisions"),
                 "last": _sum(activity, last_week_start, week_start - datetime.timedelta(days=1),
                              "drafts", "revisions")},
        "month": {"saves": _sum(activity, month_start, today, "drafts", "revisions"),
                  "last": _sum(activity, last_month_start, last_month_end, "drafts", "revisions"),
                  "started": _sum(activity, month_start, today, "started"),
                  "started_last": _sum(activity, last_month_start, last_month_end, "started"),
                  "words_added": None if month_base is None else words - month_base},
        "streak": {"current": current, "longest": longest},
        "milestone": None if next_milestone is None else {"words": next_milestone,
                                                          "to_go": next_milestone - words},
        "weeks": weeks,
        "categories": sorted(by_cat.values(), key=lambda c: -c["words"]),
        "recent": [{"id": r["id"], "title": r["title"], "category": r["top_folder"],
                    "day": r["draft_modified"], "words": r["word_count"] or 0} for r in recent],
        "history": [dict(h) for h in history],
    }
