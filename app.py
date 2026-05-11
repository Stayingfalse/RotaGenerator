from __future__ import annotations

import csv
import io
import json
from collections import defaultdict
from dataclasses import asdict
from datetime import datetime, timezone
from io import BytesIO

from flask import Flask, jsonify, render_template, request, send_file

from rotagen import db
from rotagen.exporter import export_single_worksheet
from rotagen.models import DAYS, DemandEntry, FairnessHistory, Person, QueueRule, ScheduleConfig, ScheduleInput, SLOTS_PER_DAY, slot_label
from rotagen.sample_data import sample_input
from rotagen.scheduler import generate_schedule, validate_and_apply_swap


app = Flask(__name__)
LAST_INPUT: ScheduleInput | None = None
LAST_RESULT = None


def _build_seed_payload() -> dict:
    """Build the seed payload from sample_input for first-run DB seeding."""
    si = sample_input()
    return {
        "people": [
            {
                "person_id": p.person_id,
                "name": p.name,
                "roles": sorted(list(p.roles)),
                "default_availability": {k: sorted(list(v)) for k, v in p.default_availability.items()},
                "target_hours": p.target_hours,
                "account": p.account,
            }
            for p in si.people
        ],
        "queue_rules": [
            {
                "queue": q.queue,
                "priority_roles": q.priority_roles,
                "allowed_roles": sorted(list(q.allowed_roles)),
                "queue_priority": q.queue_priority,
            }
            for q in si.queue_rules.values()
        ],
        "demand": [asdict(d) for d in si.demand],
        "overrides": [],
        "holidays": [],
        "fairness": [],
        "config": asdict(si.config),
    }


# Initialise the database (seeds with sample data on first run)
with app.app_context():
    db.init_db(_build_seed_payload())


def _parse_payload(payload: dict) -> ScheduleInput:
    people = []
    for p in payload["people"]:
        people.append(
            Person(
                person_id=p["person_id"],
                name=p["name"],
                roles=set(p["roles"]),
                default_availability={k: set(v) for k, v in p["default_availability"].items()},
                target_hours=p.get("target_hours"),
                account=p.get("account", ""),
            )
        )

    queue_rules = {}
    for q in payload["queue_rules"]:
        queue_rules[q["queue"]] = QueueRule(
            queue=q["queue"],
            priority_roles=q["priority_roles"],
            allowed_roles=set(q["allowed_roles"]),
            queue_priority=q.get("queue_priority", 100),
        )

    demand = [DemandEntry(**d) for d in payload["demand"]]

    overrides = {
        (o["person_id"], o["day"]): set(o["available_slots"])
        for o in payload.get("overrides", [])
    }
    holidays = {(h["person_id"], h["day"]) for h in payload.get("holidays", [])}

    fairness = {}
    for f in payload.get("fairness", []):
        fairness[f["person_id"]] = FairnessHistory(
            person_id=f["person_id"],
            early_count=f.get("early_count", 0),
            mid_count=f.get("mid_count", 0),
            late_count=f.get("late_count", 0),
            saturday_count=f.get("saturday_count", 0),
            friday_late_count=f.get("friday_late_count", 0),
        )

    cfg = payload.get("config", {})
    config = ScheduleConfig(
        min_shift_slots=cfg.get("min_shift_slots", 3),
        max_daily_slots=cfg.get("max_daily_slots", 8),
        max_spread_slots=cfg.get("max_spread_slots", 12),
        global_target_hours=cfg.get("global_target_hours", 20.0),
    )

    return ScheduleInput(
        people=people,
        queue_rules=queue_rules,
        demand=demand,
        overrides=overrides,
        holidays=holidays,
        fairness=fairness,
        config=config,
    )


def _render_schedule(result):
    by_day_slot = defaultdict(lambda: defaultdict(list))
    for a in result.assignments:
        by_day_slot[a.day][a.slot].append({"queue": a.queue, "person_id": a.person_id})

    return {
        "assignments": [asdict(a) for a in result.assignments],
        "conflicts": [asdict(c) for c in result.conflicts],
        "grid": {
            day: {
                str(slot): sorted(v, key=lambda x: (x["queue"], x["person_id"]))
                for slot, v in slot_map.items()
            }
            for day, slot_map in by_day_slot.items()
        },
        "slots": [{"slot": i, "label": slot_label(i)} for i in range(SLOTS_PER_DAY)],
        "days": DAYS,
    }


