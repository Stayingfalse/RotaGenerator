import unittest

from rotagen.models import DAYS, DemandEntry, Person, QueueRule, ScheduleConfig, ScheduleInput
from rotagen.scheduler import generate_schedule, validate_and_apply_swap


def _base_input():
    availability = {d: set(range(24)) for d in DAYS}
    people = [
        Person("tl", "TL", {"TL"}, availability, 12),
        Person("asa", "ASA", {"ASA"}, availability, 12),
        Person("fw", "FW", {"FW", "ASA"}, availability, 12),
    ]
    queue_rules = {
        "LDM3": QueueRule("LDM3", ["TL"], {"TL"}, 1),
        "LDM1": QueueRule("LDM1", ["TL", "ASA"], {"TL", "ASA"}, 2),
        "LDM2": QueueRule("LDM2", ["ASA", "TL"], {"ASA", "TL"}, 3),
        "FW": QueueRule("FW", ["FW", "ASA"], {"FW", "ASA"}, 4),
    }
    demand = [
        DemandEntry("mon", 0, "LDM3", 1),
        DemandEntry("mon", 0, "LDM2", 1),
        DemandEntry("mon", 0, "LDM1", 1),
        DemandEntry("mon", 1, "LDM3", 1),
        DemandEntry("mon", 1, "LDM2", 1),
        DemandEntry("mon", 1, "LDM1", 1),
        DemandEntry("mon", 2, "LDM3", 1),
        DemandEntry("mon", 2, "LDM2", 1),
        DemandEntry("mon", 2, "LDM1", 1),
    ]
    return ScheduleInput(
        people=people,
        queue_rules=queue_rules,
        demand=demand,
        config=ScheduleConfig(min_shift_slots=3, max_daily_slots=8, max_spread_slots=12, global_target_hours=12),
    )


class SchedulerTests(unittest.TestCase):
    def test_priority_assignment_prefers_role(self):
        inp = _base_input()
        result = generate_schedule(inp)
        ldm3_people = {a.person_id for a in result.assignments if a.queue == "LDM3"}
        self.assertIn("tl", ldm3_people)

    def test_conflict_when_unfillable(self):
        inp = _base_input()
        inp.holidays.add(("tl", "mon"))
        result = generate_schedule(inp)
        self.assertTrue(any(c.queue == "LDM3" for c in result.conflicts))

    def test_swap_validation_rejects_invalid_role_swap(self):
        inp = _base_input()
        result = generate_schedule(inp)
        updated, err = validate_and_apply_swap(inp, result, "mon", 0, "LDM3", "LDM2")
        self.assertIsNotNone(err)
        self.assertEqual(updated.assignments, result.assignments)

    def test_swap_validation_accepts_valid_swap(self):
        inp = _base_input()
        result = generate_schedule(inp)
        updated, err = validate_and_apply_swap(inp, result, "mon", 0, "LDM1", "LDM2")
        self.assertIsNone(err)
        self.assertNotEqual(updated.assignments, result.assignments)

    def test_min_shift_removes_short_shifts(self):
        inp = _base_input()
        inp.demand = [DemandEntry("mon", 0, "LDM3", 1)]
        result = generate_schedule(inp)
        self.assertEqual(len(result.assignments), 0)
        self.assertTrue(any("insufficient eligible coverage" in c.reason.lower() for c in result.conflicts))

    def test_saturday_fairness_updates(self):
        inp = _base_input()
        inp.demand = [
            DemandEntry("sat", slot, "LDM2", 1) for slot in range(8, 16)
        ]
        result = generate_schedule(inp)
        self.assertTrue(any(v.saturday_count > 0 for v in result.fairness.values()))

    def test_saturday_requires_full_8_slot_shift(self):
        inp = _base_input()
        inp.demand = [DemandEntry("sat", 10, "LDM2", 1)]
        result = generate_schedule(inp)
        self.assertEqual(len(result.assignments), 0)
        self.assertTrue(any("insufficient eligible coverage" in c.reason.lower() for c in result.conflicts))


if __name__ == "__main__":
    unittest.main()
