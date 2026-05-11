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

```bash
docker build -t rota-generator .
docker run --rm -p 8080:8080 rota-generator
```
