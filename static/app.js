const { useMemo, useState } = React;

const DAYS = ["mon", "tue", "wed", "thu", "fri", "sat"];
const START_HOUR = 8;
const SLOT_COUNT = 24;

function slotLabel(slot) {
  const totalMinutes = (START_HOUR * 60) + (slot * 30);
  const endMinutes = totalMinutes + 30;
  const toTime = (mins) => {
    const h = String(Math.floor(mins / 60)).padStart(2, "0");
    const m = String(mins % 60).padStart(2, "0");
    return `${h}:${m}`;
  };
  return `${toTime(totalMinutes)}-${toTime(endMinutes)}`;
}

function unique(items) {
  return [...new Set(items.filter(Boolean))];
}

function slugify(value) {
  return String(value || "")
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "_")
    .replace(/^_+|_+$/g, "");
}

function fullAvailability() {
  const allSlots = Array.from({ length: SLOT_COUNT }, (_, i) => i);
  return Object.fromEntries(DAYS.map((day) => [day, allSlots]));
}

function normalizeConfig(raw) {
  const people = (raw.people || []).map((p) => ({
    person_id: String(p.person_id || ""),
    name: String(p.name || ""),
    roles: unique(p.roles || []),
    default_availability: p.default_availability || fullAvailability(),
    target_hours: p.target_hours ?? "",
  }));

  const jobTitles = (raw.queue_rules || []).map((q) => ({
    queue: q.queue,
    queue_priority: Number.isFinite(Number(q.queue_priority)) ? Number(q.queue_priority) : 100,
    allowed_roles: unique(q.allowed_roles || []),
    priority_roles: unique(q.priority_roles || []),
  }));

  const skillPool = unique([
    ...people.flatMap((p) => p.roles || []),
    ...jobTitles.flatMap((q) => [...(q.allowed_roles || []), ...(q.priority_roles || [])]),
  ]).sort();

  const demandMap = new Map();
  for (const d of raw.demand || []) {
    demandMap.set(`${d.day}|${d.slot}|${d.queue}`, Math.max(0, Number(d.required) || 0));
  }

  for (const day of DAYS) {
    for (let slot = 0; slot < SLOT_COUNT; slot += 1) {
      for (const q of jobTitles) {
        const key = `${day}|${slot}|${q.queue}`;
        if (!demandMap.has(key)) demandMap.set(key, 0);
      }
    }
  }

  return {
    people,
    skills: skillPool,
    jobTitles,
    demandMap,
    overrides: raw.overrides || [],
    holidays: raw.holidays || [],
    fairness: raw.fairness || [],
    config: raw.config || {},
  };
}

function buildPayload(state) {
  const queueNames = new Set(state.jobTitles.map((j) => j.queue));
  const demand = [];
  for (const [key, required] of state.demandMap.entries()) {
    const [day, slotRaw, queue] = key.split("|");
    if (!queueNames.has(queue)) continue;
    demand.push({ day, slot: Number(slotRaw), queue, required: Math.max(0, Number(required) || 0) });
  }

  return {
    people: state.people.map((p) => ({
      person_id: String(p.person_id || ""),
      name: String(p.name || ""),
      roles: unique(p.roles || []),
      default_availability: p.default_availability || fullAvailability(),
      target_hours: p.target_hours === "" || Number.isNaN(Number(p.target_hours)) ? null : Number(p.target_hours),
    })),
    queue_rules: state.jobTitles.map((q) => ({
      queue: q.queue,
      queue_priority: Number(q.queue_priority) || 100,
      allowed_roles: unique((q.allowed_roles || []).filter((r) => state.skills.includes(r))),
      priority_roles: unique((q.priority_roles || []).filter((r) => (q.allowed_roles || []).includes(r))),
    })),
    demand,
    overrides: state.overrides || [],
    holidays: state.holidays || [],
    fairness: state.fairness || [],
    config: state.config || {},
  };
}

