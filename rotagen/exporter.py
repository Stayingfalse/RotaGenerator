from __future__ import annotations

from io import BytesIO

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

from rotagen.models import DAYS, ScheduleResult, slot_label


# Pastel background colors for day groups (cycles if more than 6 days)
_DAY_COLORS = ["D6E4F7", "D6F7E4", "F7F0D6", "F7D6D6", "E4D6F7", "D6F7F3"]


def export_single_worksheet(result: ScheduleResult) -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.title = "Rota"

    # Determine ordered list of queues present in assignments
    queues: list[str] = []
    seen: set[str] = set()
    for a in sorted(result.assignments, key=lambda x: x.queue):
        if a.queue not in seen:
            queues.append(a.queue)
            seen.add(a.queue)
    queues.sort()

    # Build lookup: (day, slot, queue) -> list of person_ids
    grid: dict[tuple[str, int, str], list[str]] = {}
    for a in result.assignments:
        key = (a.day, a.slot, a.queue)
        grid.setdefault(key, []).append(a.person_id)

    days_present = [d for d in DAYS if any(a.day == d for a in result.assignments)]

    # ---- Header row 1: "Time" then each day spanning len(queues) columns ----
    header1 = ["Time"]
    for day in days_present:
        header1.append(day.upper())
        header1.extend([""] * (len(queues) - 1))
    ws.append(header1)

    # Merge day header cells and style them
    time_col = 1
    col = 2
    for d_idx, day in enumerate(days_present):
        colour = _DAY_COLORS[d_idx % len(_DAY_COLORS)]
        fill = PatternFill("solid", fgColor=colour)
        start_col = col
        end_col = col + len(queues) - 1
        if len(queues) > 1:
            ws.merge_cells(
                start_row=1, start_column=start_col, end_row=1, end_column=end_col
            )
        cell = ws.cell(row=1, column=start_col)
        cell.value = day.upper()
        cell.font = Font(bold=True)
        cell.alignment = Alignment(horizontal="center")
        cell.fill = fill
        col += len(queues)

    # Style the "Time" header cell
    ws.cell(row=1, column=time_col).font = Font(bold=True)

    # ---- Header row 2: "Time" | Q1 Q2 Q3 | Q1 Q2 Q3 | … ----
    header2 = ["Time"]
    for d_idx, _day in enumerate(days_present):
        colour = _DAY_COLORS[d_idx % len(_DAY_COLORS)]
        fill = PatternFill("solid", fgColor=colour)
        for q in queues:
            header2.append(q)
    ws.append(header2)

    row2_idx = 2
    col = 2
    for d_idx, _day in enumerate(days_present):
        colour = _DAY_COLORS[d_idx % len(_DAY_COLORS)]
        fill = PatternFill("solid", fgColor=colour)
        for _q in queues:
            cell = ws.cell(row=row2_idx, column=col)
            cell.font = Font(bold=True)
            cell.fill = fill
            cell.alignment = Alignment(horizontal="center")
            col += 1

    ws.cell(row=row2_idx, column=time_col).font = Font(bold=True)

    # Determine the set of slots that have any demand
    all_slots = sorted({a.slot for a in result.assignments})

    # ---- Data rows ----
    for slot in all_slots:
        row = [slot_label(slot)]
        for day in days_present:
            for queue in queues:
                persons = grid.get((day, slot, queue), [])
                row.append(", ".join(sorted(persons)) if persons else "")
        ws.append(row)

    # ---- Auto-width columns ----
    for col_cells in ws.columns:
        max_len = max((len(str(c.value or "")) for c in col_cells), default=0)
        ws.column_dimensions[get_column_letter(col_cells[0].column)].width = min(max_len + 2, 30)

    # ---- Conflicts sheet ----
    ws2 = wb.create_sheet("Conflicts")
    ws2.append(["Day", "Time", "Queue", "Needed", "Assigned", "Reason"])
    ws2.cell(row=1, column=1).font = Font(bold=True)
    for c in sorted(result.conflicts, key=lambda x: (DAYS.index(x.day), x.slot, x.queue)):
        ws2.append([c.day.upper(), slot_label(c.slot), c.queue, c.needed, c.assigned, c.reason])

    output = BytesIO()
    wb.save(output)
    return output.getvalue()
