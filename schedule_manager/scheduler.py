from datetime import datetime, timedelta
from typing import List, Dict, Tuple, Optional
import sys

# Try importing OR-Tools
try:
    from ortools.sat.python import cp_model
    ORTOOLS_AVAILABLE = True
except ImportError:
    ORTOOLS_AVAILABLE = False

from schedule_manager.data_manager import DataManager, Student, Company, Application, Interview, AppStatus


class Scheduler:
    def __init__(self, data_manager: DataManager):
        self.dm = data_manager
        self.students = self.dm.load_students()
        self.companies = self.dm.load_companies()
        self.interviews: List[Interview] = []

    def _hhmm_to_min(self, t: str) -> int:
        """'HH:MM' → minutes since midnight."""
        h, m = map(int, t.split(':'))
        return h * 60 + m

    def run(self, event_date: str = "2026-02-20") -> List[Interview]:
        if not ORTOOLS_AVAILABLE:
            print("ERROR: OR-Tools not installed. Please run 'pip install ortools'.")
            return []

        print(f"Starting OR-Tools optimization for {event_date}...")

        # ── 0. Load pinned configuration ─────────────────────────────────────
        import json as _json
        import os as _os
        _data_dir = _os.path.join(_os.path.dirname(__file__), 'data')
        _config_path = _os.path.join(_data_dir, 'config.json')
        pinned_company_ids: set = set()
        if _os.path.exists(_config_path):
            with open(_config_path, encoding='utf-8') as _f:
                pinned_company_ids = set(_json.load(_f).get('pinned_company_ids', []))

        # Load existing pinned interviews from schedule.json
        _sched_path = _os.path.join(_data_dir, 'schedule.json')
        pinned_interviews_raw: list = []
        if _os.path.exists(_sched_path) and pinned_company_ids:
            with open(_sched_path, encoding='utf-8') as _f:
                _raw = _json.load(_f)
            _all = _raw if isinstance(_raw, list) else _raw.get('interviews', [])
            pinned_interviews_raw = [iv for iv in _all if iv.get('pinned', False)]
        if pinned_company_ids:
            print(f"  Pinned companies (skipped by optimizer): {sorted(pinned_company_ids)}")
            print(f"  Loaded {len(pinned_interviews_raw)} pinned interviews.")

        # ── 1. Prepare lookup tables ─────────────────────────────────────────

        company_map: Dict[str, Company] = {c.id: c for c in self.companies}

        # role_map: role_id → JobRole
        role_map = {}
        for c in self.companies:
            for r in c.job_roles:
                role_map[r.id] = r

        # For each (company_id, role_id): ALL panels that handle it (may be multiple)
        # Changed from single-value to list so multiple panels can share a role
        panels_for_role: Dict[Tuple[str, str], List[str]] = {}
        for c in self.companies:
            for panel in c.panels:
                for rid in panel.job_role_ids:
                    key = (c.id, rid)
                    if key not in panels_for_role:
                        panels_for_role[key] = []
                    panels_for_role[key].append(panel.panel_id)

        # panel_info: (company_id, panel_id) → {duration, reserved_walkin_slots}
        panel_info: Dict[Tuple[str, str], dict] = {}
        for c in self.companies:
            for panel in c.panels:
                panel_info[(c.id, panel.panel_id)] = {
                    "duration": panel.slot_duration_minutes or 30,
                    "reserved": panel.reserved_walkin_slots or 0,
                }

        # ── 2. Build application list with metadata ──────────────────────────

        # Base slot duration: 30 min (fixed grid — keeps model size manageable)
        BASE_DURATION = 30
        DAY_START = 9 * 60    # 09:00 in minutes
        DAY_END   = 17 * 60   # 17:00 in minutes
        num_slots = (DAY_END - DAY_START) // BASE_DURATION  # 16 slots

        # slot_min[t] = start minute of slot t (e.g. 0→540, 1→570, …, 15→1020)
        slot_min = [DAY_START + t * BASE_DURATION for t in range(num_slots)]

        # ── Build per-student blocked slots from pinned interviews ────────────
        # Maps student_id → set of 30-min base slot indices that their pinned
        # interviews overlap. Used to prevent double-booking in other companies.
        pinned_student_blocked: Dict[str, set] = {}
        for _piv in pinned_interviews_raw:
            _sid = _piv['student_id']
            try:
                _ps = datetime.fromisoformat(_piv['start_time'])
                _pe = datetime.fromisoformat(_piv['end_time'])
                _sm = _ps.hour * 60 + _ps.minute
                _em = _pe.hour * 60 + _pe.minute
                _blk = pinned_student_blocked.setdefault(_sid, set())
                for _t in range(num_slots):
                    if max(_sm, slot_min[_t]) < min(_em, slot_min[_t] + BASE_DURATION):
                        _blk.add(_t)
            except Exception:
                pass

        # slot_start[t] = actual datetime for slot t
        day_dt = datetime.strptime(event_date, "%Y-%m-%d")
        slot_start_dt = [day_dt + timedelta(minutes=m - DAY_START + DAY_START)
                         for m in slot_min]
        # Simpler: just compute from event_date
        slot_start_dt = [
            datetime.strptime(f"{event_date} 09:00", "%Y-%m-%d %H:%M") + timedelta(minutes=t * BASE_DURATION)
            for t in range(num_slots)
        ]

        import math
        valid_apps = []
        # app_group: tracks all valid_apps indices for the same (student, company, role)
        # so we can add a "schedule at most once" constraint across multiple panels
        app_group: Dict[Tuple[str, str, str], List[int]] = {}

        for s in self.students:
            for app in s.applications:
                # Only schedule students who were shortlisted (or waitlisted as fallback).
                # APPLIED means the company has not shortlisted them — exclude from scheduled interviews.
                if app.status not in [AppStatus.SHORTLISTED, AppStatus.WAITLISTED]:
                    continue
                # Skip companies whose schedule is hardcoded (pinned)
                if app.company_id in pinned_company_ids:
                    continue
                if app.company_id not in company_map:
                    continue
                company = company_map[app.company_id]

                # Determine which panels handle this role — may be multiple
                pid_list = panels_for_role.get((company.id, app.job_role_id))
                if pid_list:
                    candidate_pids = pid_list
                elif company.panels:
                    # Role not explicitly assigned to any panel → use first panel
                    candidate_pids = [company.panels[0].panel_id]
                else:
                    # No panels configured at all → synthetic placeholder
                    candidate_pids = [f"{company.id}-P0"]

                group_key = (s.id, app.company_id, app.job_role_id)

                for pid in candidate_pids:
                    # Determine interview duration + reserved slots for this panel
                    pinfo = panel_info.get((company.id, pid))
                    if pinfo:
                        dur = pinfo["duration"]
                        reserved = pinfo["reserved"]
                    else:
                        role = role_map.get(app.job_role_id)
                        dur = role.duration_minutes if role else BASE_DURATION
                        reserved = 0

                    # Availability window (Phase 1c)
                    avail_start = self._hhmm_to_min(company.availability_start or "09:00")
                    avail_end   = self._hhmm_to_min(company.availability_end   or "17:00")

                    # Phase 2b: slots_needed = ceil(dur / BASE_DURATION)
                    slots_needed = max(1, math.ceil(dur / BASE_DURATION))

                    # Phase 5: Break logic — panel overrides company if panel has breaks
                    active_breaks = company.breaks
                    if company.panels:
                        for p in company.panels:
                            if p.panel_id == pid:
                                if p.breaks:
                                    active_breaks = p.breaks
                                break

                    break_intervals = []
                    for b in active_breaks:
                        try:
                            if b.get("start") and b.get("end"):
                                bs = self._hhmm_to_min(b["start"])
                                be = self._hhmm_to_min(b["end"])
                                break_intervals.append((bs, be))
                        except:
                            pass

                    candidate_slots = []
                    for t in range(num_slots):
                        if not (slot_min[t] >= avail_start and
                                slot_min[t] + dur <= avail_end and
                                t + slots_needed - 1 < num_slots):
                            continue
                        iv_start = slot_min[t]
                        iv_end = iv_start + dur
                        hits_break = any(max(iv_start, bs) < min(iv_end, be)
                                         for (bs, be) in break_intervals)
                        if not hits_break:
                            candidate_slots.append(t)

                    if reserved > 0 and len(candidate_slots) > reserved:
                        candidate_slots = candidate_slots[:-reserved]

                    # Remove slots blocked by pinned interviews for this student
                    _pblk = pinned_student_blocked.get(s.id)
                    if _pblk:
                        candidate_slots = [
                            t for t in candidate_slots
                            if not any(b in _pblk for b in range(t, t + slots_needed))
                        ]

                    if not candidate_slots:
                        continue

                    idx = len(valid_apps)
                    valid_apps.append({
                        "student": s,
                        "app": app,
                        "company": company,
                        "panel_id": pid,
                        "duration": dur,
                        "slots_needed": slots_needed,
                        "valid_slots": candidate_slots,
                        "group_key": group_key,
                    })
                    app_group.setdefault(group_key, []).append(idx)

        print(f"  Found {len(valid_apps)} potential interviews to schedule across {num_slots} slots.")

        # ── 3. Build OR-Tools model ──────────────────────────────────────────

        model = cp_model.CpModel()

        # Variables: only create x[(i, t)] for valid start slots of app i
        x: Dict[Tuple[int, int], object] = {}
        for i, item in enumerate(valid_apps):
            for t in item["valid_slots"]:
                x[(i, t)] = model.NewBoolVar(f'a{i}_t{t}')

        # C1: Each valid_apps entry scheduled at most once
        for i, item in enumerate(valid_apps):
            model.Add(sum(x[(i, t)] for t in item["valid_slots"]) <= 1)

        # C_GROUP: A student can only be scheduled ONCE per (company, role) across
        # all panels that share that role. Without this, one student could be
        # scheduled simultaneously on Panel A and Panel B for the same role.
        for group_key, indices in app_group.items():
            if len(indices) > 1:
                model.Add(
                    sum(x[(i, t)]
                        for i in indices
                        for t in valid_apps[i]["valid_slots"]) <= 1
                )

        # C2: Student no-overlap — Phase 2b: block ALL slots occupied by the interview.
        # If app i starts at slot t and needs k slots, it occupies t, t+1, …, t+k-1.
        # For each base slot b, sum over all apps whose interval covers b must be ≤ 1.
        # Use sets to avoid duplicate app indices when slots_needed > 1
        student_slot_apps: Dict[str, Dict[int, set]] = {}
        for i, item in enumerate(valid_apps):
            sid = item["student"].id
            sn  = item["slots_needed"]
            if sid not in student_slot_apps:
                student_slot_apps[sid] = {}
            for t in item["valid_slots"]:
                # This app starting at t occupies base slots t … t+sn-1
                for b in range(t, t + sn):
                    if b < num_slots:
                        student_slot_apps[sid].setdefault(b, set()).add(i)

        for sid, slot_dict in student_slot_apps.items():
            for b, indices in slot_dict.items():
                if len(indices) > 1:
                    model.Add(sum(x[(i, t)]
                                  for i in indices
                                  for t in valid_apps[i]["valid_slots"]
                                  if t <= b < t + valid_apps[i]["slots_needed"]) <= 1)

        # C3: Per-panel no-overlap — Phase 2b: same multi-slot blocking logic
        # Use sets to avoid duplicate app indices when slots_needed > 1
        panel_slot_apps: Dict[Tuple[str, str], Dict[int, set]] = {}
        for i, item in enumerate(valid_apps):
            key = (item["company"].id, item["panel_id"])
            sn  = item["slots_needed"]
            if key not in panel_slot_apps:
                panel_slot_apps[key] = {}
            for t in item["valid_slots"]:
                for b in range(t, t + sn):
                    if b < num_slots:
                        panel_slot_apps[key].setdefault(b, set()).add(i)

        for key, slot_dict in panel_slot_apps.items():
            for b, indices in slot_dict.items():
                if len(indices) > 1:
                    model.Add(sum(x[(i, t)]
                                  for i in indices
                                  for t in valid_apps[i]["valid_slots"]
                                  if t <= b < t + valid_apps[i]["slots_needed"]) <= 1)

        # ── Panel load variables ──────────────────────────────────────────────
        # panel_load[(company_id, panel_id)] = number of interviews scheduled
        # on that panel. Used for balance penalty in the objective.
        panel_keys = list({(item["company"].id, item["panel_id"]) for item in valid_apps})
        panel_load: Dict[Tuple[str, str], object] = {}
        for key in panel_keys:
            pload = model.NewIntVar(0, num_slots, f"load_{key[0]}_{key[1]}")
            panel_load[key] = pload
            terms = [
                x[(i, t)]
                for i, item in enumerate(valid_apps)
                if (item["company"].id, item["panel_id"]) == key
                for t in item["valid_slots"]
            ]
            model.Add(pload == sum(terms))

        # ── Per-company imbalance variables ───────────────────────────────────
        # For each company with 2+ panels, penalise (max_load - min_load).
        # Weight: 1 000 so balance is always subordinate to scheduling one more
        # real interview (tier-1 weight 1 000 000) but dominates slot packing
        # (tier-3 max ~16 per interview).
        imbalance_terms = []
        company_panel_keys: Dict[str, list] = {}
        for cid, pid in panel_keys:
            company_panel_keys.setdefault(cid, []).append((cid, pid))

        for cid, keys in company_panel_keys.items():
            if len(keys) < 2:
                continue
            load_vars = [panel_load[k] for k in keys]
            max_load = model.NewIntVar(0, num_slots, f"max_load_{cid}")
            min_load = model.NewIntVar(0, num_slots, f"min_load_{cid}")
            imbalance = model.NewIntVar(0, num_slots, f"imbalance_{cid}")
            model.AddMaxEquality(max_load, load_vars)
            model.AddMinEquality(min_load, load_vars)
            model.Add(imbalance == max_load - min_load)
            imbalance_terms.append(imbalance * 1_000)

        # ── 3-tier objective ──────────────────────────────────────────────────
        # Tier 1 (1 100 000 / 1 000 000): Maximise interviews scheduled.
        #   SHORTLISTED > WAITLISTED so shortlisted fill first when capacity limited.
        # Tier 2 (-1 000 × imbalance): Balance interview counts across panels of
        #   the same company. A gap of 1 interview costs 1 000 — less than one
        #   real interview, so balance never evicts a real candidate.
        # Tier 3 (num_slots - t): Pack interviews as early as possible within
        #   each panel's availability window. Max ~16 per interview — always
        #   subordinate to balance (min 1 000 per imbalance unit).
        tier1_terms = []
        tier3_terms = []
        for i, item in enumerate(valid_apps):
            app = item["app"]
            t1_weight = 1_100_000 if app.status == AppStatus.SHORTLISTED else 1_000_000
            for t in item["valid_slots"]:
                tier1_terms.append(x[(i, t)] * t1_weight)
                tier3_terms.append(x[(i, t)] * (num_slots - t))

        model.Maximize(
            sum(tier1_terms)
            - sum(imbalance_terms)
            + sum(tier3_terms)
        )

        # ── 4. Solve ─────────────────────────────────────────────────────────
        solver = cp_model.CpSolver()
        solver.parameters.max_time_in_seconds = 60.0  # safety cap
        status = solver.Solve(model)
        print(f"  Solver Status: {solver.StatusName(status)}")

        self.interviews = []

        if status in (cp_model.OPTIMAL, cp_model.FEASIBLE):
            count = 0
            for i, item in enumerate(valid_apps):
                for t in item["valid_slots"]:
                    if (i, t) in x and solver.BooleanValue(x[(i, t)]):
                        start_dt = slot_start_dt[t]
                        end_dt   = start_dt + timedelta(minutes=item["duration"])
                        interview = Interview(
                            id=f"INT-{count + 1}",
                            student_id=item["student"].id,
                            company_id=item["company"].id,
                            job_role_id=item["app"].job_role_id,
                            panel_id=item["panel_id"],       # Phase 2a
                            start_time=start_dt.isoformat(),
                            end_time=end_dt.isoformat(),
                        )
                        self.interviews.append(interview)
                        count += 1
            print(f"  Optimization found {count} interviews.")
            print(f"  Objective Value: {solver.ObjectiveValue()}")
        else:
            print("  No solution found.")

        # ── Prepend pinned interviews to the final result ─────────────────────
        pinned_objs = []
        for _piv in pinned_interviews_raw:
            try:
                pinned_objs.append(Interview(
                    id=_piv['id'],
                    student_id=_piv['student_id'],
                    company_id=_piv['company_id'],
                    job_role_id=_piv['job_role_id'],
                    panel_id=_piv['panel_id'],
                    start_time=_piv['start_time'],
                    end_time=_piv['end_time'],
                    status=_piv.get('status', 'scheduled'),
                    pinned=True,
                ))
            except Exception as e:
                print(f"  Warning: could not reload pinned interview {_piv.get('id')}: {e}")
        self.interviews = pinned_objs + self.interviews
        print(f"  Total (pinned {len(pinned_objs)} + scheduled {len(self.interviews) - len(pinned_objs)}): {len(self.interviews)}")

        return self.interviews


if __name__ == "__main__":
    import os
    if os.path.basename(os.getcwd()) == "schedule_manager":
        sys.path.append(os.path.abspath(os.path.join(os.getcwd(), "..")))
    print("Running Scheduler Standalone...")
    dm = DataManager()
    scheduler = Scheduler(dm)
    interviews = scheduler.run("2026-02-20")
    print(f"Standalone execution finished. {len(interviews)} interviews scheduled.")
