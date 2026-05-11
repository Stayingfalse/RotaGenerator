from __future__ import annotations

from collections import defaultdict
from dataclasses import replace

from rotagen.models import (
    DAYS,
    Assignment,
    Conflict,
    FairnessHistory,
    QueueRule,
    ScheduleInput,
    ScheduleResult,
    slot_to_band,
)


def _day_slots(assignments_by_person_day: dict[tuple[str, str], set[int]], person_id: str, day: str) -> set[int]:
    return assignments_by_person_day[(person_id, day)]


def _is_available(inp: ScheduleInput, person_id: str, day: str, slot: int, people_by_id: dict[str, object]) -> bool:
    if (person_id, day) in inp.holidays:
        return False
    override = inp.overrides.get((person_id, day))
    if override is not None:
        return slot in override
    person = people_by_id[person_id]
    return slot in person.default_availability.get(day, set())


def _role_rank(rule: QueueRule, person_roles: set[str]) -> int:
    best = 1000
    for idx, role in enumerate(rule.priority_roles):
        if role in person_roles:
            best = min(best, idx)
    if best != 1000:
        return best
    if person_roles & rule.allowed_roles:
        return len(rule.priority_roles) + 2
    return 9999


def _would_split(slots: set[int], new_slot: int) -> bool:
    if not slots:
        return False
    merged = sorted(slots | {new_slot})
    gaps = 0
    for i in range(1, len(merged)):
        if merged[i] - merged[i - 1] > 1:
            gaps += 1
    return gaps > 0


def _daily_spread_ok(slots: set[int], new_slot: int, max_spread_slots: int) -> bool:
    merged = slots | {new_slot}
    return (max(merged) - min(merged) + 1) <= max_spread_slots


def _score_candidate(
    inp: ScheduleInput,
    person_id: str,
    day: str,
    slot: int,
    queue: str,
    totals: dict[str, int],
    fairness: dict[str, FairnessHistory],
    people_by_id: dict[str, object],
) -> tuple:
    rule = inp.queue_rules[queue]
    person = people_by_id[person_id]
    rank = _role_rank(rule, person.roles)
    if rank >= 9999:
        return (9999, 9999, 9999, 9999)

    fh = fairness.setdefault(person_id, FairnessHistory(person_id=person_id))
    band = slot_to_band(slot)
    band_penalty = getattr(fh, f"{band}_count", 0)

    friday_late_penalty = 0
    saturday_penalty = 0
    if day == "fri" and band == "late":
        friday_late_penalty = fh.friday_late_count * 3
    if day == "sat":
        saturday_penalty = fh.saturday_count * 4

    target = people_by_id[person_id].target_hours if people_by_id[person_id].target_hours is not None else inp.config.global_target_hours
    target_slots = int(target * 2)
    target_gap = abs(target_slots - (totals[person_id] + 1))

    return (rank, friday_late_penalty + saturday_penalty + band_penalty, target_gap, totals[person_id])


