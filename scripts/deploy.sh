#!/bin/bash
set -e

# Zero-Downtime Blue-Green Deployment Script
# To be run on the VPS from the project root directory.

UPSTREAM_CONF="active-upstream.conf"

echo "=== Starting Blue-Green Deployment ==="

# 1. Determine currently active environment
if [ ! -f "$UPSTREAM_CONF" ]; then
    echo "No $UPSTREAM_CONF found. Initializing with blue..."
    cat <<EOF > "$UPSTREAM_CONF"
upstream backend_upstream {
    server backend-blue:8000;
}
upstream frontend_upstream {
    server frontend-blue:3000;
}
EOF
fi

if grep -q "backend-blue" "$UPSTREAM_CONF"; then
    ACTIVE="blue"
    INACTIVE="green"
    INACTIVE_COMPOSE="docker-compose.green.yml"
    ACTIVE_COMPOSE="docker-compose.blue.yml"
    BACKEND_PORT=8001
    FRONTEND_PORT=3001
else
    ACTIVE="green"
    INACTIVE="blue"
    INACTIVE_COMPOSE="docker-compose.blue.yml"
    ACTIVE_COMPOSE="docker-compose.green.yml"
    BACKEND_PORT=8000
    FRONTEND_PORT=3000
fi

echo "Currently active stack: $ACTIVE"
echo "Deploying to inactive stack: $INACTIVE (Backend port: $BACKEND_PORT, Frontend port: $FRONTEND_PORT)"

# 2. Ensure infrastructure stack (Postgres, Redis, Neo4j, Nginx) is running
echo "Ensuring infrastructure services are up..."
docker compose -f docker-compose.infra.yml up -d

# 3. Pull latest changes (handled by GitHub action or git command)
# Git pull is usually done before executing deploy.sh, but let's make sure dependencies are built.

# 4. Build and start the inactive stack
echo "Building and starting the $INACTIVE stack..."
docker compose -f "$INACTIVE_COMPOSE" build --pull
docker compose -f "$INACTIVE_COMPOSE" up -d --force-recreate

# 5. Poll health checks
echo "Waiting for $INACTIVE backend to pass healthchecks..."
MAX_ATTEMPTS=24
ATTEMPT=0
BACKEND_HEALTHY=false

while [ "$ATTEMPT" -lt "$MAX_ATTEMPTS" ]; do
    if curl -s -f "http://localhost:$BACKEND_PORT/health" > /dev/null; then
        echo "Backend is healthy!"
        BACKEND_HEALTHY=true
        break
    fi
    echo "Waiting... (Attempt $((ATTEMPT+1))/$MAX_ATTEMPTS)"
    sleep 5
    ATTEMPT=$((ATTEMPT+1))
done

if [ "$BACKEND_HEALTHY" = false ]; then
    echo "ERROR: Backend failed health check. Aborting deployment."
    echo "Stopping container failed stack..."
    docker compose -f "$INACTIVE_COMPOSE" down
    exit 1
fi

echo "Waiting for $INACTIVE frontend to be accessible..."
ATTEMPT=0
FRONTEND_HEALTHY=false

while [ "$ATTEMPT" -lt "$MAX_ATTEMPTS" ]; do
    if curl -s -f "http://localhost:$FRONTEND_PORT" > /dev/null; then
        echo "Frontend is accessible!"
        FRONTEND_HEALTHY=true
        break
    fi
    echo "Waiting... (Attempt $((ATTEMPT+1))/$MAX_ATTEMPTS)"
    sleep 5
    ATTEMPT=$((ATTEMPT+1))
done

if [ "$FRONTEND_HEALTHY" = false ]; then
    echo "ERROR: Frontend failed health check. Aborting deployment."
    echo "Stopping container failed stack..."
    docker compose -f "$INACTIVE_COMPOSE" down
    exit 1
fi

# 6. Swap upstream Nginx routing
echo "Swapping traffic from $ACTIVE to $INACTIVE..."
cat <<EOF > "$UPSTREAM_CONF"
upstream backend_upstream {
    server backend-$INACTIVE:8000;
}

upstream frontend_upstream {
    server frontend-$INACTIVE:3000;
}
EOF

# Reload Nginx configuration without downtime
echo "Reloading Nginx..."
docker exec nginx nginx -s reload

# 7. Stop the previously active stack
echo "Stopping the old active stack ($ACTIVE)..."
docker compose -f "$ACTIVE_COMPOSE" down || true

echo "=== Deployment completed successfully! Active stack is now: $INACTIVE ==="
