#!/usr/bin/env bash
# Create canonical Astraeus topics on a fresh cluster.
# Phase 0 only stands the broker up — actual producers/consumers ship in Phase 1.

set -euo pipefail

rpk topic create \
    astraeus.market_data.bar.created \
    astraeus.system.audit \
    --replicas 1 --partitions 3 || true

rpk topic list