def generate_schedule(inp: ScheduleInput) -> ScheduleResult:
    people_by_id = {p.person_id: p for p in inp.people}
    totals = defaultdict(int)
    assignments_by_person_day: dict[tuple[str, str], set[int]] = defaultdict(set)
    assignments_by_day_slot_queue: dict[tuple[str, int, str], list[str]] = defaultdict(list)
    conflicts: list[Conflict] = []

    fairness = {k: replace(v) for k, v in inp.fairness.items()}

    demand_items = sorted(
        inp.demand,
        key=lambda d: (DAYS.index(d.day), d.slot, inp.queue_rules[d.queue].queue_priority),
    )

    for item in demand_items:
        key = (item.day, item.slot, item.queue)
        while len(assignments_by_day_slot_queue[key]) < item.required:
            candidates = []
            for p in inp.people:
                if p.person_id in assignments_by_day_slot_queue[key]:
                    continue
                if any(
                    p.person_id in assignments_by_day_slot_queue[(item.day, item.slot, q)]
                    for q in inp.queue_rules
                ):
                    continue
                if not _is_available(inp, p.person_id, item.day, item.slot, people_by_id):
                    continue

                day_slots = _day_slots(assignments_by_person_day, p.person_id, item.day)
                if len(day_slots) >= inp.config.max_daily_slots:
                    continue
                if _would_split(day_slots, item.slot):
                    continue
                if not _daily_spread_ok(day_slots, item.slot, inp.config.max_spread_slots):
                    continue

                score = _score_candidate(inp, p.person_id, item.day, item.slot, item.queue, totals, fairness, people_by_id)
                if score[0] < 9999:
                    candidates.append((score, p.person_id))

            if candidates:
                candidates.sort(key=lambda c: c[0])
                picked = candidates[0][1]
                assignments_by_day_slot_queue[key].append(picked)
                assignments_by_person_day[(picked, item.day)].add(item.slot)
                totals[picked] += 1
                continue

            # Reallocation attempt: steal from lower-priority queue in same day+slot
            moved = False
            current_by_queue = {
                q: list(assignments_by_day_slot_queue[(item.day, item.slot, q)])
                for q in inp.queue_rules
            }
            for donor_queue, donors in current_by_queue.items():
                if donor_queue == item.queue:
                    continue
                if inp.queue_rules[donor_queue].queue_priority < inp.queue_rules[item.queue].queue_priority:
                    continue
                for donor_person in donors:
                    donor_rule = inp.queue_rules[item.queue]
                    donor_roles = people_by_id[donor_person].roles
                    if _role_rank(donor_rule, donor_roles) >= 9999:
                        continue

                    replacement = None
                    for repl in inp.people:
                        if repl.person_id == donor_person:
                            continue
                        if repl.person_id in assignments_by_day_slot_queue[(item.day, item.slot, donor_queue)]:
                            continue
                        if any(
                            repl.person_id in assignments_by_day_slot_queue[(item.day, item.slot, q)]
                            for q in inp.queue_rules
                        ):
                            continue
                        if not _is_available(inp, repl.person_id, item.day, item.slot, people_by_id):
                            continue

                        day_slots = _day_slots(assignments_by_person_day, repl.person_id, item.day)
                        if len(day_slots) >= inp.config.max_daily_slots:
                            continue
                        if _would_split(day_slots, item.slot):
                            continue
                        if not _daily_spread_ok(day_slots, item.slot, inp.config.max_spread_slots):
                            continue

                        if _role_rank(inp.queue_rules[donor_queue], repl.roles) >= 9999:
                            continue
                        replacement = repl.person_id
                        break

                    if replacement is None:
                        continue

                    assignments_by_day_slot_queue[(item.day, item.slot, donor_queue)].remove(donor_person)
                    assignments_by_day_slot_queue[(item.day, item.slot, donor_queue)].append(replacement)
                    assignments_by_person_day[(replacement, item.day)].add(item.slot)
                    totals[replacement] += 1

                    assignments_by_day_slot_queue[key].append(donor_person)
                    moved = True
                    break
                if moved:
                    break

            if not moved:
                conflicts.append(
                    Conflict(
                        day=item.day,
                        slot=item.slot,
                        queue=item.queue,
                        needed=item.required,
                        assigned=len(assignments_by_day_slot_queue[key]),
                        reason="Insufficient eligible coverage even after reallocation",
                    )
                )
                break

    # enforce min shift length by flagging and unassigning short fragments
    for (person_id, day), slots in list(assignments_by_person_day.items()):
        if not slots:
            continue
        ordered = sorted(slots)
        if len(ordered) >= inp.config.min_shift_slots:
            continue
        for slot in ordered:
            for queue in inp.queue_rules:
                k = (day, slot, queue)
                if person_id in assignments_by_day_slot_queue[k]:
                    assignments_by_day_slot_queue[k].remove(person_id)
                    totals[person_id] -= 1
                    conflicts.append(
                        Conflict(
                            day=day,
                            slot=slot,
                            queue=queue,
                            needed=1,
                            assigned=0,
                            reason="Removed to satisfy minimum shift length",
                        )
                    )

    assignments: list[Assignment] = []
    for (day, slot, queue), people in assignments_by_day_slot_queue.items():
        for person_id in people:
            assignments.append(Assignment(day=day, slot=slot, queue=queue, person_id=person_id))
            fh = fairness.setdefault(person_id, FairnessHistory(person_id=person_id))
            band = slot_to_band(slot)
            if band == "early":
                fh.early_count += 1
            elif band == "mid":
                fh.mid_count += 1
            else:
                fh.late_count += 1
            if day == "sat":
                fh.saturday_count += 1
            if day == "fri" and band == "late":
                fh.friday_late_count += 1

    assignments.sort(key=lambda a: (DAYS.index(a.day), a.slot, a.queue, a.person_id))
    return ScheduleResult(assignments=assignments, conflicts=conflicts, fairness=fairness)


def validate_and_apply_swap(inp: ScheduleInput, result: ScheduleResult, day: str, slot: int, queue_a: str, queue_b: str) -> tuple[ScheduleResult, str | None]:
    idx_a = next((i for i, a in enumerate(result.assignments) if a.day == day and a.slot == slot and a.queue == queue_a), None)
    idx_b = next((i for i, a in enumerate(result.assignments) if a.day == day and a.slot == slot and a.queue == queue_b), None)
    if idx_a is None or idx_b is None:
        return result, "Swap failed: source/target assignment not found"

    a = result.assignments[idx_a]
    b = result.assignments[idx_b]

    pa = next(p for p in inp.people if p.person_id == a.person_id)
    pb = next(p for p in inp.people if p.person_id == b.person_id)

    if _role_rank(inp.queue_rules[queue_b], pa.roles) >= 9999:
        return result, f"Swap failed: {pa.name} not eligible for {queue_b}"
    if _role_rank(inp.queue_rules[queue_a], pb.roles) >= 9999:
        return result, f"Swap failed: {pb.name} not eligible for {queue_a}"

    new_assignments = list(result.assignments)
    new_assignments[idx_a] = Assignment(day=day, slot=slot, queue=queue_a, person_id=b.person_id)
    new_assignments[idx_b] = Assignment(day=day, slot=slot, queue=queue_b, person_id=a.person_id)

    return ScheduleResult(assignments=new_assignments, conflicts=result.conflicts, fairness=result.fairness), None
