from datetime import datetime, timedelta
from typing import List, Dict, Tuple, Optional
import sys

# Try importing OR-Tools
try:
    from ortools.sat.python import cp_model
    ORTOOLS_AVAILABLE = True
except ImportError:
    ORTOOLS_AVAILABLE = False

import csv
from datetime import datetime
from schedule_manager.data_manager import DataManager, Student, Company, Application, Interview, AppStatus


class Scheduler:
    def __init__(self, data_manager: DataManager):
        self.dm = data_manager
        self.students = self.dm.load_students()
        self.companies = self.dm.load_companies()
        self.interviews: List[Interview] = []
        self.fixed_slots = {}  # (student_id, company_id, role_id) -> [(start_min, end_min, panel_id)]

    def load_fixed_sysco_schedule(self, csv_file: str):
        """Loads fixed schedule from CSV and populates self.fixed_slots."""
        try:
            with open(csv_file, 'r') as f:
                reader = csv.DictReader(f)
                
                # Mapping constants
                company_id = "sysco_labs_technologies_pvt_ltd"
                
                # Map CSV "Position" to (Role ID, Panel Code)
                # SE1 -> Software Engineer, Panel 1
                # SE2 -> Software Engineer, Panel 2
                # QE1 -> Quality Assurance, Panel 1
                # QE2 -> Quality Assurance, Panel 2
                
                role_base_se = "sysco_labs_technologies_pvt_ltd_software_engineer"
                role_base_qe = "sysco_labs_technologies_pvt_ltd_quality_assurance"
                
                for row in reader:
                    # Parse Student ID: E/20/133 -> E20133
                    reg_no = row['Reg Number'].strip()
                    if not reg_no: continue
                    
                    parts = reg_no.split('/')
                    if len(parts) == 3:
                        student_id = f"{parts[0]}{parts[1]}{parts[2]}" # E + 20 + 133
                    else:
                        print(f"Warning: Invalid Reg No format: {reg_no}")
                        continue
                        
                    # Helper to process an entry
                    def process_entry(pos_str, time_str):
                        if not pos_str or not time_str: return
                        
                        pos_str = pos_str.upper().strip()
                        role_id = None
                        panel_suffix = None
                        
                        if pos_str.startswith("SE"):
                            role_id = role_base_se
                            # SE1 -> P1, SE2 -> P2
                            panel_suffix = pos_str.replace("SE", "")
                        elif pos_str.startswith("QE"):
                            role_id = role_base_qe
                            # QE1 -> P3, QE2 -> P4 (Assuming separate panel allocation)
                            qe_suffix = pos_str.replace("QE", "")
                            if qe_suffix == "1":
                                panel_suffix = "3"
                            elif qe_suffix == "2":
                                panel_suffix = "4"
                            else:
                                panel_suffix = qe_suffix # Fallback
                            
                        if role_id and panel_suffix:
                             self._add_fixed_slot(student_id, company_id, role_id, time_str, panel_suffix)

                    # Process Position 1
                    process_entry(row.get('Position1'), row.get('Timeslot1'))
                        
                    # Process Position 2 (if exists in this row, though new format seems single)
                    process_entry(row.get('Position2'), row.get('Timeslot2'))
                        
            print(f"Loaded fixed schedule for {len(self.fixed_slots)} students/roles.")
        except FileNotFoundError:
            print(f"Warning: Fixed schedule file {csv_file} not found.")

    def _add_fixed_slot(self, student_id, company_id, role_id, time_str, panel_suffix):
        # Time format: "9.30 am to 10.15 am"
        try:
            start_str, end_str = time_str.lower().split(' to ')
            start_min = self._parse_time_am_pm(start_str.strip())
            end_min = self._parse_time_am_pm(end_str.strip())
            
            key = (student_id, company_id, role_id)
            if key not in self.fixed_slots:
                self.fixed_slots[key] = []
            
            # Identify panel ID
            # Config has "sysco_labs_technologies_pvt_ltd-P1", etc.
            # But the suffix might be '1' or '2'.
            target_panel_id = None
            if panel_suffix:
                # We can't know the full ID exactly without lookup, but we can construct likely ID
                # or store the suffix and match later against candidate PIDs
                target_panel_id = f"{company_id}-P{panel_suffix}" 
                # Note: The JSON has extra timestamp suffix e.g. -P2-1771524... for some panels!
                # P1 is simple "sysco_labs_technologies_pvt_ltd-P1"
                # Others have suffixes. We need to do a "startswith" match later.
                
            self.fixed_slots[key].append((start_min, end_min, panel_suffix))
        except ValueError as e:
            print(f"Error parsing time '{time_str}': {e}")

    def _parse_time_am_pm(self, t_str: str) -> int:
        # "9.30 am" -> minutes
        dt = datetime.strptime(t_str, "%I.%M %p")
        return dt.hour * 60 + dt.minute


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
        
        # Load fixed schedule if available
        import os
        if os.path.exists("sysco_schedule.csv"):
            self.load_fixed_sysco_schedule("sysco_schedule.csv")

        # Base slot duration: 5 min (fixed grid — keeps model size manageable and handles irregular start times)
        BASE_DURATION = 5
        DAY_START = 9 * 60    # 09:00 in minutes
        DAY_END   = 17 * 60   # 17:00 in minutes
        num_slots = (DAY_END - DAY_START) // BASE_DURATION  # 96 slots

        # slot_min[t] = start minute of slot t (e.g. 0→540, 1→545, ...)
        slot_min = [DAY_START + t * BASE_DURATION for t in range(num_slots)]

        # slot_start_dt = actual datetime for slot t
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
                if app.status not in [AppStatus.APPLIED, AppStatus.SHORTLISTED, AppStatus.WAITLISTED]:
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
                
                # Check for forced fixed slots
                forced_slots = self.fixed_slots.get((s.id, app.company_id, app.job_role_id), [])
                
                # HARDCODE: If forced slots exist with panel suffixes, override candidate_pids
                # This ensures we respect the CSV mapping ("SE1" -> P1) even if metadata suggests otherwise
                forced_panel_ids = set()
                for (_, _, suffix) in forced_slots:
                    if suffix:
                         # Construct full ID: sysco...-P{suffix}
                         # We need to find the actual panel ID in company.panels that matches this suffix
                         # because real IDs have timestamps (e.g. ...-P2-177...)
                         suffix_match = f"-P{suffix}"
                         suffix_match_dash = f"-P{suffix}-"
                         
                         found = False
                         if company.panels:
                             for p in company.panels:
                                 if p.panel_id.endswith(suffix_match) or (suffix_match_dash in p.panel_id):
                                     forced_panel_ids.add(p.panel_id)
                                     found = True
                                     break
                         
                         if not found:
                             # Fallback: construct simple ID if not found in config (might fail validation but ensures intent)
                             forced_panel_ids.add(f"{company.id}-P{suffix}")

                if forced_panel_ids:
                    candidate_pids = list(forced_panel_ids)

                for pid in candidate_pids:
                    # Determine interview duration + reserved slots for this panel
                    pinfo = panel_info.get((company.id, pid))
                    if pinfo:
                        dur = pinfo["duration"]
                        reserved = pinfo["reserved"]
                    else:
                        role = role_map.get(app.job_role_id)
                        dur = role.duration_minutes if role else 30 # Default back to 30 if undefined
                        reserved = 0

                    candidate_slots = []
                    
                    if forced_slots:
                        # If fixed slots exist, valid slots MUST be exact matches
                        # Find t such that slot_min[t] matches a fixed start time
                        # AND duration matches fixed duration
                        for (fs_start, fs_end, fs_panel_suffix) in forced_slots:
                             
                             # Check panel constraint first
                             if fs_panel_suffix:
                                 # We need to see if this pid matches the suffix
                                 # Config uses "-P{suffix}" or "-P{suffix}-timestamp"
                                 # Example: sysco...-P5-177... vs suffix="5"
                                 suffix_match = f"-P{fs_panel_suffix}"
                                 suffix_match_dash = f"-P{fs_panel_suffix}-"
                                 
                                 # PID usually ends with suffix or has dash
                                 if not (pid.endswith(suffix_match) or 
                                         (suffix_match_dash in pid)):
                                     continue

                             # Find t:
                             if (fs_start - DAY_START) % BASE_DURATION == 0:
                                 t_idx = (fs_start - DAY_START) // BASE_DURATION
                                 if 0 <= t_idx < num_slots:
                                     # Override duration for calculation
                                     fs_dur = fs_end - fs_start
                                     
                                     # Use the fixed duration 
                                     dur = fs_dur
                                     candidate_slots.append(t_idx)

                        if not candidate_slots:
                            # Could not match fixed slot to grid or panel?
                            # Maybe we should verify this outside. 
                            # If forced_slots exist but none matched grid, it means app won't be scheduled.
                            # But wait, we iterate over panels. If this student has a fixed slot, 
                            # we add it as candidate for ALL compatible panels?
                            # YES, let the solver pick WHICH panel.
                            pass
                    
                    else:
                        # Normal logic
                        # Availability window (Phase 1c)
                        avail_start = self._hhmm_to_min(company.availability_start or "09:00")
                        avail_end   = self._hhmm_to_min(company.availability_end   or "17:00")

                        # Phase 5: Break logic
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

                        # Make slots_needed based on duration
                        slots_needed_calc = max(1, math.ceil(dur / BASE_DURATION))
    
                        for t in range(num_slots):
                            if not (slot_min[t] >= avail_start and
                                    slot_min[t] + dur <= avail_end and
                                    t + slots_needed_calc - 1 < num_slots):
                                continue
                            iv_start = slot_min[t]
                            iv_end = iv_start + dur
                            hits_break = any(max(iv_start, bs) < min(iv_end, be)
                                             for (bs, be) in break_intervals)
                            if not hits_break:
                                candidate_slots.append(t)
    
                        if reserved > 0 and len(candidate_slots) > reserved:
                            candidate_slots = candidate_slots[:-reserved]

                    if not candidate_slots:
                        continue
                    
                    # Recalculate slots_needed based on final dur
                    slots_needed = max(1, math.ceil(dur / BASE_DURATION))

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
                        "force_fixed": bool(forced_slots)
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
            # Check if any index is forced
            is_any_forced = any(valid_apps[i].get("force_fixed") for i in indices)
            
            if len(indices) >= 1: # Logic applies even if len=1
                 constraint_sum = sum(x[(i, t)]
                        for i in indices
                        for t in valid_apps[i]["valid_slots"])
                 
                 if is_any_forced:
                      model.Add(constraint_sum == 1)
                 else:
                      model.Add(constraint_sum <= 1)


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
            
            # Boost weight for fixed schedule items to ensure solver prefers them if feasible
            # (Though constraints already force them)
            if item.get("force_fixed"):
                weight += 1000
                
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
