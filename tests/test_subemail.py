import io
from email.message import EmailMessage

import pytest

from minerva import core, subemail, subimport, submissions

TITLES = ["Morning Tide", "The Lighthouse", "Field Notes", "Water"]


def mail(sender, subject, body, date, html=False):
    m = EmailMessage()
    m["From"] = sender
    m["To"] = "writer@example.com"
    m["Subject"] = subject
    m["Date"] = date
    if html:
        m.set_content("<html><body><p>" + body.replace("\n", "</p><p>") + "</p></body></html>", subtype="html")
    else:
        m.set_content(body)
    return m.as_bytes()


RECEIVED = mail("Harbor Review via Submittable <notifications@submittable.com>", "Submission Received",
                "Thank you for your submission to Harbor Review.\nTitle: Morning Tide\nWe read every piece.",
                "Thu, 14 Mar 2024 10:00:00 -0400")
DECLINED = mail("Harbor Review via Submittable <notifications@submittable.com>", "Your submission: Morning Tide",
                "Dear Writer,\nThank you for sending Morning Tide. Unfortunately it isn't right for us.",
                "Thu, 02 May 2024 09:00:00 -0400", html=True)
ACCEPTED = mail("Submittable <no-reply@submittable.com>", "Salt Quarterly - The Lighthouse",
                "We are delighted to accept The Lighthouse for our spring issue! Thanks for submitting to Salt Quarterly.",
                "Mon, 06 May 2024 09:00:00 -0400")
NEWSLETTER = mail("Submittable <news@submittable.com>", "New opportunities this week",
                  "Here are some calls for work you might like.", "Mon, 06 May 2024 09:00:00 -0400")
PERSONAL = mail("Aunt May <may@example.com>", "Congratulations!", "Unfortunately I can't come.", "Mon, 06 May 2024 09:00:00 -0400")


def mbox(*messages):
    out = b""
    for m in messages:
        out += b"From MAILER-DAEMON Thu Jan  1 00:00:00 2024\n" + m.replace(b"\nFrom ", b"\n>From ") + b"\n"
    return out


def test_emails_become_rows():
    r = subemail.read([("Submissions.mbox", mbox(RECEIVED, DECLINED, ACCEPTED, NEWSLETTER, PERSONAL))], TITLES)
    assert r["emails"] == 5 and r["used"] == 2 and r["skipped_count"] == 1
    rows = subimport.read_csv(r["text"])
    assert rows[0] == subemail.HEADINGS
    got = {row[0]: row[1:5] for row in rows[1:]}
    # received then declined: one record, sent on the first, declined on the second
    assert got["Morning Tide"] == ["Harbor Review", "2024-03-14", "Declined", "2024-05-02"]
    # the venue comes from the email when the sender is just "Submittable"
    assert got["The Lighthouse"] == ["Salt Quarterly", "", "Accepted", "2024-05-06"]


def test_signs_and_titles():
    assert subemail._status("", "We are unable to accept this piece at this time") == "Declined"
    assert subemail._status("", "your piece is on our shortlist") == "Shortlisted"
    assert subemail._status("Submission withdrawn", "Your submission has been withdrawn.") == "Withdrawn"
    assert subemail._status("Hello", "Our new issue is out") is None
    # the longest title wins over one inside it
    assert subemail._title("Re: Low Water", "", ["Low Water", "Water"]) == ("Low Water", True)
    assert subemail._title("Your submission", 'about "A New Poem" we', TITLES) == ("A New Poem", False)
    with pytest.raises(subemail.EmailImportError):
        list(subemail._messages("notes.txt", b"hello"))


def test_emails_update_records_through_the_import(library, client):
    core.configure(library)
    core.scan_and_sync()
    conn = core.get_conn()
    tide = conn.execute("SELECT id FROM entries WHERE title = 'Morning Tide'").fetchone()["id"]
    # entered by hand, with a date a day off
    submissions.create(conn, {"entry_id": tide, "venue": "Harbor Review", "submitted_on": "2024-03-13"})
    conn.close()
    data = {"files": [(io.BytesIO(RECEIVED), "a.eml"), (io.BytesIO(DECLINED), "b.eml")]}
    r = client.post("/api/submissions/import/emails", data=data, content_type="multipart/form-data").get_json()
    assert r["used"] == 1
    conn = core.get_conn()
    p = subimport.preview(conn, r["text"], source="")
    assert [row["state"] for row in p["rows"]] == ["update"]
    subimport.run(conn, r["text"], p["mapping"])
    s = submissions.search(conn, {})[0]
    assert (s["status"], s["decided_on"], s["submitted_on"]) == ("Declined", "2024-05-02", "2024-03-13")
    assert len(submissions.search(conn, {})) == 1
