"""Submission updates read from emails: the confirmations and decisions
that Submittable and other submission managers send.

The writer exports the emails (an .mbox mailbox, or .eml files) and
chooses them in Import... on Submissions. Each email from a known
submission manager is read for the venue, the piece (by finding one of
the library's titles in it), what happened (received, declined, accepted,
shortlisted, withdrawn) and when. Emails about the same piece at the same
venue are combined, and the result is handed to the spreadsheet importer
as a CSV, so it gets the same preview: new records, status updates to
records already in Minerva, and rows that need a match. Nothing is saved
until the writer confirms there.

No mail account is signed in to; the files are only read.
"""

import csv
import email
import email.policy
import email.utils
import io
import mailbox
import os
import re
import tempfile

from . import fileimport

MAX_EMAILS = 20000
HEADINGS = ["Title", "Venue", "Date Submitted", "Status", "Response Date", "Notes"]

# sender domains of submission managers
SERVICES = {
    "submittable.com": "Submittable",
    "moksha.io": "Moksha",
    "duosuma.com": "Duosuma",
    "chillsubs.com": "Chill Subs",
}

# Phrases, checked in this order: a decline often thanks the writer for
# submitting, and "unable to accept" mentions accepting.
SIGNS = [
    ("Withdrawn", ("has been withdrawn", "you have withdrawn", "withdrawal of your submission",
                   "withdrawn your submission")),
    ("Declined", ("not a fit", "not the right fit", "not quite right for", "unable to accept", "not able to accept",
                  "cannot accept", "can't accept", "won't be able to", "will not be able to", "decided to pass",
                  "we'll pass", "we will pass", "pass on this", "regret to inform", "we regret that",
                  "unfortunately", "not selected", "decline", "not to move forward", "not moving forward",
                  "not be moving forward", "not for us", "doesn't fit our", "does not fit our")),
    ("Shortlisted", ("shortlist", "short list", "short-list", "finalist", "further consideration",
                     "holding your", "hold your", "second round", "next round")),
    ("Accepted", ("pleased to accept", "happy to accept", "delighted to accept", "thrilled to accept",
                  "would like to publish", "we'd like to publish", "love to publish", "accepted for publication",
                  "has been accepted", "we accept", "congratulations")),
    ("Submitted", ("received your submission", "thank you for your submission", "thanks for your submission",
                   "submission has been received", "successfully submitted", "submission confirmation",
                   "we have received", "submission received", "thank you for submitting", "thanks for submitting")),
]
ORDER = {"Submitted": 0, "Shortlisted": 1, "Accepted": 2, "Declined": 2, "Withdrawn": 2}

_VIA_RE = re.compile(r"\s+(?:via|through|on)\s+(?:Submittable|Moksha|Duosuma|Chill Subs)\s*$", re.IGNORECASE)
_VENUE_RES = [
    re.compile(r"(?:submission|submitting|submitted)\b[^\n.!?]{0,80}?\bto\s+(?:the\s+)?([A-Z][^\n.!?,:;]{2,60}?)(?=\s+(?:has|have|was|is|on|for|and)\b|[\n.!?,:;])"),
    re.compile(r"interest in\s+(?:the\s+)?([A-Z][^\n.!?,:;]{2,60}?)(?=[\n.!?,:;])"),
]
_QUOTED_RE = re.compile(r"[\"“]([^\"”\n]{2,120})[\"”]")


class EmailImportError(ValueError):
    user_facing = True


def _service(msg):
    sender = str(msg.get("From") or "")
    _name, addr = email.utils.parseaddr(sender)
    domain = addr.rsplit("@", 1)[-1].lower()
    for d, label in SERVICES.items():
        if domain == d or domain.endswith("." + d):
            return label
    return None


def _text(msg):
    try:
        part = msg.get_body(preferencelist=("plain", "html"))
    except Exception:
        part = None
    if part is None:
        return ""
    try:
        body = part.get_content()
    except Exception:
        return ""
    if part.get_content_type() == "text/html":
        body, _title, _notes = fileimport._html(body.encode("utf-8"))
    return " ".join(body.split()) if body else ""


