# Career Fair Scheduling System — Testing & Fix Plan

> **Audit date:** 2026-02-19  
> **Purpose:** Verify every implemented feature end-to-end, document all bugs found via static code audit, define test cases per feature, and specify the exact fix for each bug before implementation begins.

---

## 1. Audit Summary

| Feature | Data Model | Scheduler | Backend API | Frontend UI | End-to-End | Verdict |
|---|:---:|:---:|:---:|:---:|:---:|:---:|
| Ph0 — Checkpoint | — | — | ✅ | ✅ | ⚠️ Bug #3 | Mostly works |
| Ph0 — Restore | — | — | ✅ | ✅ | ✅ | ✅ Working |
| Ph1a — Panel job roles | ✅ | ✅ | ❌ Bug #1 | ✅ | ❌ | Broken |
| Ph1b — Variable durations | ✅ | ✅ | ❌ Bug #1 | ✅ | ❌ | Broken |
| Ph1c — Availability window | ✅ | ✅ | ⚠️ Bug #2 | ✅ | ⚠️ | Saves, wrong toast |
| Ph1d — Walk-in reservation | ✅ | ✅ | ❌ Bug #1 | ✅ | ❌ | Broken |
| Ph2a — panel_id on interviews | ✅ | ✅ | ✅ | ✅ | ⚠️ | Placeholder IDs only |
| Ph2b — Multi-slot blocking | — | ✅ | — | — | ⚠️ | Always 1 slot (no panels configured) |
| Ph2c — Avail window in solver | — | ✅ | — | — | ✅ | Working |
| Ph2d — Reserved walk-in slots | — | ✅ | — | — | ⚠️ | Always 0 (no panels configured) |
| Ph2e — Priority-weighted obj. | — | ✅ | — | — | ✅ | Working |
| Ph3 — Interview status API | ✅ | — | ✅ | ⚠️ Bug #4 | ⚠️ | In-Progress unreachable from UI |
| Ph3 — Live Queue display | — | — | ✅ | ✅ | ✅ | Working |
| Ph5 — Company-level breaks | ✅ | ✅ | ✅ | ❌ Gap #1 | ❌ | No UI to configure |
| Ph5 — Panel-level break override | ✅ | ✅ | ❌ Bug #1 | ⚠️ Bug #6 | ❌ | Broken (saves lost) |
| Ph5 — Multi-panel staggered breaks | ✅ | ✅ | ❌ Bug #1 | ⚠️ Bug #5/6 | ❌ | Logic correct, blocked by Bug #1 |

---

## 2. Confirmed Bugs

### Bug #1 — `POST /api/company/{id}/panels` has no server handler
**Severity:** 🔴 Critical  
**File:** `server.py`  
**Root cause:** The JavaScript `savePanels()` function posts all panel data to `/api/company/{id}/panels`. No `elif` block in `handle_api_post()` matches paths ending in `/panels`. The request falls through to the default `send_json({"status": "success"})` without writing anything.  
**Effect:** Every panel save (`saveSinglePanel`, `deletePanelById`, `addPanel`) is silently discarded. All panel configuration is lost. This single bug makes Phases 1a, 1b, 1d, and Phase 5 panel-level breaks completely non-functional end-to-end.  
**Fix:** Add a new `elif` block matching `.startswith('/api/company/') and .endswith('/panels')` in `handle_api_post()`. Read body as list of panel dicts, construct `Panel` objects, call `dm.save_company()`.

---

### Bug #2 — Double body-read in `/settings` handler causes error toast on every save
**Severity:** 🔴 Critical  
**File:** `server.py` ~lines 660–683  
**Root cause:** Inside the `elif ... endswith('/settings')` block, a dangling orphan block (no `elif`/`if`) immediately follows. It runs unconditionally after the settings logic. It calls `self.rfile.read(content_length)` on an already-consumed HTTP body, receives empty bytes `b''`, and `json.loads(b'')` raises `JSONDecodeError`. This is caught and sets `response_data["status"] = "error"`.  
**Effect:** Availability window settings ARE correctly written to disk, but the client always receives an error response and shows "Error: …" toast. Users believe saves are failing when they are not.  
**Fix:** Delete the entire orphan block (~13 lines). The `/settings` handler already handles panels via `if "panels" in body` — no separate block is needed.

