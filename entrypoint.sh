#!/bin/bash
set -e

PUID=${PUID:-1000}
PGID=${PGID:-1000}

# Ensure compose directory exists and is owned correctly
mkdir -p /compose
chown -R ${PUID}:${PGID} /compose

# Create group if it doesn't exist
if ! getent group appgroup > /dev/null 2>&1; then
    groupadd -g ${PGID} appgroup
fi

# Create user if it doesn't exist
if ! getent passwd appuser > /dev/null 2>&1; then
    useradd -u ${PUID} -g ${PGID} -s /bin/bash -M appuser
fi

# Ensure /app is owned correctly
chown -R ${PUID}:${PGID} /app

exec gosu appuser gunicorn main:app \
    --worker-class uvicorn.workers.UvicornWorker \
    --workers 2 \
    --bind 0.0.0.0:8000 \
    --reload
