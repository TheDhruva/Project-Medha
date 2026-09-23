# Controlled Docker fixture (Phases 8–9)

Minimal local Compose stack used to validate execution ordering, CEG construction,
and scoped rollback **when Docker is available**.

## Safety

- Opt-in only: set `MEDHA_DOCKER_EXECUTE=true`
- Default path uses `SimulatorExecutor` (no Docker mutate)
- Images are intentionally tiny (`alpine`, `busybox`) — do not add heavy builds

## Layout

```
docker-compose.yml   # network → database → backend → frontend + independent analytics
```

## Commands

```bash
cd backend/tests/fixtures/docker
docker compose config   # structural validation only
# Real mutate is performed only by DockerExecutor when MEDHA_DOCKER_EXECUTE=true
```

If Docker is unavailable, Phase 7–9 pytest suite still passes via `SimulatorExecutor`.
