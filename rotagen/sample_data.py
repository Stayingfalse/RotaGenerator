from __future__ import annotations

from rotagen.models import DAYS, DemandEntry, Person, QueueRule, ScheduleConfig, ScheduleInput


def sample_input() -> ScheduleInput:
    all_slots = set(range(24))
    people = [
        Person("tl_1", "TL One", {"TL"}, {d: all_slots for d in DAYS}, 22, "Account_A"),
        Person("tl_2", "TL Two", {"TL"}, {d: all_slots for d in DAYS}, 22, "Account_A"),
        Person("asa_1", "ASA One", {"ASA"}, {d: all_slots for d in DAYS}, 20, "Account_B"),
        Person("asa_2", "ASA Two", {"ASA"}, {d: all_slots for d in DAYS}, 20, "Account_B"),
        Person("fw_1", "FW One", {"FW", "ASA"}, {d: all_slots for d in DAYS}, 18, "Account_C"),
    ]

    queue_rules = {
        "LDM3": QueueRule("LDM3", ["TL"], {"TL"}, 1),
        "LDM1": QueueRule("LDM1", ["TL", "ASA"], {"TL", "ASA"}, 2),
        "LDM2": QueueRule("LDM2", ["ASA", "TL"], {"ASA", "TL"}, 3),
        "FW": QueueRule("FW", ["FW", "ASA"], {"FW", "ASA"}, 4),
    }

    demand = []
    for day in DAYS:
        for slot in range(24):
            demand.extend(
                [
                    DemandEntry(day, slot, "LDM3", 1),
                    DemandEntry(day, slot, "LDM1", 1),
                    DemandEntry(day, slot, "LDM2", 1),
                    DemandEntry(day, slot, "FW", 1),
                ]
            )

    return ScheduleInput(
        people=people,
        queue_rules=queue_rules,
        demand=demand,
        config=ScheduleConfig(min_shift_slots=3, max_daily_slots=8, max_spread_slots=12, global_target_hours=20),
    )
