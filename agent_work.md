# Agent Work Log — Career Fair Scheduling System
**Date:** 2026-02-19  
**Project:** `e20-careerfair-scheduling` — Python HTTP server + OR-Tools CP-SAT optimizer + vanilla JS SPA

---

## Stack
- `server.py` — bare Python HTTP server, port 8000
- `schedule_manager/scheduler.py` — OR-Tools CP-SAT optimizer
- `schedule_manager/data_manager.py` — dataclasses + JSON persistence
- `web/index.html` — single-page app, 6 tabs
- Data: `schedule_manager/data/*.json`
- Venv: `.venv/`

---

## Bugs Found & Fixed

### B1 — `POST /api/company/{id}/panels` had no handler *(server.py)*
**Symptom:** Every panel save was silently discarded; panels never persisted.  
**Fix:** Added `elif` handler block for the `/panels` route, reads body, constructs `Panel` objects, calls `dm.save_company()`.

### B2 — Orphan block double-read HTTP body in `/settings` *(server.py)*
**Symptom:** Every company settings save returned a JSON error toast.  
**Fix:** Deleted the orphan `if` block (~13 lines) that called `self.rfile.read()` a second time after the main handler already consumed it.

### B3 — `run-schedule` clobbered `config.json` erasing `last_checkpoint` *(server.py)*
**Symptom:** After running the scheduler, the checkpoint timestamp disappeared.  
**Fix:** Changed from `json.dump({"event_date": ...})` to read-merge-write pattern:
```python
cfg = json.load(...) if exists else {}
cfg["event_date"] = event_date
json.dump(cfg, ...)
```

### B4 — No `markInProgress()` JS function or button in Live Queue *(index.html)*
**Symptom:** "In Progress" button was wired to a non-existent function.  
**Fix:** Added `async function markInProgress(id)` + conditional 🔄 button in queue row (only shown when `status !== 'in_progress'`).

### G1 — No company-level break UI *(index.html)*
**Symptom:** Company break times were never exposed or saveable in the UI.  
**Fix:** Added two `<input type="time">` fields (`detail-break-start`, `detail-break-end`) to company settings; wired into `openCompanyDetail()` (populate) and `saveCompanySettings()` (post).

