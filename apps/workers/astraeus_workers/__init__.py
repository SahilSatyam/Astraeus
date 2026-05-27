"""Astraeus workers — Phase 0 process scaffold.

Deliberately bare. The runtime choice (Celery / Arq / Temporal / Dramatiq) is
deferred to Phase 1 once the first real workload arrives. Until then this
process exists to prove that the deployment topology, observability wiring,
and Dockerfile pattern work for a non-API workload.
"""
