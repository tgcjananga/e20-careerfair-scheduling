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

        # ── 1. Prepare lookup tables ─────────────────────────────────────────

        company_map: Dict[str, Company] = {c.id: c for c in self.companies}

        # role_map: role_id → JobRole
        role_map = {}
        for c in self.companies:
            for r in c.job_roles:
                role_map[r.id] = r

        # For each (company_id, role_id): which panel handles it?
        panel_for_role: Dict[Tuple[str, str], str] = {}
        for c in self.companies:
            for panel in c.panels:
                for rid in panel.job_role_ids:
                    panel_for_role[(c.id, rid)] = panel.panel_id

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

        # slot_start[t] = actual datetime for slot t
        day_dt = datetime.strptime(event_date, "%Y-%m-%d")
        slot_start_dt = [day_dt + timedelta(minutes=m - DAY_START + DAY_START)
                         for m in slot_min]
        # Simpler: just compute from event_date
        slot_start_dt = [
            datetime.strptime(f"{event_date} 09:00", "%Y-%m-%d %H:%M") + timedelta(minutes=t * BASE_DURATION)
            for t in range(num_slots)
        ]

        valid_apps = []
        for s in self.students:
            for app in s.applications:
                if app.status not in [AppStatus.APPLIED, AppStatus.SHORTLISTED, AppStatus.WAITLISTED]:
                    continue
                if app.company_id not in company_map:
                    continue
                company = company_map[app.company_id]

                # Determine panel
                pid = panel_for_role.get((company.id, app.job_role_id), 'default')
                if pid == 'default' and company.panels:
                    pid = company.panels[0].panel_id
                elif pid == 'default': # If no panels defined, use a generic company-level panel_id
                    pid = f"{company.id}-P0" # Placeholder for company-level scheduling

                # Determine interview duration
                pinfo = panel_info.get((company.id, pid))
                if pinfo:
                    dur = pinfo["duration"]
                    reserved = pinfo["reserved"]
                else:
                    role = role_map.get(app.job_role_id)
                    dur = role.duration_minutes if role else BASE_DURATION  # Bug #G2 fix: was self.BASE_DURATION
                    reserved = 0

                # Availability window (Phase 1c)
                avail_start = self._hhmm_to_min(company.availability_start or "09:00")
                avail_end   = self._hhmm_to_min(company.availability_end   or "17:00")

                # Pre-compute which slots are valid for this application.
                # Phase 2b: an interview of `dur` minutes occupies ceil(dur/BASE_DURATION)
                # consecutive base slots. Slot t is valid only if ALL occupied slots fit
                # within the availability window AND do not overlap with breaks (Phase 5).
                import math
                slots_needed = max(1, math.ceil(dur / BASE_DURATION))

                # --- Phase 5: Break Logic ---
                # Determine active breaks for this panel
                active_breaks = company.breaks # Default
                # Find specific panel object if it exists
                if company.panels:
                    for p in company.panels:
                        if p.panel_id == pid:
                            if p.breaks: # Override if specific breaks defined
                                active_breaks = p.breaks
                            break
                
                # Convert breaks to (start_min, end_min) tuples
                break_intervals = []
                for b in active_breaks:
                    try:
                        if b.get("start") and b.get("end"):
                            bs = self._hhmm_to_min(b["start"])
                            be = self._hhmm_to_min(b["end"])
                            break_intervals.append((bs, be))
                    except: pass

                candidate_slots = []
                for t in range(num_slots):
                    # Check Availability Window
                    if not (slot_min[t] >= avail_start and
                            slot_min[t] + dur <= avail_end and
                            t + slots_needed - 1 < num_slots):
                        continue
                    
                    # Check Break Overlap
                    # The interview occupies time [start, end)
                    # Break is [b_start, b_end)
                    # Overlap if max(start, b_start) < min(end, b_end)
                    
                    iv_start = slot_min[t]
                    iv_end = iv_start + dur
                    
                    hits_break = False
                    for (bs, be) in break_intervals:
                        if max(iv_start, bs) < min(iv_end, be):
                            hits_break = True
                            break
                    
                    if not hits_break:
                        candidate_slots.append(t)
                if reserved > 0 and len(candidate_slots) > reserved:
                    candidate_slots = candidate_slots[:-reserved]

                if not candidate_slots:
                    continue  # No valid slot for this app, skip entirely

                valid_apps.append({
                    "student": s,
                    "app": app,
                    "company": company,
                    "panel_id": pid,
                    "duration": dur,
                    "slots_needed": slots_needed,  # Phase 2b: how many base-slots this interview occupies
                    "valid_slots": candidate_slots,
                })

        print(f"  Found {len(valid_apps)} potential interviews to schedule across {num_slots} slots.")

        # ── 3. Build OR-Tools model ──────────────────────────────────────────

        model = cp_model.CpModel()

        # Variables: only create x[(i, t)] for valid start slots of app i
        x: Dict[Tuple[int, int], object] = {}
        for i, item in enumerate(valid_apps):
            for t in item["valid_slots"]:
                x[(i, t)] = model.NewBoolVar(f'a{i}_t{t}')

        # C1: Each application scheduled at most once
        for i, item in enumerate(valid_apps):
            model.Add(sum(x[(i, t)] for t in item["valid_slots"]) <= 1)

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

        # ── Objective: maximise weighted scheduled interviews ─────────────────
        # Phase 2e: tiered weights for priority + status
        objective_terms = []
        for i, item in enumerate(valid_apps):
            app = item["app"]
            weight = 10
            if app.status == AppStatus.SHORTLISTED:
                weight += 20
            if app.priority:
                weight += max(0, 6 - app.priority)  # priority 1→+5, …, 5→+1
            for t in item["valid_slots"]:
                objective_terms.append(x[(i, t)] * weight)

        model.Maximize(sum(objective_terms))

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
