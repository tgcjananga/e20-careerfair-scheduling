# Career Fair Scheduling System — Enhancement Roadmap

> **Current state:** Basic OR-Tools scheduler, single panel per company, fixed 30-min slots, JSON file storage, Admin Panel with walk-in toggle.

---

## Phase 0 — Data Safety Infrastructure (Do This First)

Before any new features, establish a safe data layer so you can always recover from mistakes.

### What to build
- **Backup/Restore system** for all JSON data files
- **Admin UI tools** to trigger checkpoint and restore

### Files affected
| File | Change |
|:---|:---|
| `server.py` | Add `POST /api/checkpoint` and `POST /api/restore` endpoints |
| `web/index.html` | Add Checkpoint and Restore buttons to Admin Panel |
| `schedule_manager/data/` | Add `*.backup.json` files alongside working copies |

### How it works
```
schedule_manager/data/
├── companies.json          ← working copy  (daily read/write)
├── companies.backup.json   ← permanent backup (updated at checkpoints)
├── students.json
├── students.backup.json
├── schedule.json
├── schedule.backup.json
└── config.json
```

**Checkpoint** (`POST /api/checkpoint`):
- Copies `companies.json` → `companies.backup.json`
- Copies `students.json` → `students.backup.json`
- Copies `schedule.json` → `schedule.backup.json`
- Records timestamp of last checkpoint in `config.json`

**Restore** (`POST /api/restore`):
- Copies `*.backup.json` → working copies
- Reloads all data in memory
- Returns what was restored and the checkpoint timestamp

**When to checkpoint:**
- After a successful CSV import
- After running and verifying the schedule
- At the start of the event day

**When to restore:**
- If wrong data was imported
- If the schedule is corrupted
- If walk-in toggles were accidentally changed

### Admin UI additions
```
[ 💾 Checkpoint ]   [ ↩ Restore from Backup ]
Last checkpoint: 2026-02-18 09:00
```

---

## Phase 1 — Richer Data Model

Extend the data structures to support per-panel roles and variable durations. **No scheduler changes yet** — just the data model.

### 1a. Per-panel job role assignment

**Current model:**
```json
{ "id": "sysco", "num_panels": 2 }
```

**New model:**
```json
{
  "id": "sysco",
  "panels": [
    { "panel_id": "sysco-P1", "label": "Panel 1", "job_role_ids": ["sysco_software_engineer"] },
    { "panel_id": "sysco-P2", "label": "Panel 2", "job_role_ids": ["sysco_devops_engineer"] }
  ]
}
```

Each panel can serve one or more job roles. A student applying for Software Engineer will only be scheduled to P1.

### 1b. Variable interview durations

**Current model:**
```json
{ "id": "aiml_role", "title": "AI/ML Engineer", "duration_minutes": 30 }
```

**New model** — already has the field, just needs to be used:
```json
{ "id": "aiml_role", "title": "AI/ML Engineer", "duration_minutes": 45 }
{ "id": "se_role",   "title": "Software Engineer", "duration_minutes": 30 }
```

### 1c. Company-specific availability windows

```json
{
  "id": "sysco",
  "availability": { "start": "10:00", "end": "15:00" }
}
```

Some companies may only be available for part of the day.

### 1d. Walk-in slot reservation per panel

```json
{
  "panel_id": "sysco-P1",
  "reserved_walkin_slots": 2
}
```

The scheduler will leave N slots unscheduled at the end of each panel's day for walk-ins.

### Files affected
| File | Change |
|:---|:---|
| `schedule_manager/data_manager.py` | Update `Company`, `Panel`, `JobRole` dataclasses |
| `schedule_manager/response_importer.py` | Map CSV data to new panel structure |
| `schedule_manager/data/companies.json` | Migrate to new format |
| `web/index.html` | Admin Panel shows per-panel info |

> **Checkpoint after Phase 1** — back up the migrated data before touching the scheduler.

---

## Phase 2 — Scheduler Enhancements

Update the OR-Tools solver to use the richer data model. Each constraint is added incrementally.

### 2a. Per-panel role assignment constraint
```
For each interview:
  student.job_role must be in panel.job_role_ids
  interview must be assigned to a valid panel
```

### 2b. Variable duration intervals
```
Each interview is an interval variable: [start, start + role.duration_minutes]
No-overlap constraint applied per panel (not per company)
```

### 2c. Company availability windows
```
For each interview at company C:
  start_time >= C.availability.start
  end_time   <= C.availability.end
```

