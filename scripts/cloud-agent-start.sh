#!/usr/bin/env bash
# Cloud Agent start: per-boot Docker daemon + local dev stack.
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${repo_root}"

export PATH="${HOME}/.local/bin:${PATH}"

COMPOSE_FILES=(
    -f infra/docker/compose.yml
    -f infra/docker/compose.override.yml
    -f infra/docker/compose.cloud-agent.yml
)

start_docker() {
    if docker info >/dev/null 2>&1; then
        return 0
    fi

    sudo update-alternatives --set iptables /usr/sbin/iptables-legacy 2>/dev/null || true
    sudo update-alternatives --set ip6tables /usr/sbin/ip6tables-legacy 2>/dev/null || true

    if [[ ! -f /etc/docker/daemon.json ]]; then
        sudo mkdir -p /etc/docker
        echo '{"storage-driver": "vfs"}' | sudo tee /etc/docker/daemon.json >/dev/null
    fi

    if ! pgrep -x dockerd >/dev/null 2>&1; then
        sudo dockerd >/tmp/dockerd.log 2>&1 &
        for _ in $(seq 1 30); do
            if docker info >/dev/null 2>&1; then
                break
            fi
            sleep 1
        done
    fi

    sudo chmod 666 /var/run/docker.sock 2>/dev/null || true
    docker info >/dev/null
}

api_healthy() {
    curl -fsS "http://localhost:8000/healthz" >/dev/null 2>&1
}

wait_for_api() {
    for _ in $(seq 1 60); do
        if api_healthy; then
            return 0
        fi
        sleep 2
    done
    return 1
}

start_host_api() {
    if api_healthy; then
        return 0
    fi

    (cd libs/db && uv run alembic upgrade head)
    if ! pgrep -f "uvicorn astraeus_api.main:app" >/dev/null 2>&1; then
        nohup uv run uvicorn astraeus_api.main:app --host 0.0.0.0 --port 8000 \
            >/tmp/astraeus-api.log 2>&1 &
    fi
    wait_for_api
}

start_docker

if ! api_healthy; then
    docker compose "${COMPOSE_FILES[@]}" build postgres
    docker compose "${COMPOSE_FILES[@]}" up -d --wait
    docker compose "${COMPOSE_FILES[@]}" --profile init run --rm minio-init
    start_host_api
    ./scripts/verify-stack.sh
fi

wait_for_api
