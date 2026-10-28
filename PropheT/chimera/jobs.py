"""Background jobs for the console: a subprocess or a Python function, with a live log.

The console starts a job (collect evidence, run the analysts), gets an ID back at once,
and follows the log over server-sent events. Jobs live in memory for the server's lifetime.

One job at a time (Oct 23 review, finding 6): two pipeline runs would write out/ at once, and a
run starting while the agents' model is generating would evict it from the GPU mid-answer
(free_ollama). A second start while one job is running raises JobRunning, which the API turns
into 409 with the running job's ID.
"""

import json
import os
import subprocess
import threading
import time
import uuid
from dataclasses import dataclass, field


@dataclass
class Job:
    id: str
    kind: str
    status: str = "running"            # running, done, failed
    log: list = field(default_factory=list)
    result: dict | None = None
    returncode: int | None = None
    started: float = field(default_factory=time.time)
    finished: float | None = None

    def to_dict(self) -> dict:
        return {
            "id": self.id, "kind": self.kind, "status": self.status, "returncode": self.returncode,
            "started": self.started, "finished": self.finished, "lines": len(self.log),
            "result": self.result,
        }


class JobRunning(Exception):
    """Another job is still running; the API answers 409 with it."""

    def __init__(self, job: Job):
        super().__init__(f"a job is already running ({job.kind}, {job.id})")
        self.job = job


class JobRegistry:
    def __init__(self):
        self._jobs: dict[str, Job] = {}
        self._lock = threading.Lock()

    def get(self, job_id: str) -> Job | None:
        return self._jobs.get(job_id)

    def running(self) -> Job | None:
        return next((j for j in self._jobs.values() if j.status == "running"), None)

    def _new(self, kind: str) -> Job:
        job = Job(id=uuid.uuid4().hex[:12], kind=kind)
        with self._lock:                      # the check and the insert happen together, so two starts can't both win
            busy = self.running()
            if busy is not None:
                raise JobRunning(busy)
            self._jobs[job.id] = job
        return job

    def run_command(self, kind: str, cmd: list[str], cwd: str | None = None) -> Job:
        """Run a command line in the background and capture its output line by line."""
        job = self._new(kind)
        job.log.append("$ " + " ".join(cmd))

        def worker():
            env = {**os.environ, "PYTHONUNBUFFERED": "1", "PYTHONIOENCODING": "utf-8"}
            try:
                proc = subprocess.Popen(cmd, cwd=cwd, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                        text=True, encoding="utf-8", errors="replace", bufsize=1)
                for line in proc.stdout:
                    job.log.append(line.rstrip("\n"))
                proc.wait()
                job.returncode = proc.returncode
                job.status = "done" if proc.returncode == 0 else "failed"
            except Exception as exc:  # the console shows the error instead of hanging
                job.log.append(f"error: {exc}")
                job.status = "failed"
            job.finished = time.time()

        threading.Thread(target=worker, daemon=True).start()
        return job

    def run_function(self, kind: str, fn, *args) -> Job:
        """Run a Python function in the background. It gets the job as its first argument, for logging."""
        job = self._new(kind)

        def worker():
            try:
                job.result = fn(job, *args)
                job.status = "done"
                job.returncode = 0
            except Exception as exc:
                job.log.append(f"error: {exc}")
                job.status = "failed"
                job.returncode = 1
            job.finished = time.time()

        threading.Thread(target=worker, daemon=True).start()
        return job

    def events(self, job_id: str, poll: float = 0.25):
        """Server-sent events: every new log line, then one final status event."""
        job = self.get(job_id)
        if job is None:
            yield "event: error\ndata: " + json.dumps({"error": "no such job"}) + "\n\n"
            return
        sent = 0
        while True:
            while sent < len(job.log):
                yield "data: " + json.dumps({"line": job.log[sent]}) + "\n\n"
                sent += 1
            if job.status != "running":
                yield "event: status\ndata: " + json.dumps(job.to_dict()) + "\n\n"
                return
            time.sleep(poll)