### 2d. Walk-in slot reservation
```
For each panel P with reserved_walkin_slots = N:
  Total scheduled interviews <= (available_slots - N)
```

### 2e. Priority ordering (1st preference first)
```
Objective function weight:
  preference_rank 1 → weight 5
  preference_rank 2 → weight 3
  preference_rank 3 → weight 2
  preference_rank 4 → weight 1
  preference_rank 5 → weight 1
```

This is already partially implemented. The full version ensures that if a student can only get 2 interviews, they get their top 2 choices.

### 2f. Student travel time between booths
```
For student S with consecutive interviews at booth A then booth B:
  interview_B.start >= interview_A.end + travel_time(A, B)
```

Travel time can be a fixed constant (e.g. 5 minutes) or a matrix based on booth layout.

### Files affected
| File | Change |
|:---|:---|
| `schedule_manager/scheduler.py` | All constraint additions above |
| `server.py` | Pass new config options to scheduler |
| `web/index.html` | Show travel time config in Admin Panel |

> **Checkpoint after Phase 2** — back up after verifying the new schedule is correct.

---

## Phase 3 — Real-Time Updates

The most complex phase. Handles the live event day where interviews complete, run over, or are cancelled.

### How it works

The event day is divided into two modes:

**Pre-event (before 09:00):** Full schedule is fixed. No real-time updates needed.

**During event:** As interviews complete or are marked as done, the system re-runs the optimizer for the **remaining unstarted slots only** (rolling horizon).

### What to build

| Feature | Description |
|:---|:---|
| Interview status tracking | Each interview gets a status: `scheduled`, `in_progress`, `completed`, `cancelled` |
| Mark complete button | Admin can mark an interview as done from the panel view |
| Rolling re-schedule | When an interview is marked done or cancelled, re-run the solver for remaining slots |
| Delay handling | If an interview runs over, push subsequent interviews back and notify affected students |

### Files affected
| File | Change |
|:---|:---|
| `schedule_manager/data_manager.py` | Add `status` field to `Interview` |
| `schedule_manager/scheduler.py` | Add `reschedule_remaining(from_time)` method |
| `server.py` | Add `POST /api/complete-interview/{id}` and `POST /api/cancel-interview/{id}` |
| `web/index.html` | Live status view in Admin Panel with mark-complete buttons |

> **Checkpoint frequently during Phase 3** — real-time changes are the most likely to cause data issues.

---

## Implementation Order Summary

```
Phase 0 ──► Phase 1 ──► Phase 2a ──► Phase 2b ──► Phase 2c
  │                         │
  │                    (checkpoint)
  │
  └──► Phase 2d ──► Phase 2e ──► Phase 2f ──► Phase 3
                                                  │
                                             (checkpoint
                                              frequently)
```

| Phase | Feature | Complexity | Risk |
|:---:|:---|:---:|:---:|
| 0 | Backup/Restore | Low | Low |
| 1a | Per-panel role assignment (data model) | Low | Low |
| 1b | Variable durations (data model) | Low | Low |
| 1c | Company availability windows | Low | Low |
| 1d | Walk-in slot reservation | Low | Low |
| 2a | Per-panel constraint in scheduler | Medium | Medium |
| 2b | Variable duration intervals | Medium | Medium |
| 2c | Availability window constraints | Low | Low |
| 2d | Walk-in reservation in scheduler | Low | Low |
| 2e | Priority ordering (full) | Medium | Low |
| 2f | Travel time between booths | Medium | Medium |
| 3 | Real-time rolling reschedule | High | High |

---

## Admin Tooling Reference

| Tool | When to use |
|:---|:---|
| **📂 Load Data from CSV** | New responses received from Google Forms |
| **💾 Checkpoint** | After verifying imported data or a good schedule |
| **↩ Restore** | Data was corrupted or wrongly imported |
| **▶ Run Auto-Schedule** | Generate/regenerate the full schedule |
| **🔄 Refresh (Admin Panel)** | Manual refresh of live status |
| **Toggle Walk-in** | Open/close walk-ins per company during the event |
| *(Phase 3)* **✅ Mark Complete** | Mark an interview as done to trigger re-scheduling |
| *(Phase 3)* **❌ Cancel Interview** | Remove an interview and free the slot |

---

## Notes

- **Each phase is independently deployable.** You don't need to do Phase 3 to benefit from Phase 1 and 2.
- **OR-Tools scales well.** Even with all Phase 2 constraints active, the solver typically finds an optimal solution in under 10 seconds for a single-day career fair.
- **The backup system (Phase 0) is a prerequisite for everything else.** Always implement it first.
