from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import asdict
from datetime import datetime, timezone
from io import BytesIO

from flask import Flask, jsonify, render_template, request, send_file

from rotagen.exporter import export_single_worksheet
from rotagen.models import DAYS, DemandEntry, FairnessHistory, Person, QueueRule, ScheduleConfig, ScheduleInput, SLOTS_PER_DAY, slot_label
from rotagen.sample_data import sample_input
from rotagen.scheduler import generate_schedule, validate_and_apply_swap


app = Flask(__name__)
LAST_INPUT: ScheduleInput | None = None
LAST_RESULT = None


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
    payload = {
        "people": [
            {
                "person_id": p.person_id,
                "name": p.name,
                "roles": sorted(list(p.roles)),
                "default_availability": {k: sorted(list(v)) for k, v in p.default_availability.items()},
                "target_hours": p.target_hours,
            }
            for p in sample_input().people
        ],
        "queue_rules": [
            {
                "queue": q.queue,
                "priority_roles": q.priority_roles,
                "allowed_roles": sorted(list(q.allowed_roles)),
                "queue_priority": q.queue_priority,
            }
            for q in sample_input().queue_rules.values()
        ],
        "demand": [asdict(d) for d in sample_input().demand],
        "overrides": [],
        "holidays": [],
        "fairness": [],
        "config": asdict(sample_input().config),
    }
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
