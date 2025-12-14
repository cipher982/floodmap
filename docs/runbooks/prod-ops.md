# Prod Ops (clifford / Coolify)

## Quick checks
- Site health: `curl -s https://drose.io/floodmap/api/health | head`
- Web + tileserver containers: `ssh clifford` then `docker ps` (do not filter first).

## Logs / shell
- Logs: `docker logs --tail 200 -f <container>`
- Shell: `docker exec -it <container> sh`
- Python (webapp container): `/app/.venv/bin/python`

## Data mounts (host → container)
- `/mnt/backup/floodmap/data/elevation-source` → `/app/data/elevation-source`
- `/mnt/backup/floodmap/data/elevation-tiles` → `/app/data/elevation-tiles`
- `/mnt/backup/floodmap/data/base-maps` → `/app/data/base-maps`

## Gotchas
- Avoid `docker wait` (can hang indefinitely).
- Some tools may be missing on the host (e.g. `rg`); use `grep`/`sed` instead.
