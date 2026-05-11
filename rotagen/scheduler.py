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


_DEFAULT_QUEUE_IDEAL_SHIFT_SLOTS = {
    "LDM1": 8,
    "LDM2": 6,
    "LDM3": 8,
    "ICH_FW": 4,
    "MSK_FW": 5,
}
UNELIGIBLE_RANK = 9999
UNKNOWN_ELIGIBLE_COUNT = 9999
UNELIGIBLE_SCORE = (UNELIGIBLE_RANK,) * 4
FRIDAY_LATE_SORT_KEY = -1
# Earlier sort-key values are processed first. Saturday is strongest contested-day
# priority, Friday next, then all other days.
SATURDAY_DAY_SORT_KEY = -2
FRIDAY_DAY_SORT_KEY = -1


def _day_slots(assignments_by_person_day: dict[tuple[str, str], set[int]], person_id: str, day: str) -> set[int]:
    return assignments_by_person_day[(person_id, day)]


def _is_friday_late_slot(day: str, slot: int) -> bool:
    return day == "fri" and slot_to_band(slot) == "late"


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
    return UNELIGIBLE_RANK


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


def _effective_min_shift_slots(inp: ScheduleInput, day: str) -> int:
    if day == "sat":
        return 8
    return max(1, inp.config.min_shift_slots)


def _ideal_shift_slots(inp: ScheduleInput, day: str, queue: str) -> int | None:
    if day == "sat":
        return 8
    configured = getattr(inp.queue_rules.get(queue), "ideal_shift_slots", None)
    if configured is not None:
        try:
            val = int(configured)
            if val > 0:
                return val
        except (TypeError, ValueError):
            pass
    return _DEFAULT_QUEUE_IDEAL_SHIFT_SLOTS.get(queue.upper())


def _open_eligible_demand_by_slot(
    inp: ScheduleInput,
    people_by_id: dict[str, object],
    demand_required: dict[tuple[str, int, str], int],
    assignments_by_day_slot_queue: dict[tuple[str, int, str], list[str]],
    person_id: str,
    day: str,
    slot: int,
) -> bool:
    if not _is_available(inp, person_id, day, slot, people_by_id):
        return False
    if any(person_id in assignments_by_day_slot_queue[(day, slot, q)] for q in inp.queue_rules):
        return False
    person_roles = people_by_id[person_id].roles
    for queue, rule in inp.queue_rules.items():
        need = demand_required.get((day, slot, queue), 0)
        if need <= len(assignments_by_day_slot_queue[(day, slot, queue)]):
            continue
        if _role_rank(rule, person_roles) < UNELIGIBLE_RANK:
            return True
    return False


def _can_still_meet_min_shift(
    inp: ScheduleInput,
    people_by_id: dict[str, object],
    demand_required: dict[tuple[str, int, str], int],
    assignments_by_day_slot_queue: dict[tuple[str, int, str], list[str]],
    person_id: str,
    day: str,
    current_slots: set[int],
    new_slot: int,
) -> bool:
    min_slots = _effective_min_shift_slots(inp, day)
    merged = current_slots | {new_slot}
    if len(merged) >= min_slots:
        return True
    run = set(merged)
    left = min(merged) - 1
    while left >= 0:
        if _open_eligible_demand_by_slot(
            inp, people_by_id, demand_required, assignments_by_day_slot_queue, person_id, day, left
        ):
            run.add(left)
            left -= 1
            continue
        break
    right = max(merged) + 1
    while right < 24:
        if _open_eligible_demand_by_slot(
            inp, people_by_id, demand_required, assignments_by_day_slot_queue, person_id, day, right
        ):
            run.add(right)
            right += 1
            continue
        break
    return len(run) >= min_slots


def _pick_open_queue_for_person_slot(
    inp: ScheduleInput,
    people_by_id: dict[str, object],
    demand_required: dict[tuple[str, int, str], int],
    assignments_by_day_slot_queue: dict[tuple[str, int, str], list[str]],
    person_id: str,
    day: str,
    slot: int,
) -> str | None:
    if any(person_id in assignments_by_day_slot_queue[(day, slot, q)] for q in inp.queue_rules):
        return None
    person = people_by_id[person_id]
    best_queue = None
    best_priority = 10**9
    for queue, rule in inp.queue_rules.items():
        if _role_rank(rule, person.roles) >= UNELIGIBLE_RANK:
            continue
        key = (day, slot, queue)
        if len(assignments_by_day_slot_queue[key]) >= demand_required.get(key, 0):
            continue
        if rule.queue_priority < best_priority:
            best_priority = rule.queue_priority
            best_queue = queue
    return best_queue


