"""SlurmMonitor backend: a FastAPI app that polls disi-cluster over SSH for
the live `squeue` snapshot (every user, every partition) and serves it as
JSON plus a small static dashboard. Styled after FrostLine's webui, but
cluster-wide instead of scoped to one project's jobs.
"""
from __future__ import annotations

import os
import subprocess
import threading
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

SSH_HOST = os.environ.get("SLURM_SSH_HOST", "disi")
SSH_CONNECT_TIMEOUT = int(os.environ.get("SLURM_SSH_TIMEOUT", "15"))
REFRESH_INTERVAL = int(os.environ.get("REFRESH_INTERVAL_SECONDS", "20"))
STATIC_DIR = Path(__file__).parent / "static"

# %i job id, %j name, %u user, %T state, %M time used, %l time limit,
# %D nodes, %P partition, %R reason/nodelist, %C cpus
SQUEUE_FORMAT = "%i|%j|%u|%T|%M|%l|%D|%P|%R|%C"
# -u $USER scopes this to the SSH login's own jobs only ($USER is expanded
# remotely, by the remote shell, not locally).
SQUEUE_CMD = f"squeue -h -a -u $USER -o '{SQUEUE_FORMAT}'"

# Multiplexing (ControlMaster) is configured in the mounted ~/.ssh/config for
# interactive use, but a stale control socket makes every poll fail at once
# for a long-running process -- disable it here so each poll is independent.
SSH_BASE_OPTS = [
    "-o", "BatchMode=yes",
    "-o", "ControlMaster=no",
    "-o", "ControlPath=none",
    "-o", f"ConnectTimeout={SSH_CONNECT_TIMEOUT}",
]

app = FastAPI(title="SlurmMonitor")

_lock = threading.Lock()
_state: dict[str, Any] = {
    "generated_at": None,
    "host": SSH_HOST,
    "jobs": [],
    "error": "not polled yet",
}


def fetch_jobs() -> dict[str, Any]:
    try:
        result = subprocess.run(
            ["ssh", *SSH_BASE_OPTS, SSH_HOST, SQUEUE_CMD],
            capture_output=True,
            text=True,
            timeout=SSH_CONNECT_TIMEOUT + 10,
        )
    except subprocess.TimeoutExpired:
        return {"jobs": [], "error": f"ssh to {SSH_HOST} timed out"}
    except OSError as exc:
        return {"jobs": [], "error": f"ssh failed to start: {exc}"}

    if result.returncode != 0:
        return {"jobs": [], "error": result.stderr.strip() or f"ssh exited {result.returncode}"}

    jobs: list[dict[str, str]] = []
    for line in result.stdout.splitlines():
        parts = line.split("|")
        if len(parts) < 10:
            continue
        job_id, name, user, state, time_used, time_limit, nodes, partition, reason, cpus = parts[:10]
        jobs.append({
            "job_id": job_id,
            "name": name,
            "user": user,
            "state": state,
            "time_used": time_used,
            "time_limit": time_limit,
            "nodes": nodes,
            "partition": partition,
            "reason": reason,
            "cpus": cpus,
        })
    return {"jobs": jobs, "error": None}


def _apply(outcome: dict[str, Any]) -> dict[str, Any]:
    with _lock:
        _state["jobs"] = outcome["jobs"]
        _state["error"] = outcome["error"]
        _state["generated_at"] = datetime.now(timezone.utc).isoformat()
        return dict(_state)


def poll_loop() -> None:
    while True:
        _apply(fetch_jobs())
        time.sleep(REFRESH_INTERVAL)


threading.Thread(target=poll_loop, daemon=True).start()


@app.get("/api/jobs")
def get_jobs() -> dict:
    with _lock:
        return dict(_state)


@app.post("/api/refresh")
def refresh_now() -> dict:
    return _apply(fetch_jobs())


@app.get("/api/stats")
def get_stats() -> dict:
    with _lock:
        jobs = list(_state["jobs"])
        generated_at = _state["generated_at"]
        error = _state["error"]

    states = Counter(j["state"] for j in jobs)
    partitions = Counter(j["partition"] for j in jobs)
    users = Counter(j["user"] for j in jobs)
    running = states.get("RUNNING", 0)
    pending = states.get("PENDING", 0)
    return {
        "generated_at": generated_at,
        "error": error,
        "total": len(jobs),
        "running": running,
        "pending": pending,
        "other": len(jobs) - running - pending,
        "active_users": len(users),
        "by_state": dict(states),
        "by_partition": dict(partitions),
        "top_users": users.most_common(8),
    }


@app.get("/")
def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