def _venue(msg, body, service):
    name, _addr = email.utils.parseaddr(str(msg.get("From") or ""))
    name = _VIA_RE.sub("", name or "").strip(' "')
    if name and name.lower() not in {s.lower() for s in SERVICES.values()} and "noreply" not in name.lower().replace("-", ""):
        return name
    subject = str(msg.get("Subject") or "")
    for rx in _VENUE_RES:
        m = rx.search(subject) or rx.search(body)
        if m:
            return m.group(1).strip()
    return ""


def _status(subject, body):
    text = f"{subject} {body}".lower()
    for status, phrases in SIGNS:
        if any(p in text for p in phrases):
            return status
    return None


def _title(subject, body, titles):
    """The library title this email is about: one found in the subject,
    else the only one found in the body, else a quoted title."""
    for where in (subject, body):
        hits = {t for t in titles if len(t) >= 3 and re.search(rf"(?<!\w){re.escape(t)}(?!\w)", where, re.IGNORECASE)}
        # "Low Water" also contains "Water": keep the longest
        hits = {t for t in hits if not any(t != o and t.lower() in o.lower() for o in hits)}
        if len(hits) == 1:
            return hits.pop(), True
        if len(hits) > 1:
            break
    m = _QUOTED_RE.search(subject) or _QUOTED_RE.search(body)
    return (m.group(1).strip(), False) if m else ("", False)


MAX_BYTES = 500 * 1024 * 1024


def _messages(name, data):
    low = name.lower()
    if len(data) > MAX_BYTES:
        raise EmailImportError("That mailbox is too large. Export just your submission emails (a label or folder of them).")
    if low.endswith(".eml"):
        yield email.message_from_bytes(data, policy=email.policy.default)
        return
    if not low.endswith(".mbox") and not data.startswith(b"From "):
        raise EmailImportError(f'"{name}" isn\'t an .mbox or .eml file.')
    fd, path = tempfile.mkstemp(suffix=".mbox")
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
        box = mailbox.mbox(path, create=False)
        try:
            for key in box.iterkeys():
                yield email.message_from_bytes(box.get_bytes(key), policy=email.policy.default)
        finally:
            box.close()
    finally:
        os.unlink(path)


def read(files, titles):
    """files: (name, bytes) pairs. titles: the library's entry and project
    titles. Returns {"text": CSV for subimport, "emails", "used",
    "skipped": [{"subject", "reason"}]}."""
    found, skipped, total = {}, [], 0
    for name, data in files:
        for msg in _messages(name, data):
            total += 1
            if total > MAX_EMAILS:
                raise EmailImportError(f"That's more than {MAX_EMAILS:,} emails. Export just your submission emails.")
            subject = " ".join(str(msg.get("Subject") or "").split())
            service = _service(msg)
            if not service:
                continue  # not from a submission manager: not mentioned, there may be thousands
            body = _text(msg)
            status = _status(subject, body)
            if not status:
                skipped.append({"subject": subject, "reason": "Doesn't say a piece was received or decided."})
                continue
            venue = _venue(msg, body, service)
            title, _known = _title(subject, body, titles)
            try:
                when = email.utils.parsedate_to_datetime(str(msg.get("Date"))).date().isoformat()
            except (TypeError, ValueError):
                when = ""
            # an email whose piece can't be told is kept on its own
            key = (venue.casefold(), title.casefold() or f"?{total}")
            rec = found.setdefault(key, {"title": title, "venue": venue, "submitted": "", "status": "",
                                         "decided": "", "decided_at": "", "notes": [], "service": service})
            if status == "Submitted":
                if when and (not rec["submitted"] or when < rec["submitted"]):
                    rec["submitted"] = when
            elif not rec["status"] or (when or "") >= rec["decided_at"]:
                rec.update(status=status, decided_at=when or "")
                if status != "Shortlisted":
                    rec["decided"] = when
            rec["notes"].append(f"{service} email {when}: {subject}".strip())
    out = io.StringIO()
    w = csv.writer(out)
    w.writerow(HEADINGS)
    for rec in sorted(found.values(), key=lambda r: (r["submitted"] or r["decided_at"], r["title"].lower())):
        w.writerow([rec["title"], rec["venue"], rec["submitted"], rec["status"] or "Submitted", rec["decided"],
                    "\n".join(rec["notes"][-3:])])
    return {"text": out.getvalue(), "emails": total, "used": len(found), "skipped": skipped[:50],
            "skipped_count": len(skipped)}