@app.get("/")
def home():
    payload = db.load_config()
    return render_template("index.html", sample_payload=payload, sample_json=json.dumps(payload, indent=2))


@app.post("/generate")
def generate():
    global LAST_INPUT, LAST_RESULT
    payload = request.get_json(force=True)
    LAST_INPUT = _parse_payload(payload)
    LAST_RESULT = generate_schedule(LAST_INPUT)
    return jsonify(_render_schedule(LAST_RESULT))


@app.post("/swap")
def swap():
    global LAST_RESULT
    if LAST_INPUT is None or LAST_RESULT is None:
        return jsonify({"error": "No generated schedule yet"}), 400

    body = request.get_json(force=True)
    day = body["day"]
    slot = int(body["slot"])
    queue_a = body["queue_a"]
    queue_b = body["queue_b"]

    LAST_RESULT, err = validate_and_apply_swap(LAST_INPUT, LAST_RESULT, day, slot, queue_a, queue_b)
    if err:
        return jsonify({"error": err}), 400
    return jsonify(_render_schedule(LAST_RESULT))


@app.post("/import-csv")
def import_csv():
    """Parse a CSV upload with columns: UserID, UserName, Account, Hours, Role.
    Column names are matched case-insensitively with surrounding whitespace stripped.
    Returns a JSON array of person objects ready to merge into the dashboard state.
    Multiple rows for the same UserID accumulate roles.
    """
    if "file" not in request.files:
        return jsonify({"error": "No file uploaded"}), 400
    f = request.files["file"]
    try:
        text = f.read().decode("utf-8-sig")
    except UnicodeDecodeError:
        return jsonify({"error": "File is not valid UTF-8. Please save as UTF-8 and try again."}), 400
    extra_columns_key = "__extra_columns__"
    reader = csv.DictReader(io.StringIO(text), restkey=extra_columns_key)

    # Normalise header names: strip whitespace and lowercase
    if reader.fieldnames is None:
        return jsonify({"error": "Empty CSV"}), 400

    expected = {"userid", "username", "account", "hours", "role"}
    actual = {h.strip().lower() for h in reader.fieldnames if h is not None}
    missing = expected - actual
    if missing:
        return jsonify({"error": f"Missing CSV columns: {', '.join(sorted(missing))}"}), 400

    people_map: dict[str, dict] = {}
    all_slots = list(range(24))
    for row_num, row in enumerate(reader, start=2):
        if row.get(extra_columns_key):
            return jsonify(
                {
                    "error": (
                        f"Malformed CSV on row {row_num}: found extra columns beyond the header row."
                    )
                }
            ), 400
        norm = {
            k.strip().lower(): (v.strip() if v else "")
            for k, v in row.items()
            if k is not None and k != extra_columns_key
        }
        pid = norm.get("userid", "").strip()
        if not pid:
            continue
        if pid not in people_map:
            people_map[pid] = {
                "person_id": pid,
                "name": norm.get("username", pid),
                "account": norm.get("account", ""),
                "target_hours": None,
                "roles": [],
                "default_availability": {d: all_slots for d in ["mon", "tue", "wed", "thu", "fri", "sat"]},
            }
        # Update fields from this row (last row wins for non-role fields)
        if norm.get("username"):
            people_map[pid]["name"] = norm["username"]
        if norm.get("account"):
            people_map[pid]["account"] = norm["account"]
        hours_raw = norm.get("hours", "")
        if hours_raw:
            try:
                people_map[pid]["target_hours"] = float(hours_raw)
            except ValueError:
                pass
        role = norm.get("role", "").strip()
        if role and role not in people_map[pid]["roles"]:
            people_map[pid]["roles"].append(role)

    return jsonify(list(people_map.values()))


@app.post("/config")
def save_config():
    """Persist the full dashboard configuration to the database."""
    payload = request.get_json(force=True)
    db.save_config(payload)
    return jsonify({"status": "saved"})


@app.get("/export.xlsx")
def export_xlsx():
    if LAST_RESULT is None:
        return jsonify({"error": "No schedule to export"}), 400
    data = export_single_worksheet(LAST_RESULT)
    return send_file(
        BytesIO(data),
        as_attachment=True,
        download_name=f"rota-{datetime.now(timezone.utc):%Y%m%d%H%M%S}.xlsx",
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)
