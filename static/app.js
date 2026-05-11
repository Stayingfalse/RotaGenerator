let current = null;
let dragPayload = null;
const ASSIGNMENTS_HEADER = "Assignments (drag to swap queues)";

function byId(id) { return document.getElementById(id); }

async function generate() {
  byId('message').textContent = '';
  try {
    const payload = JSON.parse(byId('config').value);
    const res = await fetch('/generate', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify(payload)
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || 'Generate failed');
    current = data;
    render();
  } catch (e) {
    byId('message').textContent = e.message;
  }
}

async function swap(day, slot, queueA, queueB) {
  const res = await fetch('/swap', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({ day, slot, queue_a: queueA, queue_b: queueB })
  });
  const data = await res.json();
  if (!res.ok) throw new Error(data.error || 'Swap failed');
  current = data;
  render();
}

function render() {
  if (!current) return;
  const grid = byId('grid');
  const rows = [];
  rows.push(`<table><thead><tr><th>Day</th><th>Slot</th><th>${ASSIGNMENTS_HEADER}</th></tr></thead><tbody>`);

  for (const day of current.days) {
    for (const slotInfo of current.slots) {
      const slot = String(slotInfo.slot);
      const items = ((current.grid[day] || {})[slot] || []);
      const slotCell = items.map(a =>
        `<span class="badge dropzone" draggable="true" data-day="${day}" data-slot="${slot}" data-queue="${a.queue}" data-person="${a.person_id}">${a.queue}: ${a.person_id}</span>`
      ).join(' ');
      rows.push(`<tr><td>${day.toUpperCase()}</td><td>${slotInfo.label}</td><td class="dropzone" data-day="${day}" data-slot="${slot}">${slotCell}</td></tr>`);
    }
  }

  rows.push('</tbody></table>');
  grid.innerHTML = rows.join('');

  byId('conflicts').textContent = JSON.stringify(current.conflicts, null, 2);

  document.querySelectorAll('.badge[draggable="true"]').forEach(el => {
    el.addEventListener('dragstart', ev => {
      dragPayload = {
        day: ev.target.dataset.day,
        slot: Number(ev.target.dataset.slot),
        queue: ev.target.dataset.queue,
        person: ev.target.dataset.person
      };
    });
  });

  document.querySelectorAll('.badge.dropzone').forEach(el => {
    el.addEventListener('dragover', ev => ev.preventDefault());
    el.addEventListener('drop', async ev => {
      ev.preventDefault();
      if (!dragPayload) return;
      const target = ev.target.dataset;
      if (dragPayload.day !== target.day || String(dragPayload.slot) !== target.slot || dragPayload.queue === target.queue) return;
      try {
        await swap(dragPayload.day, dragPayload.slot, dragPayload.queue, target.queue);
      } catch (e) {
        byId('message').textContent = e.message;
      }
    });
  });
}

byId('generateBtn').addEventListener('click', generate);
