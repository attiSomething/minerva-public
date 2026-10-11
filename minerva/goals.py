"""Word goals: a daily and a weekly target for words added across the
library, and an optional target length per project.

Words added are net: the library's word count now minus its size when the
day (or week) began, so cutting words counts against the goal. That size
comes from library_days.start_words, recorded by each day's first sync.
"""

import datetime

from . import core

FIELDS = ("daily_words", "weekly_words")
MAX_GOAL = 1_000_000


class GoalError(Exception):
    user_facing = True


def get():
    saved = core.read_library_settings(core.ARCHIVE_ROOT).get("goals") or {}
    return {k: int(saved.get(k) or 0) for k in FIELDS}


def set_goals(body):
    goals = get()
    for k in FIELDS:
        if k in body:
            v = body[k]
            try:
                v = int(v or 0)
            except (TypeError, ValueError):
                raise GoalError("A goal should be a number of words.") from None
            if not 0 <= v <= MAX_GOAL:
                raise GoalError("Pick a goal between 0 and 1,000,000 words.")
            goals[k] = v
    settings = core.read_library_settings(core.ARCHIVE_ROOT)
    settings["goals"] = goals
    core.write_library_settings(core.ARCHIVE_ROOT, settings)
    return goals


def _baseline(conn, day, now_words):
    """The library's word count when `day` began."""
    r = conn.execute("SELECT day, words, start_words FROM library_days WHERE day >= ? ORDER BY day LIMIT 1",
                     (day.isoformat(),)).fetchone()
    if r and r["start_words"] is not None:
        return r["start_words"]
    r = conn.execute("SELECT words FROM library_days WHERE day < ? ORDER BY day DESC LIMIT 1",
                     (day.isoformat(),)).fetchone()
    return r["words"] if r else now_words


def progress(conn, today=None):
    today = today or datetime.date.today()
    week_start = today - datetime.timedelta(days=today.weekday())
    words = conn.execute("SELECT COALESCE(SUM(word_count), 0) w FROM entries").fetchone()["w"]
    goals = get()
    projects = []
    for p in conn.execute("SELECT * FROM projects WHERE target_words > 0 ORDER BY name COLLATE NOCASE"):
        total = conn.execute("SELECT COALESCE(SUM(word_count), 0) w FROM entries WHERE project_tag = ?",
                             (p["tag"],)).fetchone()["w"]
        projects.append({"id": p["id"], "name": p["name"], "tag": p["tag"],
                         "target": p["target_words"], "words": total})
    return {
        "daily": {"goal": goals["daily_words"], "words": words - _baseline(conn, today, words)},
        "weekly": {"goal": goals["weekly_words"], "words": words - _baseline(conn, week_start, words)},
        "projects": projects,
    }
