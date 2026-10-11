"""Long-running work (transcribing a scan) runs in a background thread so
the page stays responsive. The page polls a job for progress and can ask it
to stop between pages."""

import threading
import traceback
import uuid

_jobs = {}
_lock = threading.Lock()


class Job:
    def __init__(self, kind, label):
        self.id = uuid.uuid4().hex[:12]
        self.kind = kind
        self.label = label
        self.status = "running"
        self.done = 0
        self.total = 0
        self.message = ""
        self.error = None
        self.result = None
        self._cancel = threading.Event()

    def progress(self, done, total, message=""):
        self.done, self.total, self.message = done, total, message

    def cancelled(self):
        return self._cancel.is_set()

    def to_dict(self):
        return {"id": self.id, "kind": self.kind, "label": self.label, "status": self.status,
                "done": self.done, "total": self.total, "message": self.message,
                "error": self.error, "result": self.result}


def start(kind, label, fn):
    """Run fn(job) in a thread. Only one job of a kind runs at a time."""
    with _lock:
        for j in _jobs.values():
            if j.kind == kind and j.status == "running":
                raise RuntimeError(f"Already working on {j.label}. Wait for it or stop it first.")
        job = Job(kind, label)
        _jobs[job.id] = job

    def run():
        try:
            job.result = fn(job)
            job.status = "stopped" if job.cancelled() else "done"
        except Exception as e:  # reported to the page, never raised
            job.status = "stopped" if job.cancelled() else "failed"
            job.error = str(e) or e.__class__.__name__
            if job.status == "failed" and not getattr(e, "user_facing", False):
                traceback.print_exc()

    threading.Thread(target=run, daemon=True).start()
    return job


def get(job_id):
    return _jobs.get(job_id)


def active(kind=None):
    return [j.to_dict() for j in _jobs.values()
            if j.status == "running" and (kind is None or j.kind == kind)]


def cancel(job_id):
    job = _jobs.get(job_id)
    if job:
        job._cancel.set()
    return job
