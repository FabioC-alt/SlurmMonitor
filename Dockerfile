FROM python:3.12-slim

RUN apt-get update \
 && apt-get install -y --no-install-recommends openssh-client \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app

RUN pip install --no-cache-dir fastapi "uvicorn[standard]"

COPY backend /app/backend
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

ENV SLURM_SSH_HOST=disi
ENV REFRESH_INTERVAL_SECONDS=20
ENV PYTHONPATH=/app

EXPOSE 8091

ENTRYPOINT ["/entrypoint.sh"]
