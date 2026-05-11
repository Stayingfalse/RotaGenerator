from __future__ import annotations

from io import BytesIO

from openpyxl import Workbook

from rotagen.models import DAYS, ScheduleResult, slot_label


def export_single_worksheet(result: ScheduleResult) -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.title = "Rota"

    ws.append(["Day", "Time", "Queue", "Person"])
    for a in sorted(result.assignments, key=lambda x: (DAYS.index(x.day), x.slot, x.queue, x.person_id)):
        ws.append([a.day.upper(), slot_label(a.slot), a.queue, a.person_id])

    ws.append([])
    ws.append(["Conflicts"])
    ws.append(["Day", "Time", "Queue", "Needed", "Assigned", "Reason"])
    for c in sorted(result.conflicts, key=lambda x: (DAYS.index(x.day), x.slot, x.queue)):
        ws.append([c.day.upper(), slot_label(c.slot), c.queue, c.needed, c.assigned, c.reason])

    output = BytesIO()
    wb.save(output)
    return output.getvalue()
