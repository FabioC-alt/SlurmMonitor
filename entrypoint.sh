#!/bin/sh
# The host's ~/.ssh is bind-mounted read-only at /ssh-host (see
# docker-compose.yml) instead of straight into /root/.ssh, because a
# Windows-hosted bind mount can't carry Unix file permissions and ssh
# refuses keys/config that look world-readable. Copy it in and fix
# permissions here instead.
set -e

if [ -d /ssh-host ]; then
  mkdir -p /root/.ssh
  cp -r /ssh-host/. /root/.ssh/ 2>/dev/null || true
  rm -rf /root/.ssh/cm
  mkdir -p /root/.ssh/cm
  chmod 700 /root/.ssh /root/.ssh/cm
  find /root/.ssh -maxdepth 1 -type f -exec chmod 600 {} \;
  [ -f /root/.ssh/id_ed25519.pub ] && chmod 644 /root/.ssh/id_ed25519.pub
  [ -f /root/.ssh/id_rsa.pub ] && chmod 644 /root/.ssh/id_rsa.pub
fi

exec uvicorn backend.main:app --host 0.0.0.0 --port 8091
