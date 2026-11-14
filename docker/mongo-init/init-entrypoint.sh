#!/bin/sh

set -eu

uri="mongodb://${MONGO_HOST:-mongo}:27017/?directConnection=true"
maxAttempts="${MONGO_WAIT_ATTEMPTS:-60}"
attempt=1

echo "Esperando a que MongoDB acepte conexiones en ${uri}..."
while ! mongosh "$uri" --quiet --eval 'db.adminCommand({ ping: 1 }).ok' >/dev/null 2>&1; do
  if [ "$attempt" -ge "$maxAttempts" ]; then
    echo "MongoDB no respondió después de ${maxAttempts} intentos." >&2
    exit 1
  fi
  attempt=$((attempt + 1))
  sleep 2
done

echo "MongoDB disponible. Iniciando el replica set..."
exec mongosh "$uri" --quiet --file /scripts/init-replica-set.js
