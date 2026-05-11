from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta


DAYS = ["mon", "tue", "wed", "thu", "fri", "sat"]
START_HOUR = 8
END_HOUR = 20
SLOT_MINUTES = 30
SLOTS_PER_DAY = int((END_HOUR - START_HOUR) * 60 / SLOT_MINUTES)


SHIFT_BANDS = {
    "early": (0, 8),   # 08:00-12:00
    "mid": (8, 16),    # 12:00-16:00
    "late": (16, 24),  # 16:00-20:00
}


@dataclass(slots=True)
class Person:
    person_id: str
    name: str
    roles: set[str]
    default_availability: dict[str, set[int]]
    target_hours: float | None = None
    account: str = ""


@dataclass(slots=True)
class QueueRule:
    queue: str
    priority_roles: list[str]
    allowed_roles: set[str]
    queue_priority: int = 100


@dataclass(slots=True)
class DemandEntry:
    day: str
    slot: int
    queue: str
    required: int


@dataclass(slots=True)
class Assignment:
    day: str
    slot: int
    queue: str
    person_id: str


@dataclass(slots=True)
class Conflict:
    day: str
    slot: int
    queue: str
    needed: int
    assigned: int
    reason: str


@dataclass(slots=True)
class FairnessHistory:
    person_id: str
    early_count: int = 0
    mid_count: int = 0
    late_count: int = 0
    saturday_count: int = 0
    friday_late_count: int = 0


@dataclass(slots=True)
class ScheduleConfig:
    min_shift_slots: int = 3
    max_daily_slots: int = 8
    max_spread_slots: int = 12
    global_target_hours: float = 20.0


@dataclass(slots=True)
class ScheduleInput:
    people: list[Person]
    queue_rules: dict[str, QueueRule]
    demand: list[DemandEntry]
    overrides: dict[tuple[str, str], set[int]] = field(default_factory=dict)
    holidays: set[tuple[str, str]] = field(default_factory=set)
    fairness: dict[str, FairnessHistory] = field(default_factory=dict)
    config: ScheduleConfig = field(default_factory=ScheduleConfig)


@dataclass(slots=True)
class ScheduleResult:
    assignments: list[Assignment]
    conflicts: list[Conflict]
    fairness: dict[str, FairnessHistory]


def slot_label(slot: int) -> str:
    start = datetime(2000, 1, 1, START_HOUR, 0) + timedelta(minutes=SLOT_MINUTES * slot)
    end = start + timedelta(minutes=SLOT_MINUTES)
    return f"{start:%H:%M}-{end:%H:%M}"


def slot_to_band(slot: int) -> str:
    for band, (start, end) in SHIFT_BANDS.items():
        if start <= slot < end:
            return band
    return "late"