def _find_replacement_for_slot(
    inp: ScheduleInput,
    people_by_id: dict[str, object],
    demand_required: dict[tuple[str, int, str], int],
    assignments_by_day_slot_queue: dict[tuple[str, int, str], list[str]],
    assignments_by_person_day: dict[tuple[str, str], set[int]],
    person_id: str,
    day: str,
    slot: int,
    queue: str,
) -> str | None:
    for repl in inp.people:
        if repl.person_id == person_id:
            continue
        if repl.person_id in assignments_by_day_slot_queue[(day, slot, queue)]:
            continue
        if any(repl.person_id in assignments_by_day_slot_queue[(day, slot, q)] for q in inp.queue_rules):
            continue
        if not _is_available(inp, repl.person_id, day, slot, people_by_id):
            continue
        if _role_rank(inp.queue_rules[queue], repl.roles) >= UNELIGIBLE_RANK:
            continue

        day_slots = _day_slots(assignments_by_person_day, repl.person_id, day)
        if len(day_slots) >= inp.config.max_daily_slots:
            continue
        if _would_split(day_slots, slot):
            continue
        if not _daily_spread_ok(day_slots, slot, inp.config.max_spread_slots):
            continue
        if not _can_still_meet_min_shift(
            inp,
            people_by_id,
            demand_required,
            assignments_by_day_slot_queue,
            repl.person_id,
            day,
            day_slots,
            slot,
        ):
            continue
        return repl.person_id
    return None


def _score_candidate(
    inp: ScheduleInput,
    person_id: str,
    day: str,
    slot: int,
    queue: str,
    totals: dict[str, int],
    fairness: dict[str, FairnessHistory],
    people_by_id: dict[str, object],
    assignments_by_person_day: dict[tuple[str, str], set[int]],
) -> tuple:
    rule = inp.queue_rules[queue]
    person = people_by_id[person_id]
    rank = _role_rank(rule, person.roles)
    if rank >= UNELIGIBLE_RANK:
        return UNELIGIBLE_SCORE

    fh = fairness.setdefault(person_id, FairnessHistory(person_id=person_id))
    band = slot_to_band(slot)
    band_penalty = getattr(fh, f"{band}_count", 0)

    friday_late_penalty = 0
    saturday_penalty = 0
    if day == "fri" and band == "late":
        friday_late_penalty = fh.friday_late_count * 3
    if day == "sat":
        saturday_penalty = fh.saturday_count * 4

    target = person.target_hours if person.target_hours is not None else inp.config.global_target_hours
    target_slots = int(target * 2)
    target_gap = abs(target_slots - (totals[person_id] + 1))
    day_slots = _day_slots(assignments_by_person_day, person_id, day)
    ideal = _ideal_shift_slots(inp, day, queue)
    ideal_penalty = 0
    empty_shift_start_penalty = 0
    if ideal is not None:
        projected = len(day_slots) + 1
        ideal_penalty = abs(ideal - projected)
        if not day_slots:
            empty_shift_start_penalty = ideal

    return (
        rank,
        friday_late_penalty + saturday_penalty + band_penalty + ideal_penalty + empty_shift_start_penalty,
        target_gap,
        totals[person_id],
    )