---

### Bug #3 — `/api/run-schedule` clobbers `config.json`, erasing checkpoint timestamp
**Severity:** 🟡 Medium  
**File:** `server.py` ~line 581  
**Root cause:**
```python
# Current (broken):
with open(config_path, 'w') as f:
    json.dump({"event_date": event_date}, f)
```
This overwrites the entire file with only `event_date`, deleting `last_checkpoint`.  
**Effect:** After every "Run Auto-Schedule" click, the checkpoint label in the Admin Panel resets to "No checkpoint yet." Checkpoint history is permanently lost after every scheduling run.  
**Fix:** Read-merge-write pattern:
```python
cfg = {}
if os.path.exists(config_path):
    with open(config_path, 'r') as f:
        try: cfg = json.load(f)
        except Exception: cfg = {}
cfg["event_date"] = event_date
with open(config_path, 'w') as f:
    json.dump(cfg, f, indent=2)
```

---

### Bug #4 — "Mark In Progress" button missing from Live Queue
**Severity:** 🟠 Low-Medium  
**File:** `web/index.html`  
**Root cause:** No `markInProgress(id)` JavaScript function exists. No "🔄 In Progress" button is rendered in `renderLiveQueue()`. The `POST /api/interview/{id}/in-progress` backend endpoint is fully implemented but unreachable from the UI.  
**Effect:** Interviewers cannot mark an interview as "In Progress." The in-progress state (which keeps an interview as "current" even after its time window passes) is inaccessible from the dashboard.  
**Fix:** Add `async function markInProgress(id)` calling `POST /api/interview/${id}/in-progress`. Render a `🔄 In Progress` button in the action row of `lq-current` and `lq-previous` rows (show only when status is not already `in_progress`).

---

### Bug #5 — No way to express "panel has no break" when company has a break (Design Gap)
**Severity:** 🟡 Medium  
**File:** `schedule_manager/scheduler.py` line 125  
**Root cause:**
```python
if p.breaks:   # Only overrides when panel.breaks is non-empty
    active_breaks = p.breaks
```
An empty `panel.breaks = []` is falsy — it always means "inherit company breaks." There is no sentinel to express "this panel intentionally has NO break window."  
**Effect:** Scenario: Company has `breaks: [{start:"12:00", end:"13:00"}]`. Panel B is intended to continue interviews during that hour to handle walk-ins. It is impossible — leaving `panel.breaks = []` causes Panel B to also exclude 12:00–13:00 slots.  
**Current behaviour documented as known limitation.** Future fix: add `panel.override_company_break: bool = False` field, or instruct users to configure all breaks at panel level and leave company break empty.

---

### Bug #6 — Panel break UI only supports one break; any second break is silently lost
**Severity:** 🟠 Low-Medium  
**File:** `web/index.html` ~line 1815  
**Root cause:** The panel editor renders only one break row (`panel.breaks[0]`). `saveSinglePanel()` always writes back at most one break: `panel.breaks = (bs && be) ? [{start:bs, end:be}] : []`. The `Panel` dataclass supports `List[dict]`.  
**Effect:** If a panel has two break windows (e.g. 10:00–10:15 tea and 13:00–14:00 lunch), only one can be set via UI. Any second break configured programmatically is destroyed the next time the panel is saved from the UI.  
**Current mitigation:** Add a tooltip noting single-break limitation. Full multi-break UI is future work.

---

## 3. Identified Gaps

### Gap #1 — No UI for company-level breaks
**File:** `web/index.html`, `server.py`  
**Detail:** The Company Settings section has inputs for `availability_start`/`end` only. No time inputs for `company.breaks`. `saveCompanySettings()` also omits `breaks` from its POST body. The backend `/settings` handler already reads `body.get('breaks', ...)` — the only missing piece is UI + payload.  
**Fix:** Add two `<input type="time">` fields in the Company Settings section (`id="detail-break-start"` and `id="detail-break-end"`). Update `openCompanyDetail()` to populate them. Update `saveCompanySettings()` to include `breaks` in the POST body.

