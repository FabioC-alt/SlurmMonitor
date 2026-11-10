"""SlurmMonitor backend: a FastAPI app that polls disi-cluster over SSH for
the live `squeue` snapshot (every user, every partition) and serves it as
JSON plus a small static dashboard. Styled after FrostLine's webui, but
cluster-wide instead of scoped to one project's jobs.
"""
from __future__ import annotations

import json
import os
import subprocess
import threading
import time
import urllib.request
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

SSH_HOST = os.environ.get("SLURM_SSH_HOST", "disi")
SSH_CONNECT_TIMEOUT = int(os.environ.get("SLURM_SSH_TIMEOUT", "15"))
REFRESH_INTERVAL = int(os.environ.get("REFRESH_INTERVAL_SECONDS", "20"))
STATIC_DIR = Path(__file__).parent / "static"

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")

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
    "telegram_configured": bool(TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID),
}

# job_id → job_name: jobs the user wants Telegram notifications for.
_watched: dict[str, str] = {}
# job_id → last known state: used to detect changes between polls.
_prev_job_states: dict[str, str] = {}


class WatchRequest(BaseModel):
    name: str = ""
    watch: bool = True


def send_telegram(text: str) -> None:
    """Send a message via the Telegram Bot API. Logs errors but never raises."""
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = json.dumps({
        "chat_id": TELEGRAM_CHAT_ID,
        "text": text,
        "parse_mode": "HTML",
    }).encode()
    try:
        req = urllib.request.Request(
            url, data=payload,
            headers={"Content-Type": "application/json"},
        )
        urllib.request.urlopen(req, timeout=10)
    except Exception as exc:
        print(f"Telegram send failed: {exc}", flush=True)


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


def _apply_and_notify(outcome: dict[str, Any]) -> dict[str, Any]:
    """Update shared state; detect state changes for watched jobs and
    queue Telegram notifications (sent outside the lock to avoid blocking)."""
    global _prev_job_states
    notifications: list[str] = []

    with _lock:
        if not outcome["error"]:
            new_map: dict[str, dict] = {j["job_id"]: j for j in outcome["jobs"]}

            for job_id, job_name in list(_watched.items()):
                prev = _prev_job_states.get(job_id)
                if job_id not in new_map:
                    # Job disappeared from squeue → finished (success or failure unknown here)
                    if prev is not None:
                        notifications.append(
                            f"🏁 <b>{job_name}</b> (#{job_id}) has left the queue.\n"
                            f"Previous state: {prev}"
                        )
                else:
                    curr = new_map[job_id]["state"]
                    if prev is not None and curr != prev:
                        notifications.append(
                            f"🔄 <b>{job_name}</b> (#{job_id}) changed state:\n"
                            f"{prev} → {curr}"
                        )

            # Always advance the state snapshot, even for unwatched jobs,
            # so we have the right baseline for the next poll.
            _prev_job_states = {j["job_id"]: j["state"] for j in outcome["jobs"]}

        _state["jobs"] = outcome["jobs"]
        _state["error"] = outcome["error"]
        _state["generated_at"] = datetime.now(timezone.utc).isoformat()
        snapshot = dict(_state)

    # Send outside the lock — network I/O must not block API requests.
    for msg in notifications:
        send_telegram(msg)

    return snapshot


def poll_loop() -> None:
    while True:
        _apply_and_notify(fetch_jobs())
        time.sleep(REFRESH_INTERVAL)


threading.Thread(target=poll_loop, daemon=True).start()


@app.get("/api/jobs")
def get_jobs() -> dict:
    with _lock:
        return {**_state, "watched": dict(_watched)}


@app.post("/api/refresh")
def refresh_now() -> dict:
    result = _apply_and_notify(fetch_jobs())
    with _lock:
        return {**result, "watched": dict(_watched)}


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


@app.get("/api/watched")
def get_watched() -> dict:
    """Return the current set of watched job IDs."""
    with _lock:
        return {"watched": dict(_watched)}


@app.post("/api/watch/{job_id}")
def set_watch(job_id: str, req: WatchRequest) -> dict:
    """Add or remove a job from the Telegram watch list.
    Returns the full updated watched dict so the caller can sync its local state.
    """
    with _lock:
        if req.watch:
            _watched[job_id] = req.name or job_id
        else:
            _watched.pop(job_id, None)
        return {"watched": dict(_watched)}


@app.get("/")
def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
