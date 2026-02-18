from datetime import datetime, timedelta
from typing import List, Dict, Set, Tuple, Optional
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
        
        # Maps to track availability (if we were preserving state, but optimization usually rebuilds)
        # For this implementation, we assume run() builds from scratch for the given day
        
    def generate_slots(self, date_str: str, start_hour: int = 9, end_hour: int = 17, duration_minutes: int = 30) -> List[datetime]:
        """Generates a list of start times for a given day."""
        slots = []
        current = datetime.strptime(f"{date_str} {start_hour}:00", "%Y-%m-%d %H:%M")
        end_time = datetime.strptime(f"{date_str} {end_hour}:00", "%Y-%m-%d %H:%M")
        
        while current < end_time:
            slots.append(current)
            current += timedelta(minutes=duration_minutes)
        return slots

    def run(self, event_date: str = "2026-02-20") -> List[Interview]:
        if not ORTOOLS_AVAILABLE:
            print("ERROR: OR-Tools not installed. Please run 'pip install ortools'.")
            return []

        print(f"Starting OR-Tools optimization for {event_date}...")
        
        # 1. Prepare Data
        slots = self.generate_slots(event_date)
        num_slots = len(slots)
        
        # Flatten applications to schedule
        # List of (Student, Application, Company)
        valid_apps = []
        
        # For lookup
        company_map = {c.id: c for c in self.companies}
        
        for s in self.students:
            for app in s.applications:
                # We consider APPLIED, SHORTLISTED, and WAITLISTED for optimization
                # (Assuming we want to schedule as many as possible given constraints)
                if app.status in [AppStatus.APPLIED, AppStatus.SHORTLISTED, AppStatus.WAITLISTED]:
                    valid_apps.append({
                        "student": s,
                        "app": app,
                        "company": company_map[app.company_id]
                    })

        print(f"  Found {len(valid_apps)} potential interviews to schedule across {num_slots} slots.")

        # 2. Build Model
        model = cp_model.CpModel()
        
        # Variables: x[app_index, slot_index]
        # 1 if valid_apps[i] is scheduled at slot[j], 0 otherwise
        x = {}
        
        for i, item in enumerate(valid_apps):
            for t in range(num_slots):
                x[(i, t)] = model.NewBoolVar(f'app_{i}_slot_{t}')

        # Constraints
        
        # C1: Each application scheduled at most once
        for i in range(len(valid_apps)):
            model.Add(sum(x[(i, t)] for t in range(num_slots)) <= 1)
            
        # C2: Student can have at most 1 interview per slot
        # Group apps by student
        apps_by_student = {}
        for i, item in enumerate(valid_apps):
            s_id = item["student"].id
            if s_id not in apps_by_student: apps_by_student[s_id] = []
            apps_by_student[s_id].append(i)
            
        for s_id, app_indices in apps_by_student.items():
            for t in range(num_slots):
                model.Add(sum(x[(i, t)] for i in app_indices) <= 1)

        # C3: Company can have at most 1 interview per slot (Assuming 1 panel per company for now)
        # If companies have multiple roles/panels, we might handle this differently, 
        # but safe assumption is 1 slot = 1 interview for the company entity.
        apps_by_company = {}
        for i, item in enumerate(valid_apps):
            c_id = item["company"].id
            if c_id not in apps_by_company: apps_by_company[c_id] = []
            apps_by_company[c_id].append(i)
            
        for c_id, app_indices in apps_by_company.items():
            for t in range(num_slots):
                model.Add(sum(x[(i, t)] for i in app_indices) <= 1)

        # Objective: Maximize total scheduled interviews
        # Weighting:
        # - Shortlisted apps could have higher weight?
        # - Earlier slots could have tiny positive weight to compact schedule?
        
        objective_terms = []
        for i, item in enumerate(valid_apps):
            app = item["app"]
            
            # Base weight
            weight = 10
            
            # Boost for Shortlisted
            if app.status == AppStatus.SHORTLISTED:
                weight += 20
            
            # Boost for Priority (if it exists, lower is better. 1=High)
            if app.priority:
                # 1->5, 2->4, 3->3, etc.
                weight += (6 - app.priority)
            
            for t in range(num_slots):
                objective_terms.append(x[(i, t)] * weight)

        model.Maximize(sum(objective_terms))

        # 3. Solve
        solver = cp_model.CpSolver()
        # solver.parameters.log_search_progress = True
        status = solver.Solve(model)

        print(f"  Solver Status: {solver.StatusName(status)}")
        
        self.interviews = []

        if status == cp_model.OPTIMAL or status == cp_model.FEASIBLE:
            count = 0
            for i, item in enumerate(valid_apps):
                for t in range(num_slots):
                    if solver.BooleanValue(x[(i, t)]):
                        # Scheduled!
                        slot_start = slots[t]
                        slot_end = slot_start + timedelta(minutes=30)
                        
                        student = item["student"]
                        company = item["company"]
                        app = item["app"]
                        
                        interview = Interview(
                            id=f"INT-{count+1}",
                            student_id=student.id,
                            company_id=company.id,
                            job_role_id=app.job_role_id,
                            start_time=slot_start.isoformat(),
                            end_time=slot_end.isoformat()
                        )
                        self.interviews.append(interview)
                        count += 1
                        
            print(f"  Optimization found {count} interviews.")
            print(f"  Objective Value: {solver.ObjectiveValue()}")
        else:
            print("  No solution found.")

        return self.interviews

if __name__ == "__main__":
    from schedule_manager.data_manager import DataManager
    import os
    
    # Ensure we are in the project root context for imports
    # If running from inside schedule_manager, add parent to path
    if os.path.basename(os.getcwd()) == "schedule_manager":
        sys.path.append(os.path.abspath(os.path.join(os.getcwd(), "..")))
    
    print("Running Scheduler Standalone...")
    dm = DataManager()
    scheduler = Scheduler(dm)
    interviews = scheduler.run("2026-02-20")
    print(f"Standalone execution finished. {len(interviews)} interviews scheduled.")
