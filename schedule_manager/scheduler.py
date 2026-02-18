from datetime import datetime, timedelta
from typing import List, Dict, Set, Tuple
import random
from schedule_manager.data_manager import DataManager, Student, Company, Application, Interview, AppStatus

class Scheduler:
    def __init__(self, data_manager: DataManager):
        self.dm = data_manager
        self.students = self.dm.load_students()
        self.companies = self.dm.load_companies()
        self.interviews: List[Interview] = []
        
        # Maps to track availability
        # student_id -> set of (start_time)
        self.student_schedule: Dict[str, Set[datetime]] = {}
        # company_id -> set of (start_time)
        self.company_schedule: Dict[str, Set[datetime]] = {}
        
    def generate_slots(self, date_str: str, start_hour: int = 9, end_hour: int = 17, duration_minutes: int = 30) -> List[datetime]:
        """Generates a list of start times for a given day."""
        slots = []
        current = datetime.strptime(f"{date_str} {start_hour}:00", "%Y-%m-%d %H:%M")
        end_time = datetime.strptime(f"{date_str} {end_hour}:00", "%Y-%m-%d %H:%M")
        
        while current < end_time:
            slots.append(current)
            current += timedelta(minutes=duration_minutes)
        return slots

    def run(self, event_date: str = "2024-10-25", iterations: int = 100):
        print(f"Starting schedule optimization for {event_date} ({iterations} iterations)...")
        
        best_interviews = []
        best_count = -1
        
        # Use deepcopy to preserve the best list of Interview objects
        from copy import deepcopy

        for i in range(iterations):
            # Reset state for this iteration
            self.interviews = []
            self.student_schedule = {}
            self.company_schedule = {}
            
            # Run single pass
            self._run_single_iteration(event_date, verbose=(i==0))
            
            current_count = len(self.interviews)
            
            if current_count > best_count:
                best_count = current_count
                best_interviews = deepcopy(self.interviews)
                print(f"  > New best found: {best_count} interviews (Iteration {i+1})")
        
        # Restore best result
        self.interviews = best_interviews
        print(f"Optimization Complete. Final Schedule: {len(self.interviews)} interviews.")
        return self.interviews

    def _run_single_iteration(self, event_date: str, verbose: bool = False):
        if verbose:
            print(f"Generating base schedule for {event_date}...")
        
        # 1. Prepare slots
        all_slots = self.generate_slots(event_date)
        
        # 2. Collect all valid applications (Shortlisted only for now)
        # We need to flatten the structure to: (Application, Company, Student)
        pending_apps = []
        
        company_map = {c.id: c for c in self.companies}
        
        for s in self.students:
            for app in s.applications:
                if app.status == AppStatus.SHORTLISTED:
                    # Determine sort priority:
                    # 1. Company Priority (1 is highest)
                    # 2. If no priority, treat as lower priority (e.g. 6)
                    prio = app.priority if app.priority is not None else 6
                    
                    pending_apps.append({
                        "app": app,
                        "student": s,
                        "company": company_map[app.company_id],
                        "priority": prio,
                        "random_tie_breaker": random.random() # To shuffle equal priorities
                    })
        
        # 3. Sort applications
        # Primary key: Priority (ascending, 1 is best)
        # Secondary key: Random tie breaker (fairness)
        pending_apps.sort(key=lambda x: (x["priority"], x["random_tie_breaker"]))
        
        if verbose:
            print(f"Processing {len(pending_apps)} shortlisted applications...")
        
        scheduled_count = 0
        conflict_count = 0
        
        for item in pending_apps:
            app: Application = item["app"]
            student: Student = item["student"]
            company: Company = item["company"]
            
            # Try to find a slot
            assigned_slot = None
            
            # Simple Greedy Strategy:
            # Look for the first slot where BOTH Student and Company are free
            for slot in all_slots:
                if self._is_slot_available(student.id, company.id, slot):
                    assigned_slot = slot
                    break
            
            if assigned_slot:
                self._book_slot(student.id, company.id, app, assigned_slot)
                scheduled_count += 1
            else:
                conflict_count += 1
                app.status = AppStatus.WAITLISTED # Downgrade to waitlist if no slot found
                # print(f"Conflict: Could not schedule {student.name} for {company.name}")

        if verbose:
            print(f"Phase 2 Complete. Scheduled Shortlisted: {scheduled_count}")

        # 4. Phase: Open Allocation (Waitlisted & Applied)
        # Collect all remaining applications (Applied status) and those waitlisted from Phase 2
        
        open_apps = []
        for s in self.students:
            for app in s.applications:
                # We want to schedule 'APPLIED' candidates
                # AND 'WAITLISTED' candidates (who were shortlisted but conflicted)
                if app.status == AppStatus.APPLIED or app.status == AppStatus.WAITLISTED:
                    # Priority for open allocation:
                    # - Waitlisted (previously shortlisted) should probably come first?
                    # - Or just mix them? 
                    # User said: "give chance to not shortlisted peoples"
                    # Let's prioritize WAITLISTED (conflicted shortlisted) over APPLIED
                    prio_score = 1 if app.status == AppStatus.WAITLISTED else 2
                    
                    open_apps.append({
                        "app": app,
                        "student": s,
                        "company": company_map[app.company_id],
                        "priority": prio_score,
                        "random_tie_breaker": random.random()
                    })
        
        # Sort by priority then random
        open_apps.sort(key=lambda x: (x["priority"], x["random_tie_breaker"]))
        
        if verbose:
            print(f"Processing {len(open_apps)} open applications...")
        
        open_scheduled_count = 0
        
        for item in open_apps:
            app: Application = item["app"]
            student: Student = item["student"]
            company: Company = item["company"]
            
            # Check if student already has too many interviews?
            # User said max 7 applications, but maybe we cap interviews to 5?
            # For now, no cap implemented, just availability.
            
            assigned_slot = None
            for slot in all_slots:
                if self._is_slot_available(student.id, company.id, slot):
                    assigned_slot = slot
                    break
            
            if assigned_slot:
                self._book_slot(student.id, company.id, app, assigned_slot)
                open_scheduled_count += 1
                # If it was APPLIED, it's now SCHEDULED (effectively shortlisted+scheduled)
                # We don't change status to SHORTLISTED to preserve history, but it is in interviews list.
                
        if verbose:
            print(f"Phase 3 Complete. Scheduled Open: {open_scheduled_count}")
            print(f"Total Scheduled: {len(self.interviews)}")
        
        return self.interviews

    def _is_slot_available(self, student_id: str, company_id: str, start_time: datetime) -> bool:
        # Check student availability
        if student_id not in self.student_schedule:
            self.student_schedule[student_id] = set()
        if start_time in self.student_schedule[student_id]:
            return False
            
        # Check company availability
        if company_id not in self.company_schedule:
            self.company_schedule[company_id] = set()
        if start_time in self.company_schedule[company_id]:
            return False
            
        return True

    def _book_slot(self, student_id: str, company_id: str, app: Application, start_time: datetime, duration_minutes: int = 30):
        # Update internal sets
        self.student_schedule[student_id].add(start_time)
        self.company_schedule[company_id].add(start_time)
        
        # Create Interview object
        end_time = start_time + timedelta(minutes=duration_minutes)
        interview = Interview(
            id=f"INT-{len(self.interviews)+1}",
            student_id=student_id,
            company_id=company_id,
            job_role_id=app.job_role_id,
            start_time=start_time.isoformat(),
            end_time=end_time.isoformat()
        )
        self.interviews.append(interview)