function App() {
  const [state, setState] = useState(() => normalizeConfig(window.__INITIAL_CONFIG__ || {}));
  const [newSkill, setNewSkill] = useState("");
  const [newJobTitle, setNewJobTitle] = useState("");
  const [activeDay, setActiveDay] = useState("mon");
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState(null);
  const [dragPayload, setDragPayload] = useState(null);

  const slotOptions = useMemo(() => Array.from({ length: SLOT_COUNT }, (_, i) => ({ slot: i, label: slotLabel(i) })), []);

  const addUser = () => {
    setState((prev) => {
      let n = prev.people.length + 1;
      let personId = `user_${n}`;
      const ids = new Set(prev.people.map((p) => p.person_id));
      while (ids.has(personId)) {
        n += 1;
        personId = `user_${n}`;
      }
      return {
        ...prev,
        people: [...prev.people, { person_id: personId, name: `User ${n}`, roles: [], target_hours: "", default_availability: fullAvailability() }],
      };
    });
  };

  const removeUser = (personId) => {
    setState((prev) => ({ ...prev, people: prev.people.filter((p) => p.person_id !== personId) }));
  };

  const updateUser = (personId, updater) => {
    setState((prev) => ({
      ...prev,
      people: prev.people.map((p) => (p.person_id === personId ? updater(p) : p)),
    }));
  };

  const renameUserId = (personId, candidate) => {
    const nextId = slugify(candidate);
    if (!nextId || nextId === personId) return;
    if (state.people.some((p) => p.person_id === nextId)) {
      setMessage(`User ID '${nextId}' already exists.`);
      return;
    }
    setState((prev) => ({
      ...prev,
      people: prev.people.map((p) => (p.person_id === personId ? { ...p, person_id: nextId } : p)),
    }));
  };

  const addSkill = () => {
    const value = newSkill.trim();
    if (!value) return;
    setState((prev) => {
      if (prev.skills.includes(value)) return prev;
      return { ...prev, skills: [...prev.skills, value].sort() };
    });
    setNewSkill("");
  };

  const removeSkill = (skill) => {
    setState((prev) => ({
      ...prev,
      skills: prev.skills.filter((s) => s !== skill),
      people: prev.people.map((p) => ({ ...p, roles: (p.roles || []).filter((r) => r !== skill) })),
      jobTitles: prev.jobTitles.map((j) => ({
        ...j,
        allowed_roles: (j.allowed_roles || []).filter((r) => r !== skill),
        priority_roles: (j.priority_roles || []).filter((r) => r !== skill),
      })),
    }));
  };

  const addJobTitle = () => {
    const trimmedInput = newJobTitle.trim();
    const queue = trimmedInput || `queue_${state.jobTitles.length + 1}`;
    if (state.jobTitles.some((j) => j.queue === queue)) return;

    setState((prev) => {
      const next = {
        ...prev,
        jobTitles: [...prev.jobTitles, { queue, queue_priority: prev.jobTitles.length + 1, allowed_roles: [], priority_roles: [] }],
      };
      const demandMap = new Map(next.demandMap);
      for (const day of DAYS) {
        for (let slot = 0; slot < SLOT_COUNT; slot += 1) {
          const key = `${day}|${slot}|${queue}`;
          if (!demandMap.has(key)) demandMap.set(key, 0);
        }
      }
      next.demandMap = demandMap;
      return next;
    });
    setNewJobTitle("");
  };

  const removeJobTitle = (queue) => {
    setState((prev) => {
      const demandMap = new Map();
      for (const [key, value] of prev.demandMap.entries()) {
        if (!key.endsWith(`|${queue}`)) demandMap.set(key, value);
      }
      return {
        ...prev,
        jobTitles: prev.jobTitles.filter((j) => j.queue !== queue),
        demandMap,
      };
    });
  };

  const updateJobTitle = (queue, updater) => {
    setState((prev) => ({
      ...prev,
      jobTitles: prev.jobTitles.map((j) => {
        if (j.queue !== queue) return j;
        const next = updater(j);
        const allowed = unique(next.allowed_roles || []);
        return {
          ...next,
          allowed_roles: allowed,
          priority_roles: unique((next.priority_roles || []).filter((r) => allowed.includes(r))),
        };
      }),
    }));
  };

  const updateDemand = (day, slot, queue, required) => {
    setState((prev) => {
      const demandMap = new Map(prev.demandMap);
      demandMap.set(`${day}|${slot}|${queue}`, Math.max(0, Number(required) || 0));
      return { ...prev, demandMap };
    });
  };

  const validateForGenerate = () => {
    if (state.people.length === 0) return "Add at least one user.";
    if (state.jobTitles.length === 0) return "Add at least one job title.";
    if (state.people.some((p) => !String(p.person_id || "").trim() || !String(p.name || "").trim())) {
      return "Every user must have both an ID and name.";
    }
    if (state.jobTitles.some((j) => !String(j.queue || "").trim())) {
      return "Every job title must have a name.";
    }
    return "";
  };

  const generate = async () => {
    const validationError = validateForGenerate();
    if (validationError) {
      setMessage(validationError);
      return;
    }

    setMessage("");
    setBusy(true);
    try {
      const payload = buildPayload(state);
      const res = await fetch("/generate", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || "Generate failed");
      setResult(data);
    } catch (err) {
      setMessage(err.message || "Generate failed");
    } finally {
      setBusy(false);
    }
  };

  const swap = async (day, slot, queueA, queueB) => {
    const res = await fetch("/swap", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ day, slot, queue_a: queueA, queue_b: queueB }),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || "Swap failed");
    setResult(data);
  };

  return (
    <>
      <div className="panel">
        <h2 className="section-title">Rota Dashboard</h2>
        <p className="muted">Manage users, skills, job titles, and requirement matrix from a structured React UI.</p>
        <div className="row">
          <button className="btn primary" onClick={generate} disabled={busy}>{busy ? "Generating..." : "Generate Schedule"}</button>
          <a className="btn" href="/export.xlsx" target="_blank" rel="noreferrer">Export XLSX</a>
        </div>
        {message && <div className="error">{message}</div>}
      </div>

      <div className="panel">
        <h3 className="section-title">Users</h3>
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>User ID</th>
                <th>Name</th>
                <th>Target Hours</th>
                <th>Assigned Skills</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {state.people.map((p) => (
                <tr key={p.person_id}>
                  <td>
                    <input
                      value={p.person_id}
                      onChange={(e) => renameUserId(p.person_id, e.target.value)}
                    />
                  </td>
                  <td><input value={p.name} onChange={(e) => updateUser(p.person_id, (curr) => ({ ...curr, name: e.target.value }))} /></td>
                  <td>
                    <input
                      type="number"
                      min="0"
                      value={p.target_hours}
                      onChange={(e) => updateUser(p.person_id, (curr) => ({ ...curr, target_hours: e.target.value }))}
                    />
                  </td>
                  <td>
                    {state.skills.length === 0 && <span className="muted">Add skills first</span>}
                    {state.skills.map((skill) => {
                      const checked = (p.roles || []).includes(skill);
                      return (
                        <label key={`${p.person_id}-${skill}`} className="pill">
                          <input
                            type="checkbox"
                            checked={checked}
                            onChange={(e) => updateUser(p.person_id, (curr) => ({
                              ...curr,
                              roles: e.target.checked
                                ? unique([...(curr.roles || []), skill])
                                : (curr.roles || []).filter((r) => r !== skill),
                            }))}
                          />
                          {skill}
                        </label>
                      );
                    })}
                  </td>
                  <td><button className="btn danger" onClick={() => removeUser(p.person_id)}>Remove</button></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <div style={{ marginTop: 10 }}>
          <button className="btn" onClick={addUser}>Add User</button>
        </div>
      </div>

      <div className="panel">
        <h3 className="section-title">Skills</h3>
        <div className="row">
          <input placeholder="Add new skill (e.g. TL)" value={newSkill} onChange={(e) => setNewSkill(e.target.value)} />
          <button className="btn" onClick={addSkill}>Add Skill</button>
        </div>
        <div style={{ marginTop: 10 }}>
          {state.skills.map((skill) => (
            <span key={skill} className="pill">
              {skill}
              <button className="btn danger" onClick={() => removeSkill(skill)}>x</button>
            </span>
          ))}
        </div>
      </div>

      <div className="panel">
        <h3 className="section-title">Job Titles & Skill Priority</h3>
        <div className="row" style={{ marginBottom: 10 }}>
          <input placeholder="Add new job title (e.g. LDM1)" value={newJobTitle} onChange={(e) => setNewJobTitle(e.target.value)} />
          <button className="btn" onClick={addJobTitle}>Add Job Title</button>
        </div>

        {state.jobTitles.map((j) => (
          <div className="card" key={j.queue}>
            <div className="row">
              <div>
                <label className="muted">Job Title</label>
                <input
                  value={j.queue}
                  onChange={(e) => {
                    const nextQueue = e.target.value.trim() || j.queue;
                    const oldQueue = j.queue;
                    if (nextQueue === oldQueue) return;
                    setState((prev) => {
                      if (prev.jobTitles.some((item) => item.queue === nextQueue)) return prev;
                      const jobTitles = prev.jobTitles.map((item) => item.queue === oldQueue ? { ...item, queue: nextQueue } : item);
                      const demandMap = new Map();
                      for (const [key, value] of prev.demandMap.entries()) {
                        const [day, slot, queue] = key.split("|");
                        const q = queue === oldQueue ? nextQueue : queue;
                        demandMap.set(`${day}|${slot}|${q}`, value);
                      }
                      return { ...prev, jobTitles, demandMap };
                    });
                  }}
                />
              </div>
              <div>
                <label className="muted">Priority Rank</label>
                <input
                  type="number"
                  min="1"
                  value={j.queue_priority}
                  onChange={(e) => updateJobTitle(j.queue, (curr) => ({ ...curr, queue_priority: Number(e.target.value) || 1 }))}
                />
              </div>
              <div style={{ display: "flex", alignItems: "end" }}>
                <button className="btn danger" onClick={() => removeJobTitle(j.queue)}>Remove Job Title</button>
              </div>
            </div>

            <div style={{ marginTop: 8 }}>
              <div className="muted">Allowed Skills</div>
              {state.skills.length === 0 && <div className="muted">No skills available</div>}
              {state.skills.map((skill) => {
                const checked = (j.allowed_roles || []).includes(skill);
                return (
                  <label key={`${j.queue}-${skill}`} className="pill">
                    <input
                      type="checkbox"
                      checked={checked}
                      onChange={(e) => {
                        updateJobTitle(j.queue, (curr) => {
                          const allowed = e.target.checked
                            ? unique([...(curr.allowed_roles || []), skill])
                            : (curr.allowed_roles || []).filter((r) => r !== skill);
                          const priority = e.target.checked
                            ? unique(curr.priority_roles || [])
                            : (curr.priority_roles || []).filter((r) => r !== skill);
                          return { ...curr, allowed_roles: allowed, priority_roles: priority };
                        });
                      }}
                    />
                    {skill}
                  </label>
                );
              })}
            </div>

            <div style={{ marginTop: 8 }}>
              <div className="muted">Priority Order</div>
              {(j.allowed_roles || []).filter((skill) => !(j.priority_roles || []).includes(skill)).map((skill) => (
                <span key={`${j.queue}-add-priority-${skill}`} className="pill">
                  {skill}
                  <button
                    className="btn"
                    onClick={() => updateJobTitle(j.queue, (curr) => ({ ...curr, priority_roles: unique([...(curr.priority_roles || []), skill]) }))}
                  >
                    Add to Priority
                  </button>
                </span>
              ))}
              {(j.priority_roles || []).filter((skill) => (j.allowed_roles || []).includes(skill)).map((skill, idx, arr) => (
                <span key={`${j.queue}-priority-${skill}`} className="pill">
                  {idx + 1}. {skill}
                  <button
                    className="btn"
                    disabled={idx === 0}
                    onClick={() => updateJobTitle(j.queue, (curr) => {
                      const list = [...(curr.priority_roles || [])].filter((s) => (curr.allowed_roles || []).includes(s));
                      if (idx === 0) return curr;
                      [list[idx - 1], list[idx]] = [list[idx], list[idx - 1]];
                      return { ...curr, priority_roles: list };
                    })}
                  >↑</button>
                  <button
                    className="btn"
                    disabled={idx === arr.length - 1}
                    onClick={() => updateJobTitle(j.queue, (curr) => {
                      const list = [...(curr.priority_roles || [])].filter((s) => (curr.allowed_roles || []).includes(s));
                      if (idx >= list.length - 1) return curr;
                      [list[idx], list[idx + 1]] = [list[idx + 1], list[idx]];
                      return { ...curr, priority_roles: list };
                    })}
                  >↓</button>
                </span>
              ))}
            </div>
          </div>
        ))}
      </div>

      <div className="panel">
        <h3 className="section-title">Requirement Matrix (Day × Slot × Job Title)</h3>
        <div className="day-tabs">
          {DAYS.map((day) => (
            <button
              key={day}
              className={`btn ${activeDay === day ? "active" : ""}`}
              onClick={() => setActiveDay(day)}
            >
              {day.toUpperCase()}
            </button>
          ))}
        </div>
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Slot</th>
                {state.jobTitles.map((j) => <th key={`head-${j.queue}`}>{j.queue}</th>)}
              </tr>
            </thead>
            <tbody>
              {slotOptions.map((slotInfo) => (
                <tr key={`row-${slotInfo.slot}`}>
                  <td>{slotInfo.label}</td>
                  {state.jobTitles.map((j) => {
                    const value = state.demandMap.get(`${activeDay}|${slotInfo.slot}|${j.queue}`) || 0;
                    return (
                      <td key={`${activeDay}-${slotInfo.slot}-${j.queue}`}>
                        <input
                          type="number"
                          min="0"
                          value={value}
                          onChange={(e) => updateDemand(activeDay, slotInfo.slot, j.queue, e.target.value)}
                        />
                      </td>
                    );
                  })}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      <div className="panel">
        <h3 className="section-title">Schedule Grid</h3>
        {!result && <div className="muted">Generate a schedule to view assignments and conflicts.</div>}
        {result && (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Day</th>
                  <th>Slot</th>
                  <th>Assignments (drag to swap queues)</th>
                </tr>
              </thead>
              <tbody>
                {result.days.map((day) => result.slots.map((slotInfo) => {
                  const slot = String(slotInfo.slot);
                  const items = ((result.grid[day] || {})[slot] || []);
                  return (
                    <tr key={`${day}-${slot}`}>
                      <td>{day.toUpperCase()}</td>
                      <td>{slotInfo.label}</td>
                      <td
                        className="dropzone"
                        onDragOver={(e) => e.preventDefault()}
                        onDrop={async (e) => {
                          if (!dragPayload) return;
                          const targetBadge = e.target.closest("[data-queue]");
                          const targetQueue = targetBadge ? targetBadge.getAttribute("data-queue") : null;
                          try {
                            if (dragPayload.day !== day || dragPayload.slot !== Number(slot)) {
                              setMessage("Swaps are only allowed within the same day and slot.");
                              return;
                            }
                            if (!targetQueue || targetQueue === dragPayload.queue) {
                              setMessage("Drop onto a different queue badge to swap.");
                              return;
                            }
                            await swap(dragPayload.day, dragPayload.slot, dragPayload.queue, targetQueue);
                          } catch (err) {
                            setMessage(err.message || "Swap failed");
                          } finally {
                            setDragPayload(null);
                          }
                        }}
                      >
                        {items.map((a) => (
                          <span
                            key={`${day}-${slot}-${a.queue}-${a.person_id}`}
                            className="badge"
                            data-queue={a.queue}
                            draggable
                            onDragStart={() => setDragPayload({ day, slot: Number(slot), queue: a.queue })}
                          >
                            {a.queue}: {a.person_id}
                          </span>
                        ))}
                      </td>
                    </tr>
                  );
                }))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      <div className="panel">
        <h3 className="section-title">Conflicts</h3>
        <pre>{JSON.stringify(result?.conflicts || [], null, 2)}</pre>
      </div>
    </>
  );
}

ReactDOM.createRoot(document.getElementById("app")).render(<App />);
