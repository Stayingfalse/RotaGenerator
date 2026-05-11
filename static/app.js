const { useMemo, useState, useRef, useEffect } = React;

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
  return Object.fromEntries(
    DAYS.map((day) => [day, Array.from({ length: SLOT_COUNT }, (_, i) => i)]),
  );
}

function normalizeConfig(raw) {
  const people = (raw.people || []).map((p) => ({
    person_id: String(p.person_id || ""),
    name: String(p.name || ""),
    account: String(p.account || ""),
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

  const rolePool = unique([
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
    roles: rolePool,
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
      account: String(p.account || ""),
      roles: unique(p.roles || []),
      default_availability: p.default_availability || fullAvailability(),
      target_hours: p.target_hours === "" || Number.isNaN(Number(p.target_hours)) ? null : Number(p.target_hours),
    })),
    queue_rules: state.jobTitles.map((q) => ({
      queue: q.queue,
      queue_priority: Number(q.queue_priority) || 100,
      allowed_roles: unique((q.allowed_roles || []).filter((r) => state.roles.includes(r))),
      priority_roles: unique((q.priority_roles || []).filter((r) => (q.allowed_roles || []).includes(r))),
    })),
    demand,
    overrides: state.overrides || [],
    holidays: state.holidays || [],
    fairness: state.fairness || [],
    config: state.config || {},
  };
}

// ---- Availability Editor Component ----
function AvailabilityEditor({ person, overrides, onChange, onOverridesChange }) {
  const [activeTab, setActiveTab] = useState("default");
  const [activeDay, setActiveDay] = useState("mon");

  const slots = useMemo(() => Array.from({ length: SLOT_COUNT }, (_, i) => i), []);

  const defaultForDay = (day) => new Set((person.default_availability || {})[day] || []);

  const toggleDefaultSlot = (day, slot) => {
    const next = new Set(defaultForDay(day));
    if (next.has(slot)) next.delete(slot); else next.add(slot);
    onChange({ ...person, default_availability: { ...(person.default_availability || {}), [day]: [...next] } });
  };

  const setDayAll = (day, value) => {
    onChange({ ...person, default_availability: { ...(person.default_availability || {}), [day]: value ? slots.slice() : [] } });
  };

  const personOverrides = overrides.filter((o) => o.person_id === person.person_id);
  const getOverride = (day) => personOverrides.find((o) => o.day === day);

  const setOverrideSlots = (day, slotSet) => {
    const next = overrides.filter((o) => !(o.person_id === person.person_id && o.day === day));
    next.push({ person_id: person.person_id, day, available_slots: [...slotSet] });
    onOverridesChange(next);
  };

  const removeOverride = (day) => {
    onOverridesChange(overrides.filter((o) => !(o.person_id === person.person_id && o.day === day)));
  };

  const addOverride = (day) => {
    if (!getOverride(day)) setOverrideSlots(day, new Set(defaultForDay(day)));
    setActiveDay(day);
    setActiveTab("override");
  };

  const toggleOverrideSlot = (day, slot) => {
    const ov = getOverride(day);
    const current = new Set(ov ? ov.available_slots : []);
    if (current.has(slot)) current.delete(slot); else current.add(slot);
    setOverrideSlots(day, current);
  };

  const renderSlotGrid = (selectedSet, onToggle, onAll) => (
    <div>
      <div style={{ marginBottom: 6, display: "flex", gap: 8, alignItems: "center" }}>
        <button className="btn" style={{ fontSize: 11 }} onClick={() => onAll(true)}>All</button>
        <button className="btn" style={{ fontSize: 11 }} onClick={() => onAll(false)}>None</button>
        <span className="muted">{selectedSet.size}/{SLOT_COUNT} slots</span>
      </div>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: 2 }}>
        {slots.map((s) => (
          <label key={s} style={{ fontSize: 11, display: "flex", alignItems: "center", gap: 3, cursor: "pointer" }}>
            <input type="checkbox" checked={selectedSet.has(s)} onChange={() => onToggle(s)} />
            {slotLabel(s)}
          </label>
        ))}
      </div>
    </div>
  );

  return (
    <div style={{ padding: "8px 0" }}>
      <div className="day-tabs" style={{ marginBottom: 8 }}>
        <button className={`btn ${activeTab === "default" ? "active" : ""}`} onClick={() => setActiveTab("default")}>Default Availability</button>
        <button className={`btn ${activeTab === "override" ? "active" : ""}`} onClick={() => setActiveTab("override")}>
          Weekly Overrides {personOverrides.length > 0 ? `(${personOverrides.length})` : ""}
        </button>
      </div>

      {activeTab === "default" && (
        <div>
          <div className="day-tabs">
            {["mon", "tue", "wed", "thu", "fri", "sat"].map((day) => (
              <button key={day} className={`btn ${activeDay === day ? "active" : ""}`} onClick={() => setActiveDay(day)}>
                {day.toUpperCase()}
              </button>
            ))}
          </div>
          {renderSlotGrid(defaultForDay(activeDay), (s) => toggleDefaultSlot(activeDay, s), (v) => setDayAll(activeDay, v))}
        </div>
      )}

      {activeTab === "override" && (
        <div>
          <p className="muted" style={{ margin: "0 0 8px 0" }}>Overrides replace default availability for that day of the current week.</p>
          <div style={{ display: "flex", gap: 8, flexWrap: "wrap", marginBottom: 10 }}>
            {["mon", "tue", "wed", "thu", "fri", "sat"].map((day) => {
              const hasOverride = !!getOverride(day);
              return (
                <span key={day} style={{ display: "flex", gap: 4, alignItems: "center" }}>
                  <button className={`btn ${hasOverride ? "active" : ""}`} onClick={() => addOverride(day)} style={{ fontSize: 11 }}>
                    {day.toUpperCase()}{hasOverride ? " ✓" : " +"}
                  </button>
                  {hasOverride && (
                    <button className="btn danger" style={{ fontSize: 11 }} onClick={() => removeOverride(day)}>×</button>
                  )}
                </span>
              );
            })}
          </div>
          {personOverrides.length > 0 && (
            <div>
              <div className="day-tabs">
                {personOverrides.map((o) => (
                  <button key={o.day} className={`btn ${activeDay === o.day ? "active" : ""}`} onClick={() => setActiveDay(o.day)}>
                    {o.day.toUpperCase()}
                  </button>
                ))}
              </div>
              {getOverride(activeDay) && renderSlotGrid(
                new Set(getOverride(activeDay).available_slots),
                (s) => toggleOverrideSlot(activeDay, s),
                (v) => setOverrideSlots(activeDay, v ? new Set(slots) : new Set()),
              )}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function App() {
  const [state, setState] = useState(() => normalizeConfig(window.__INITIAL_CONFIG__ || {}));
  const [newRole, setNewRole] = useState("");
  const [newJobTitle, setNewJobTitle] = useState("");
  const [activeDay, setActiveDay] = useState("mon");
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState(null);
  const [dragPayload, setDragPayload] = useState(null);
  const [expandedAvail, setExpandedAvail] = useState(null);
  const csvInputRef = useRef(null);
  const saveTimerRef = useRef(null);
  const isFirstRender = useRef(true);
  const [saveStatus, setSaveStatus] = useState(""); // "" | "saving" | "saved" | "error"

  // Auto-save to server 1 second after any state change (skip the initial render)
  useEffect(() => {
    if (isFirstRender.current) {
      isFirstRender.current = false;
      return;
    }
    setSaveStatus("saving");
    clearTimeout(saveTimerRef.current);
    saveTimerRef.current = setTimeout(async () => {
      try {
        const payload = buildPayload(state);
        const res = await fetch("/config", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(payload),
        });
        if (!res.ok) throw new Error("Save failed");
        setSaveStatus("saved");
      } catch {
        setSaveStatus("error");
      }
    }, 1000);
  }, [state]);

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
        people: [...prev.people, { person_id: personId, name: `User ${n}`, account: "", roles: [], target_hours: "", default_availability: fullAvailability() }],
      };
    });
  };

  const removeUser = (personId) => {
    setState((prev) => ({
      ...prev,
      people: prev.people.filter((p) => p.person_id !== personId),
      overrides: prev.overrides.filter((o) => o.person_id !== personId),
    }));
    if (expandedAvail === personId) setExpandedAvail(null);
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
      overrides: prev.overrides.map((o) => o.person_id === personId ? { ...o, person_id: nextId } : o),
    }));
    if (expandedAvail === personId) setExpandedAvail(nextId);
  };

  const addRole = () => {
    const value = newRole.trim();
    if (!value) return;
    setState((prev) => {
      if (prev.roles.includes(value)) return prev;
      return { ...prev, roles: [...prev.roles, value].sort() };
    });
    setNewRole("");
  };

  const removeRole = (role) => {
    setState((prev) => ({
      ...prev,
      roles: prev.roles.filter((s) => s !== role),
      people: prev.people.map((p) => ({ ...p, roles: (p.roles || []).filter((r) => r !== role) })),
      jobTitles: prev.jobTitles.map((j) => ({
        ...j,
        allowed_roles: (j.allowed_roles || []).filter((r) => r !== role),
        priority_roles: (j.priority_roles || []).filter((r) => r !== role),
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
    if (state.jobTitles.length === 0) return "Add at least one queue.";
    if (state.people.some((p) => !String(p.person_id || "").trim() || !String(p.name || "").trim())) {
      return "Every user must have both an ID and name.";
    }
    if (state.jobTitles.some((j) => !String(j.queue || "").trim())) {
      return "Every queue must have a name.";
    }
    return "";
  };

  const handleCsvFile = async (e) => {
    const file = e.target.files[0];
    if (!file) return;
    const formData = new FormData();
    formData.append("file", file);
    try {
      const res = await fetch("/import-csv", { method: "POST", body: formData });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || "CSV import failed");
      setState((prev) => {
        const existingIds = new Set(prev.people.map((p) => p.person_id));
        const newPeople = [...prev.people];
        const newRoles = [...prev.roles];
        for (const imp of data) {
          if (existingIds.has(imp.person_id)) {
            const idx = newPeople.findIndex((p) => p.person_id === imp.person_id);
            newPeople[idx] = {
              ...newPeople[idx],
              name: imp.name || newPeople[idx].name,
              account: imp.account || newPeople[idx].account,
              target_hours: imp.target_hours ?? newPeople[idx].target_hours,
              roles: unique([...(newPeople[idx].roles || []), ...(imp.roles || [])]),
            };
          } else {
            newPeople.push({
              person_id: imp.person_id,
              name: imp.name || imp.person_id,
              account: imp.account || "",
              roles: imp.roles || [],
              target_hours: imp.target_hours ?? "",
              default_availability: imp.default_availability || fullAvailability(),
            });
            existingIds.add(imp.person_id);
          }
          for (const r of (imp.roles || [])) {
            if (!newRoles.includes(r)) newRoles.push(r);
          }
        }
        return { ...prev, people: newPeople, roles: newRoles.sort() };
      });
      setMessage(`Imported ${data.length} user(s) from CSV.`);
    } catch (err) {
      setMessage(err.message || "CSV import failed");
    }
    e.target.value = "";
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
        <p className="muted">Manage users, roles, queues, and the requirement matrix.</p>
        <div className="row" style={{ alignItems: "center" }}>
          <button className="btn primary" onClick={generate} disabled={busy}>{busy ? "Generating..." : "Generate Schedule"}</button>
          <a className="btn" href="/export.xlsx" target="_blank" rel="noreferrer">Export XLSX</a>
          {saveStatus === "saving" && <span className="muted" style={{ fontSize: 12 }}>⏳ Saving…</span>}
          {saveStatus === "saved" && <span style={{ color: "#15803d", fontSize: 12 }}>✓ Saved</span>}
          {saveStatus === "error" && <span style={{ color: "#b91c1c", fontSize: 12 }}>✗ Save failed</span>}
        </div>
        {message && <div className="error">{message}</div>}
      </div>

      <div className="panel">
        <h3 className="section-title">Users</h3>
        <div style={{ marginBottom: 10, display: "flex", gap: 10, flexWrap: "wrap", alignItems: "center" }}>
          <button className="btn" onClick={addUser}>Add User</button>
          <button className="btn" onClick={() => csvInputRef.current && csvInputRef.current.click()}>Import CSV</button>
          <input ref={csvInputRef} type="file" accept=".csv,text/csv" style={{ display: "none" }} onChange={handleCsvFile} />
          <span className="muted" style={{ fontSize: 11 }}>CSV columns: UserID, UserName, Account, Hours, Role</span>
        </div>
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>User ID</th>
                <th>Name</th>
                <th>Account</th>
                <th>Target Hours</th>
                <th>Assigned Roles</th>
                <th>Availability</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {state.people.map((p) => (
                <React.Fragment key={p.person_id}>
                  <tr>
                    <td><input value={p.person_id} onChange={(e) => renameUserId(p.person_id, e.target.value)} /></td>
                    <td><input value={p.name} onChange={(e) => updateUser(p.person_id, (curr) => ({ ...curr, name: e.target.value }))} /></td>
                    <td><input value={p.account || ""} placeholder="e.g. Account_A" onChange={(e) => updateUser(p.person_id, (curr) => ({ ...curr, account: e.target.value }))} /></td>
                    <td>
                      <input type="number" min="0" value={p.target_hours} onChange={(e) => updateUser(p.person_id, (curr) => ({ ...curr, target_hours: e.target.value }))} />
                    </td>
                    <td>
                      {state.roles.length === 0 && <span className="muted">Add roles first</span>}
                      {state.roles.map((role) => {
                        const checked = (p.roles || []).includes(role);
                        return (
                          <label key={`${p.person_id}-${role}`} className="pill">
                            <input
                              type="checkbox"
                              checked={checked}
                              onChange={(e) => updateUser(p.person_id, (curr) => ({
                                ...curr,
                                roles: e.target.checked
                                  ? unique([...(curr.roles || []), role])
                                  : (curr.roles || []).filter((r) => r !== role),
                              }))}
                            />
                            {role}
                          </label>
                        );
                      })}
                    </td>
                    <td>
                      <button
                        className={`btn ${expandedAvail === p.person_id ? "active" : ""}`}
                        onClick={() => setExpandedAvail(expandedAvail === p.person_id ? null : p.person_id)}
                        style={{ fontSize: 11 }}
                      >
                        {expandedAvail === p.person_id ? "Hide" : "Edit"} Availability
                      </button>
                    </td>
                    <td><button className="btn danger" onClick={() => removeUser(p.person_id)}>Remove</button></td>
                  </tr>
                  {expandedAvail === p.person_id && (
                    <tr>
                      <td colSpan={7} style={{ background: "#f9fafb", padding: "12px 16px" }}>
                        <AvailabilityEditor
                          person={p}
                          overrides={state.overrides}
                          onChange={(updated) => updateUser(p.person_id, () => updated)}
                          onOverridesChange={(newOverrides) => setState((prev) => ({ ...prev, overrides: newOverrides }))}
                        />
                      </td>
                    </tr>
                  )}
                </React.Fragment>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      <div className="panel">
        <h3 className="section-title">Roles</h3>
        <p className="muted" style={{ marginTop: 0 }}>Define the roles people can hold (e.g. TL, ASA, ICH_FW). Each queue below specifies which roles are allowed.</p>
        <div className="row">
          <input placeholder="Add new role (e.g. TL)" value={newRole} onChange={(e) => setNewRole(e.target.value)} onKeyDown={(e) => e.key === "Enter" && addRole()} />
          <button className="btn" onClick={addRole}>Add Role</button>
        </div>
        <div style={{ marginTop: 10 }}>
          {state.roles.map((role) => (
            <span key={role} className="pill">
              {role}
              <button className="btn danger" onClick={() => removeRole(role)}>x</button>
            </span>
          ))}
        </div>
      </div>

      <div className="panel">
        <h3 className="section-title">Queues & Role Priority</h3>
        <p className="muted" style={{ marginTop: 0 }}>Each queue (e.g. LDM1, LDM2, FW) specifies which roles can fill it and their assignment priority order.</p>
        <div className="row" style={{ marginBottom: 10 }}>
          <input placeholder="Add new queue (e.g. LDM1)" value={newJobTitle} onChange={(e) => setNewJobTitle(e.target.value)} onKeyDown={(e) => e.key === "Enter" && addJobTitle()} />
          <button className="btn" onClick={addJobTitle}>Add Queue</button>
        </div>

        {state.jobTitles.map((j) => (
          <div className="card" key={j.queue}>
            <div className="row">
              <div>
                <label className="muted">Queue Name</label>
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
                <input type="number" min="1" value={j.queue_priority} onChange={(e) => updateJobTitle(j.queue, (curr) => ({ ...curr, queue_priority: Number(e.target.value) || 1 }))} />
              </div>
              <div style={{ display: "flex", alignItems: "end" }}>
                <button className="btn danger" onClick={() => removeJobTitle(j.queue)}>Remove Queue</button>
              </div>
            </div>

            <div style={{ marginTop: 8 }}>
              <div className="muted">Allowed Roles</div>
              {state.roles.length === 0 && <div className="muted">No roles available — add roles above first</div>}
              {state.roles.map((role) => {
                const checked = (j.allowed_roles || []).includes(role);
                return (
                  <label key={`${j.queue}-${role}`} className="pill">
                    <input
                      type="checkbox"
                      checked={checked}
                      onChange={(e) => {
                        updateJobTitle(j.queue, (curr) => {
                          const allowed = e.target.checked
                            ? unique([...(curr.allowed_roles || []), role])
                            : (curr.allowed_roles || []).filter((r) => r !== role);
                          const priority = e.target.checked
                            ? unique(curr.priority_roles || [])
                            : (curr.priority_roles || []).filter((r) => r !== role);
                          return { ...curr, allowed_roles: allowed, priority_roles: priority };
                        });
                      }}
                    />
                    {role}
                  </label>
                );
              })}
            </div>

            <div style={{ marginTop: 8 }}>
              <div className="muted">Priority Order</div>
              {(j.allowed_roles || []).filter((role) => !(j.priority_roles || []).includes(role)).map((role) => (
                <span key={`${j.queue}-add-priority-${role}`} className="pill">
                  {role}
                  <button className="btn" onClick={() => updateJobTitle(j.queue, (curr) => ({ ...curr, priority_roles: unique([...(curr.priority_roles || []), role]) }))}>
                    Add to Priority
                  </button>
                </span>
              ))}
              {(j.priority_roles || []).filter((role) => (j.allowed_roles || []).includes(role)).map((role, idx, arr) => (
                <span key={`${j.queue}-priority-${role}`} className="pill">
                  {idx + 1}. {role}
                  <button className="btn" disabled={idx === 0}
                    onClick={() => updateJobTitle(j.queue, (curr) => {
                      const list = [...(curr.priority_roles || [])].filter((s) => (curr.allowed_roles || []).includes(s));
                      if (idx === 0) return curr;
                      [list[idx - 1], list[idx]] = [list[idx], list[idx - 1]];
                      return { ...curr, priority_roles: list };
                    })}
                  >↑</button>
                  <button className="btn" disabled={idx === arr.length - 1}
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
        <h3 className="section-title">Requirement Matrix (Day × Slot × Queue)</h3>
        <div className="day-tabs">
          {DAYS.map((day) => (
            <button key={day} className={`btn ${activeDay === day ? "active" : ""}`} onClick={() => setActiveDay(day)}>
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
                        <input type="number" min="0" value={value} onChange={(e) => updateDemand(activeDay, slotInfo.slot, j.queue, e.target.value)} />
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
                            if (!targetQueue) { setMessage("Drop onto a queue badge in the same slot to swap."); return; }
                            if (targetQueue === dragPayload.queue) { setMessage("Drop onto a different queue badge to swap."); return; }
                            await swap(dragPayload.day, dragPayload.slot, dragPayload.queue, targetQueue);
                          } catch (err) {
                            setMessage(err.message || "Swap failed");
                          } finally {
                            setDragPayload(null);
                          }
                        }}
                      >
                        {items.map((a) => (
                          <span key={`${day}-${slot}-${a.queue}-${a.person_id}`} className="badge" data-queue={a.queue} draggable onDragStart={() => setDragPayload({ day, slot: Number(slot), queue: a.queue })}>
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