### G2 — `self.BASE_DURATION` AttributeError *(scheduler.py)*
**Symptom:** Scheduler crash when no panel configured for a role.  
**Fix:** `self.BASE_DURATION` → `BASE_DURATION` (it's a local constant, not an instance attribute).

### C2/C3 — Duplicate indices in slot-coverage constraints *(scheduler.py)*
**Symptom:** Any panel with `slot_duration_minutes > 30` (e.g. 45 or 60 min) scheduled 0 interviews — solver found OPTIMAL but objective = 0.  
**Root cause:** `student_slot_apps` and `panel_slot_apps` used `list.append(i)`, so a single app index was added multiple times (once per valid start slot covering that base slot). The `sum(x[...]) <= 1` constraint was counting the same variable multiple times, making it impossible to satisfy.  
**Fix:** Changed from `list.append(i)` to `set.add(i)` for both dicts. Confirmed via test `test_panel_duration_45_used_by_scheduler`.

### Multi-panel "last-write-wins" — same role on multiple panels *(scheduler.py)*
**Symptom:** When 2+ panels all handle the same job role, only the last panel in the list received any students. Other panels were permanently idle.  
**Root cause:**
```python
# BEFORE — single dict, each panel overwrites the previous
panel_for_role[(c.id, rid)] = panel.panel_id
```
**Fix:** Changed to multi-valued mapping + expanded `valid_apps` to one entry per `(student × panel)`:
```python
panels_for_role[(c.id, rid)].append(panel.panel_id)  # list, not scalar
```
Added `C_GROUP` OR-Tools constraint: each student scheduled at most once per `(company, role)` across all panels.

### Company Timeline blank *(index.html — renderMasterCompanies)*
**Symptom:** Company Timeline tab showed "No interviews" for every company.  
**Root cause:** Fallback panel used `panel_id: 'default'`, but scheduler assigns `{company_id}-P0`. Zero matches.  
**Fix:** Fallback now uses `` panel_id: `${c.id}-P0` ``.

### Timeline cards missing details *(index.html — both timeline render functions)*
**Symptom:** Cards only showed start time and name; no end time, role title, or status.  
**Fix:** Both `renderMasterStudents()` and `renderMasterCompanies()` updated to show `start–end` range, role title, and uppercase status label when not `scheduled`.

---

## Known Limitations (documented, not fixed)

| ID | Description |
|---|---|
| Bug #5 | `if p.breaks:` truthiness — impossible to express "panel has no break" when company does. Panel with `breaks=[]` always inherits company break. Needs sentinel value fix. |
| Bug #6 | Panel editor only reads/writes `panel.breaks[0]`. A second break window is silently destroyed on save. |

Both are documented with `ℹ️` tooltips in the panel editor UI.

---

## Test Suite — `test_all_features.py` (50 tests)

Run: `python -m pytest test_all_features.py -v`

| Class | Tests | What it covers |
|---|---|---|
| `TestPhase0_Backup` | 4 | Checkpoint creates backups, saves timestamp, event_date update preserves checkpoint |
| `TestPhase0_Restore` | 2 | Restore copies backup, config preserved after run-schedule |
| `TestPhase1a_PanelJobRoles` | 3 | Panel save persists, multi-panel different roles, full field roundtrip |
| `TestPhase1b_VariableDurations` | 4 | 45-min duration used, 60-min no overlap, default 30-min, `slots_needed` math |
| `TestPhase1c_AvailabilityWindow` | 4 | No interview before/after window, default 09–17, save persists |
| `TestPhase1d_WalkinReservation` | 2 | Reserved=2 blocks last 2 slots, reserved=0 fills all |
| `TestPhase2a_PanelIdOnInterviews` | 4 | All interviews have panel_id, matches defined panel, two panels produce two IDs, **same-role shared across two panels** |
| `TestPhase2b_MultiSlotBlocking` | 2 | 45-min no panel overlap, student no double-book |
| `TestPhase2e_PriorityWeights` | 3 | Shortlisted wins limited capacity, priority-1 wins, objective > 0 |
| `TestPhase3_StatusTracking` | 4 | Mark complete/cancel/in_progress, new interviews default to `scheduled` |
| `TestPhase3_LiveQueue` | 5 | Current by time, previous, in_progress overrides time, cancelled excluded, panels grouped |
| `TestPhase5_CompanyBreaks` | 4 | Break slots excluded, before+after allowed, settings persist |
| `TestPhase5_PanelBreaks` | 3 | Panel break overrides company, empty inherits, save persists |
| `TestPhase5_MultiPanelStaggeredBreaks` | 6 | Panel A/B exclusions, cross-panel availability, no student double-book, Bug #5 documented |

---

---

## CSV Import Safety — Merge Logic *(response_importer.py)*

**Problem identified:** Re-importing a CSV completely overwrote `companies.json` with fresh objects — destroying all saved panels, breaks, availability windows, and walk-in config.

**Fix:** Two-tier merge added to `response_importer.py`:
- **Existing companies** (already in `companies.json`): preserve all saved config (`panels`, `breaks`, `availability_start/end`, `walk_in_open`, `num_panels`); only merge newly seen job roles from CSV.
- **New companies** (first time in CSV): apply template defaults from `company_defaults.json` (see below).

---

## Company Defaults Template System

**Motivation:** The merge-only approach still leaves new companies with bare config on first import. A template file ensures any new company gets a consistent, pre-configured starting point.

### New file: `schedule_manager/data/company_defaults.json`
```json
{
  "availability_start": "09:00",
  "availability_end": "17:00",
  "breaks": [],
  "default_panel": {
    "label": "Panel 1 (Default)",
    "slot_duration_minutes": 30,
    "reserved_walkin_slots": 0,
    "walk_in_open": false,
    "breaks": []
  }
}
```

### `response_importer.py` — template-aware new-company init
When a company appears for the first time in a CSV import:
```python
company.availability_start = defaults.get("availability_start", "09:00")
company.availability_end   = defaults.get("availability_end",   "17:00")
company.breaks             = [Break(**b) for b in defaults.get("breaks", [])]
dp = defaults.get("default_panel", {})
company.panels = [Panel(
    panel_id=f"{company.id}-P1",
    label=dp.get("label", "Panel 1 (Default)"),
    job_role_ids=[r.id for r in company.job_roles],
    slot_duration_minutes=dp.get("slot_duration_minutes", 30),
    reserved_walkin_slots=dp.get("reserved_walkin_slots", 0),
    walk_in_open=dp.get("walk_in_open", False),
    breaks=[]
)]
```

### `server.py` — two new endpoints
- **`GET /api/company-defaults`** — reads `company_defaults.json`, returns JSON (falls back to hardcoded defaults if file missing).
- **`POST /api/company-defaults`** — accepts JSON body, writes to `company_defaults.json`.

### `web/index.html` — Admin tab UI card
Added `<details id="company-defaults-panel">` card in admin tab with fields:
- `def-avail-start`, `def-avail-end` — default interview availability window
- `def-break-start`, `def-break-end` — default break time
- `def-panel-label` — default panel label
- `def-slot-duration` — slot duration (minutes)
- `def-reserved` — reserved walk-in slots

**JS functions added:**
- `loadCompanyDefaults()` — fetches `/api/company-defaults` and populates all fields; called automatically when admin tab is opened (wired into `switchTab('admin')`).
- `saveCompanyDefaults()` — POSTs form values to `/api/company-defaults`; wired to the "💾 Save Defaults" button.

---

## Files Changed

| File | Changes |
|---|---|
| `server.py` | B1 `/panels` handler, B2 orphan block removed, B3 config merge, `GET /api/company-defaults`, `POST /api/company-defaults` |
| `schedule_manager/scheduler.py` | G2 BASE_DURATION, C2/C3 set dedup, multi-panel panels_for_role + C_GROUP constraint |
| `schedule_manager/response_importer.py` | CSV merge logic (preserve existing config), template-aware new-company init |
| `schedule_manager/data/company_defaults.json` | **Created** — default availability window, break, panel config |
| `web/index.html` | B4 markInProgress, G1 company break UI, company timeline panel_id fix, timeline card details, company-defaults admin card, `loadCompanyDefaults()`, `saveCompanyDefaults()` |
| `test_all_features.py` | Created — 50 tests |
| `TESTING_PLAN.md` | Created — audit findings + test plan |

---

## Prompts That Triggered Each Session

1. *"check all functionalities, go through code, verify them, implement testing, correct functionality based on tests, make a thorough plan and .md testing plan"*
2. *"check multiple panels with lunch breaks, add to plan if missing"*
3. *"now start by creating this .md file and execute the plan"*
4. *"company timeline is not working, student timeline not showing all required details"*
5. *"how to add panels to a company"* (explanation only)
6. *"scheduling for multiple panels is not working, check the functionality"*
7. *"write a make file named 'agent work' with time, work done, prompts, changes, errors, resolutions, tests"*
