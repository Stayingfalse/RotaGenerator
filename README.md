# RotaGenerator

Single-container, single-worksheet rota generator with Mon-Sat 30-minute demand scheduling.

## Features

- Shift bands fixed at:
  - Early: 08:00-12:00
  - Mid: 12:00-16:00
  - Late: 16:00-20:00
- Weekend handling: only Saturday is included in scheduling scope (Sunday is excluded).
- Demand model: per queue, per 30-minute slot, per day.
- Queue-role priority and fallback (e.g. TL priority, ASA fallback where configured).
- Hard constraints:
  - Minimum shift length 3 slots
  - Maximum 8 slots/day
  - Maximum 6-hour spread
  - Split-shift avoidance
- Reallocation attempt when a slot cannot be filled before recording a conflict.
- Rolling fairness counters including Friday late and Saturday weighting.
- Swap validation API and drag-drop UI for same-slot queue swaps.
- Single worksheet Excel export.

## Run locally

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python app.py
```

Open http://localhost:8080

## Tests

```bash
PYTHONPATH=. python -m pytest -q
```

## Docker

### Quick start (single container, data lost when the container is removed)

```bash
docker build -t rota-generator .
docker run --rm -p 8080:8080 rota-generator
```

### Persistent database with Docker Compose (recommended)

```bash
docker compose up --build
```

This mounts a named Docker volume (`rota_data`) at `/data` inside the container so the SQLite database (`/data/rota.db`) survives container restarts and image updates.

To back up the database, or to pre-seed it with a known config, copy the file out of the volume:

```bash
docker compose cp rota-generator:/data/rota.db ./rota.db.bak
```

You can also override the database path at run-time with the `ROTA_DB` environment variable:

```bash
docker run --rm -p 8080:8080 -e ROTA_DB=/data/rota.db -v rota_data:/data rota-generator
```