def generate_schedule(inp: ScheduleInput) -> ScheduleResult:
    people_by_id = {p.person_id: p for p in inp.people}
    totals = defaultdict(int)
    assignments_by_person_day: dict[tuple[str, str], set[int]] = defaultdict(set)
    assignments_by_day_slot_queue: dict[tuple[str, int, str], list[str]] = defaultdict(list)
    conflicts: list[Conflict] = []

    fairness = {k: replace(v) for k, v in inp.fairness.items()}

    demand_required = {(d.day, d.slot, d.queue): d.required for d in inp.demand}
    eligible_counts = {}
    for d in inp.demand:
        cnt = 0
        for p in inp.people:
            if not _is_available(inp, p.person_id, d.day, d.slot, people_by_id):
                continue
            if _role_rank(inp.queue_rules[d.queue], p.roles) >= UNELIGIBLE_RANK:
                continue
            cnt += 1
        eligible_counts[(d.day, d.slot, d.queue)] = cnt

    day_order = {d: i for i, d in enumerate(DAYS)}
    special_day_priority = {"sat": SATURDAY_DAY_SORT_KEY, "fri": FRIDAY_DAY_SORT_KEY}

    demand_items = sorted(
        inp.demand,
        key=lambda d: (
            special_day_priority.get(d.day, 0),
            FRIDAY_LATE_SORT_KEY if _is_friday_late_slot(d.day, d.slot) else 0,
            eligible_counts.get((d.day, d.slot, d.queue), UNKNOWN_ELIGIBLE_COUNT),
            -d.required,
            -d.slot if d.day in {"sat", "fri"} else d.slot,
            day_order.get(d.day, len(DAYS) + 1),
            inp.queue_rules[d.queue].queue_priority,
        ),
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
                if not _can_still_meet_min_shift(
                    inp,
                    people_by_id,
                    demand_required,
                    assignments_by_day_slot_queue,
                    p.person_id,
                    item.day,
                    day_slots,
                    item.slot,
                ):
                    continue

                score = _score_candidate(
                    inp,
                    p.person_id,
                    item.day,
                    item.slot,
                    item.queue,
                    totals,
                    fairness,
                    people_by_id,
                    assignments_by_person_day,
                )
                if score[0] < UNELIGIBLE_RANK:
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
                    if _role_rank(donor_rule, donor_roles) >= UNELIGIBLE_RANK:
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
                        if not _can_still_meet_min_shift(
                            inp,
                            people_by_id,
                            demand_required,
                            assignments_by_day_slot_queue,
                            repl.person_id,
                            item.day,
                            day_slots,
                            item.slot,
                        ):
                            continue

                        if _role_rank(inp.queue_rules[donor_queue], repl.roles) >= UNELIGIBLE_RANK:
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
        while len(slots) < _effective_min_shift_slots(inp, day):
            if len(slots) >= inp.config.max_daily_slots:
                break
            adjacent = []
            lo = min(slots) - 1
            hi = max(slots) + 1
            if lo >= 0:
                adjacent.append(lo)
            if hi < 24:
                adjacent.append(hi)
            added = False
            for candidate_slot in adjacent:
                if not _is_available(inp, person_id, day, candidate_slot, people_by_id):
                    continue
                if _would_split(slots, candidate_slot):
                    continue
                if not _daily_spread_ok(slots, candidate_slot, inp.config.max_spread_slots):
                    continue
                queue = _pick_open_queue_for_person_slot(
                    inp,
                    people_by_id,
                    demand_required,
                    assignments_by_day_slot_queue,
                    person_id,
                    day,
                    candidate_slot,
                )
                if queue is None:
                    continue
                assignments_by_day_slot_queue[(day, candidate_slot, queue)].append(person_id)
                slots.add(candidate_slot)
                totals[person_id] += 1
                added = True
                break
            if not added:
                break

        ordered = sorted(slots, reverse=True)
        if len(ordered) >= _effective_min_shift_slots(inp, day):
            continue
        removed_slots: set[int] = set()
        for slot in ordered:
            for queue in inp.queue_rules:
                k = (day, slot, queue)
                if person_id in assignments_by_day_slot_queue[k]:
                    replacement = _find_replacement_for_slot(
                        inp,
                        people_by_id,
                        demand_required,
                        assignments_by_day_slot_queue,
                        assignments_by_person_day,
                        person_id,
                        day,
                        slot,
                        queue,
                    )
                    if replacement is not None:
                        assignments_by_day_slot_queue[k].remove(person_id)
                        assignments_by_day_slot_queue[k].append(replacement)
                        assignments_by_person_day[(replacement, day)].add(slot)
                        totals[person_id] -= 1
                        totals[replacement] += 1
                        removed_slots.add(slot)
                        continue

                    assignments_by_day_slot_queue[k].remove(person_id)
                    totals[person_id] -= 1
                    removed_slots.add(slot)
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
        if removed_slots:
            assignments_by_person_day[(person_id, day)].difference_update(removed_slots)

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

    if _role_rank(inp.queue_rules[queue_b], pa.roles) >= UNELIGIBLE_RANK:
        return result, f"Swap failed: {pa.name} not eligible for {queue_b}"
    if _role_rank(inp.queue_rules[queue_a], pb.roles) >= UNELIGIBLE_RANK:
        return result, f"Swap failed: {pb.name} not eligible for {queue_a}"

    new_assignments = list(result.assignments)
    new_assignments[idx_a] = Assignment(day=day, slot=slot, queue=queue_a, person_id=b.person_id)
    new_assignments[idx_b] = Assignment(day=day, slot=slot, queue=queue_b, person_id=a.person_id)

    return ScheduleResult(assignments=new_assignments, conflicts=result.conflicts, fairness=result.fairness), None
