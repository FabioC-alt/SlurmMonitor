# SlurmMonitor

A live job dashboard for your own jobs on **disi-cluster**. One FastAPI
backend polls `squeue -u $USER` over SSH and serves a small static
dashboard, styled after FrostLine's webui (dark theme, colored status
stripes).

## How it works

- The container SSHes out to the `disi` host alias (from your `~/.ssh/config`,
  which is bind-mounted read-only) and runs `squeue -h -a -u $USER -o '...'`
  every `REFRESH_INTERVAL_SECONDS` (default 20s) &mdash; `$USER` expands on the
  remote side to whichever account the SSH alias logs in as, so it's scoped
  to that account's jobs only, not the whole cluster's &mdash; caching the
  parsed result in memory.
- The frontend polls `/api/jobs` every 10s and re-renders: search box,
  state filter (Running / Pending / Other), partition dropdown, and a
  "Refresh now" button that forces an immediate SSH poll.
- No historical data (no `sacct`) — this shows the current queue snapshot,
  matching "jobs running on the cluster" rather than job history.

## Run it

```bash
docker compose up -d --build
```

Then open **http://localhost:8091** (or whatever `HOST_PORT` you set — see `.env`).

Config lives in `.env` (copy `.env.example` to `.env` first — see "Set up on a
new machine" below):

| Variable | Meaning |
|---|---|
| `SSH_DIR` | Your own SSH directory (config, key, known_hosts), mounted read-only |
| `HOST_PORT` | Port exposed on the host |
| `SLURM_SSH_HOST` | SSH alias/host to run `squeue` on |
| `REFRESH_INTERVAL_SECONDS` | How often the backend re-polls SSH |

## Set up on a new machine (e.g. handing this to a colleague)

This project is safe to hand off as-is: `.env` is gitignored and nothing in
the repo contains a key, password, or your username. Each person's copy
reads their own cluster jobs, because `squeue -u $USER` expands `$USER` on
the remote side to whoever's SSH identity connected — not a hardcoded name.

1. Get the code (clone the repo, or unzip the archive you were sent).
2. **Never send or copy someone else's private SSH key.** You need your own
   working, passwordless (or agent-backed) SSH access to the cluster first
   — test it from a normal terminal: `ssh <your-alias-or-host> squeue -u $USER`.
   If that prompts for a password, this app can't authenticate non-interactively
   either; fix that first (e.g. install a key with `ssh-copy-id` and no
   passphrase, or use `ssh-agent`).
3. `cp .env.example .env`, then edit `.env`:
   - `SSH_DIR` → the absolute path to *your* `~/.ssh` directory.
   - `SLURM_SSH_HOST` → the host/alias from step 2.
4. `docker compose up -d --build`, then open `http://localhost:8091`
   (or your `HOST_PORT`).

## Why the SSH dir is copied, not mounted straight into `/root/.ssh`

A Windows bind mount can't carry Unix file permissions, and `ssh` refuses
keys/config that look world-readable. `entrypoint.sh` copies the mounted
`/ssh-host` into `/root/.ssh` on container start and `chmod`s everything
correctly, and starts fresh `cm/` (ControlMaster socket dir) each time so a
stale multiplexed connection from a host-side session can never break it.
Each poll also explicitly disables SSH multiplexing (`ControlMaster=no`) so
one bad connection can't wedge every subsequent poll.

## Viewing it as slurmMonitor.local

See the setup instructions in chat for the one-time hosts-file command.