### Gap #2 — `self.BASE_DURATION` reference in scheduler fallback
**File:** `schedule_manager/scheduler.py` line 83  
**Detail:** `dur = role.duration_minutes if role else self.BASE_DURATION` — `self.BASE_DURATION` does not exist as a class attribute. `BASE_DURATION = 30` is a local variable inside `run()`. Would raise `AttributeError` if both `pinfo` and `role` lookups fail simultaneously.  
**Fix:** Replace `self.BASE_DURATION` with `BASE_DURATION`.

---

## 4. Multi-Panel Staggered Break Analysis

The scheduler logic is **mathematically correct** for staggered breaks. Each application builds its own `break_intervals` independently based on its assigned panel:

| Panel | Break configured | Slots excluded |
|---|---|---|
| Panel A | `{start:"12:00", end:"13:00"}` | 12:00 and 12:30 slots |
| Panel B | `{start:"13:00", end:"14:00"}` | 13:00 and 13:30 slots |

- Panel B applications **can** be assigned 12:00 (not blocked by Panel A's break) ✅  
- Panel A applications **can** be assigned 13:00 (not blocked by Panel B's break) ✅  
- Student assigned to both panels will not be double-booked (Constraint C2 enforces this independently) ✅  

The multi-panel break logic is blocked end-to-end only by **Bug #1** (panels never save to disk). Once Bug #1 is fixed, staggered breaks work automatically.

**Edge case — Bug #5 applies here:**  
If company has `breaks: [{12:00–13:00}]` and you want Panel B to run during that hour, it is impossible with `panel.breaks = []` (inherits). Users must instead: leave company break empty, and configure each panel's break individually.

---

## 5. Fix Implementation Order

| Order | ID | File | Description |
|---|---|---|---|
| 1 | B2 | `server.py` | Delete orphan block inside `/settings` handler |
| 2 | B1 | `server.py` | Add proper `elif` handler for `POST .../panels` |
| 3 | B3 | `server.py` | Change config write to read-merge-write |
| 4 | B4 | `web/index.html` | Add `markInProgress()` + 🔄 button in Live Queue |
| 5 | G1 | `web/index.html` | Add break inputs to Company Settings + update `saveCompanySettings()` + populate on `openCompanyDetail()` |
| 6 | G2 | `scheduler.py` | Fix `self.BASE_DURATION` → `BASE_DURATION` |
| 7 | B5 | `web/index.html` | Add tooltip documenting single-break limitation and inheritance behaviour |
| 8 | B6 | `web/index.html` | Add note in panel break row UI |

---

## 6. Test Cases (`test_all_features.py`)

All tests use direct Python object/file manipulation (no HTTP server required).  
Each class uses `setUp` to copy data files to temp copies and `tearDown` to restore them.

---

### Class `TestPhase0_Backup`

| Test ID | Setup | Action | Expected Result |
|---|---|---|---|
| `test_checkpoint_creates_all_backup_files` | Fresh data dir | Call checkpoint handler | All 3 `.backup.json` files exist |
| `test_checkpoint_saves_timestamp` | Fresh `config.json` | Call checkpoint | `config.json["last_checkpoint"]` is a valid datetime string |
| `test_checkpoint_info_returns_correct_data` | Backups exist | GET `/api/checkpoint-info` | Returns `last_checkpoint` + all 3 `backups_exist = True` |
| `test_checkpoint_info_missing_backups` | No backup files | GET `/api/checkpoint-info` | Returns `backups_exist` all `False` |

---

### Class `TestPhase0_Restore`

| Test ID | Setup | Action | Expected Result |
|---|---|---|---|
| `test_restore_copies_backup_to_working` | Checkpoint taken, then working files corrupted | POST `/api/restore` | Working files match original content |
| `test_restore_returns_checkpoint_timestamp` | Checkpoint taken at T1 | Run schedule (B3 fix), then restore | Response contains T1 timestamp |
| `test_run_schedule_preserves_checkpoint` | Checkpoint taken first | Run schedule | `config.json` still contains `last_checkpoint` key (B3 fix verification) |

---

### Class `TestPhase1a_PanelJobRoles`

| Test ID | Setup | Action | Expected Result |
|---|---|---|---|
| `test_panel_save_persists_to_disk` | Company with `panels: []` | POST `/panels` with one panel (`job_role_ids=["role1"]`) | Reload → panel with `job_role_ids == ["role1"]` |
| `test_panel_reload_roundtrip` | Save panel via POST | `dm.load_companies()` | Panel object with correct `job_role_ids` returned |
| `test_multi_panel_different_roles` | Two panels, different roles | Save both, reload | Each panel has its own distinct `job_role_ids` |
| `test_settings_save_returns_success_toast` | Company exists | POST `/settings` with availability times | Response `status == "success"` (B2 fix verification) |

---

### Class `TestPhase1b_VariableDurations`

| Test ID | Setup | Action | Expected Result |
|---|---|---|---|
| `test_panel_duration_45_used_by_scheduler` | Company with 1 panel (`slot_duration_minutes=45`), 1 application | Run scheduler | Interview duration == 45 min |
| `test_panel_duration_60_blocks_two_slots` | Panel with 60-min duration, 2 applications for same panel | Run scheduler | The two interviews are not at adjacent slots (each occupies 2 base slots) |
| `test_default_duration_30_if_no_panel` | Company with no panels, role `duration_minutes=30` | Run scheduler | Interviews are 30 min |

---

### Class `TestPhase1c_AvailabilityWindow`

| Test ID | Setup | Action | Expected Result |
|---|---|---|---|
| `test_no_interview_before_window_start` | Company `availability_start=13:00` | Run scheduler | No interview `start_time < 13:00` |
| `test_no_interview_after_window_end` | Company `availability_end=12:00` | Run scheduler | No interview `end_time > 12:00` |
| `test_default_window_09_to_17` | Default company | Run scheduler | All interviews within 09:00–17:00 |
| `test_settings_save_persists_window` | Default company | POST `/settings` with `availability_start=10:00, end=15:00` | Reload → `availability_start=="10:00"` |

---

### Class `TestPhase1d_WalkinReservation`

| Test ID | Setup | Action | Expected Result |
|---|---|---|---|
| `test_reserved_2_slots_leaves_last_2_empty` | Panel `reserved_walkin_slots=2`, enough apps to fill day | Run scheduler | Slots 16:00 and 16:30 have no interviews for that panel |
| `test_reserved_0_fills_all_slots` | Panel `reserved_walkin_slots=0` | Run scheduler | 16:00 and 16:30 CAN have interviews |
| `test_reserved_exceeds_available_returns_zero` | Panel `reserved_walkin_slots=20` | Run scheduler | No crash; 0 interviews scheduled for that panel |

---

### Class `TestPhase2a_PanelIdOnInterviews`

| Test ID | Setup | Action | Expected Result |
|---|---|---|---|
| `test_all_interviews_have_panel_id` | Company with panels configured | Run scheduler | Every `Interview.panel_id` not empty and not `"default"` |
| `test_panel_id_matches_defined_panel` | Company with panel `panel_id="company-P1"` | Run scheduler | All company interviews have `panel_id == "company-P1"` |
| `test_panel_id_written_to_schedule_json` | Run scheduler | Read `schedule.json` | Every entry has `"panel_id"` key present |

---

### Class `TestPhase2b_MultiSlotBlocking`

| Test ID | Setup | Action | Expected Result |
|---|---|---|---|
| `test_45min_no_overlap_same_panel` | Panel 45-min duration, 2 apps for same panel | Run scheduler | Assigned slots are ≥ 2 base slots apart, or only 1 scheduled |
| `test_45min_student_no_double_book` | Student has two 45-min apps at different companies | Run scheduler | Two interviews do not overlap in wall-clock time |
| `test_slots_needed_calculation` | `dur=45, BASE_DURATION=30` | `math.ceil(45/30)` | Returns `2` |

---

### Class `TestPhase2c_AvailConstraint`

| Test ID | Setup | Action | Expected Result |
|---|---|---|---|
| `test_interview_does_not_exceed_avail_end` | Company `availability_end=12:00`, 30-min slots | Run scheduler | No `end_time > 12:00` |
| `test_45min_excluded_at_boundary` | Company `availability_end=11:30`, 45-min panel | Run scheduler | No interview starting at 11:00 (would end 11:45, exceeds window) |

---

### Class `TestPhase2d_ReservedConstraint`

| Test ID | Setup | Action | Expected Result |
|---|---|---|---|
| `test_reserved_slot_at_end_of_default_window` | Panel 09:00–17:00, `reserved_walkin_slots=1` | Run scheduler | Slot 16:30 has no panel interview |
| `test_reserved_with_custom_window` | Panel 09:00–12:00, `reserved_walkin_slots=1` | Run scheduler | Slot 11:30 has no interview |

---

### Class `TestPhase2e_PriorityWeights`

| Test ID | Setup | Action | Expected Result |
|---|---|---|---|
| `test_shortlisted_scheduled_over_applied` | 2 students for same slot: SHORTLISTED vs APPLIED, capacity=1 | Run scheduler | SHORTLISTED student is scheduled |
| `test_priority_1_wins_over_priority_5` | 2 students for same slot: priority 1 vs 5, capacity=1 | Run scheduler | Priority 1 student is scheduled |
| `test_objective_is_positive` | Any valid dataset | Run scheduler | `solver.ObjectiveValue() > 0` |

---

### Class `TestPhase3_StatusTracking`

| Test ID | Setup | Action | Expected Result |
|---|---|---|---|
| `test_mark_complete_updates_json` | `schedule.json` with one interview `status=scheduled` | POST `…/complete` | `schedule.json` has `status=completed` for that ID |
| `test_mark_cancel_updates_json` | Same | POST `…/cancel` | `status=cancelled` |
| `test_mark_in_progress_updates_json` | Same | POST `…/in-progress` | `status=in_progress` |
| `test_new_interviews_default_scheduled` | Run scheduler | Read `schedule.json` | All `"status": "scheduled"` |
| `test_invalid_id_returns_error` | Nonexistent ID | POST to complete endpoint | Response `status == "error"` |

---

### Class `TestPhase3_LiveQueue`

| Test ID | Setup | Action | Expected Result |
|---|---|---|---|
| `test_current_by_time` | Interview 09:00–09:30, `now=09:15` | GET `/api/live-queue` | Company shows `current` with that interview |
| `test_previous_is_most_recent_past` | Interviews at 09:00 and 09:30, `now=10:00` | GET `/api/live-queue` | `previous` is the 09:30 interview |
| `test_in_progress_overrides_time` | Interview 09:00 `status=in_progress`, `now=10:00` | GET `/api/live-queue` | That interview is still `current` |
| `test_cancelled_excluded` | Interview `status=cancelled` | GET `/api/live-queue` | Not in `current`, `next`, or `previous` |
| `test_panels_grouped_correctly` | Two interviews with different `panel_id` | GET `/api/live-queue` | Company has two panels, each with own queue |

---

### Class `TestPhase5_CompanyBreaks`

| Test ID | Setup | Action | Expected Result |
|---|---|---|---|
| `test_break_slots_excluded` | Company `breaks=[{start:"12:00", end:"13:00"}]` | Run scheduler | No interview starts at 12:00 or 12:30 for any company panel |
| `test_slot_before_break_allowed` | Company break 12:00–13:00, 30-min slots | Run scheduler | Interview CAN be at 11:30 (ends exactly at 12:00, no overlap) |
| `test_slot_after_break_allowed` | Same | Run scheduler | Interview CAN be at 13:00 (starts at break end) |
| `test_settings_save_persists_break` | POST `/settings` with `breaks=[{start:"12:00",end:"13:00"}]` | Reload company | `company.breaks == [{start:"12:00",end:"13:00"}]` |

---

### Class `TestPhase5_PanelBreaks`

| Test ID | Setup | Action | Expected Result |
|---|---|---|---|
| `test_panel_break_overrides_company` | Company break 12:00–13:00; Panel A break 13:00–14:00 | Run scheduler | Panel A apps CAN be at 12:00; cannot be at 13:00 |
| `test_panel_break_empty_inherits_company` | Company break 12:00–13:00; Panel B `breaks=[]` | Run scheduler | Panel B also has no interviews 12:00–13:00 (inherited) |
| `test_panel_break_save_persists` | POST `/panels` with breaks set | Reload via `dm.load_companies()` | Panel `breaks` field has correct value |

---

### Class `TestPhase5_MultiPanelStaggeredBreaks`

> Tests the scenario where Panel A breaks 12:00–13:00 and Panel B breaks 13:00–14:00.

| Test ID | Setup | Action | Expected Result |
|---|---|---|---|
| `test_panel_a_excluded_12_to_13` | PA break 12–13, PB break 13–14 | Run scheduler | PA has no interviews 12:00–13:00 |
| `test_panel_b_excluded_13_to_14` | Same | Run scheduler | PB has no interviews 13:00–14:00 |
| `test_panel_b_can_interview_during_panel_a_break` | Same | Run scheduler | PB CAN have interviews at 12:00 (not blocked by PA's break) |
| `test_panel_a_can_interview_during_panel_b_break` | Same | Run scheduler | PA CAN have interviews at 13:00 (not blocked by PB's break) |
| `test_staggered_breaks_no_student_double_book` | Student has app to PA and PB | Run scheduler | Both interviews scheduled, no wall-clock overlap |
| `test_design_gap_bug5_documented` | Company break 12:00–13:00; Panel C `breaks=[]` | Run scheduler | Panel C ALSO excludes 12:00–13:00 (inherited — documents Bug #5 known limitation) |

---

## 7. Running the Tests

```bash
# Activate virtual environment
.\venv\Scripts\activate   # Windows

# Run all tests
python -m pytest test_all_features.py -v

# Run a specific phase
python -m pytest test_all_features.py -v -k "TestPhase5"

# Run with stdout output (useful to see scheduler messages)
python -m pytest test_all_features.py -v -s
```

### Expected results after all fixes applied

- All tests except `test_design_gap_bug5_documented` should **pass**.
- `TestPhase5_MultiPanelStaggeredBreaks.test_design_gap_bug5_documented` is **expected to fail** by design — it documents Bug #5 as a known limitation until sentinel logic is added.
- Tests in `TestPhase2b` and `TestPhase2d` will only produce meaningful results after Bug #1 is fixed and panels are persisted.

---

## 8. Bug #5 — Detailed Multi-Panel Break Design Gap

The current scheduler uses `if p.breaks:` (Python truthiness) to decide whether a panel overrides the company break. This conflates two distinct states:

| `panel.breaks` value | Intended meaning | Actual scheduler behaviour |
|---|---|---|
| `[]` (empty list) | "Not configured, inherit company break" | Inherits company break ✓ |
| `[{start:"13:00",end:"14:00"}]` | "This panel has a custom break" | Uses panel break ✓ |
| `[]` but user wants "no break" | "This panel should work during company break hour" | Incorrectly inherits company break ✗ |

**Recommended future fix:** Add `panel.override_no_break: bool = False` to `Panel` dataclass. When `True`, set `active_breaks = []` regardless of company config. Update panel editor to show a "No break for this panel" checkbox.

---

## 9. Bug #6 — Single Break per Panel UI Limitation

The `Panel` dataclass and `companies.json` support `breaks: List[dict]` (arbitrary number of break windows). The panel editor only reads/writes `panel.breaks[0]`. Any additional break entries are invisible in the UI and are **deleted** on the next save.

**Recommended future fix:** Replace the single break row in `renderPanelCard()` with a dynamic list:
- `+ Add Break Window` button appends a new `{start, end}` row
- Each row has a `✕ Remove` button
- `saveSinglePanel()` collects all rows into `panel.breaks = [{start, end}, …]`

---

*End of Testing Plan — v1.0 | 2026-02-19*
