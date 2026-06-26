#!/bin/bash
set -e

PUID=${PUID:-1000}
PGID=${PGID:-1000}

# Ensure compose, data, and media directories exist with correct ownership
mkdir -p /compose /data
mkdir -p /media/movies /media/4k_movies /media/shows /media/4k_shows \
         /media/anime /media/music \
         /media/downloads/complete /media/downloads/incomplete \
         /media/cache /media/remotes
chown -R ${PUID}:${PGID} /compose /data /media

# Create group if it doesn't exist
if ! getent group appgroup > /dev/null 2>&1; then
    groupadd -g ${PGID} appgroup
fi

# Create user if it doesn't exist
if ! getent passwd appuser > /dev/null 2>&1; then
    useradd -u ${PUID} -g ${PGID} -s /bin/bash -M appuser
fi

# Add appuser to the docker socket's group so it can call the Docker API
DOCKER_SOCK=/var/run/docker.sock
if [ -S "$DOCKER_SOCK" ]; then
    DOCKER_GID=$(stat -c '%g' "$DOCKER_SOCK")
    if ! getent group dockersock > /dev/null 2>&1; then
        groupadd -g "$DOCKER_GID" dockersock
    fi
    usermod -aG dockersock appuser
fi

# Ensure /app is owned correctly
chown -R ${PUID}:${PGID} /app

exec gosu appuser gunicorn main:app \
    --worker-class uvicorn.workers.UvicornWorker \
    --workers 2 \
    --bind 0.0.0.0:8000 \
    --reload
