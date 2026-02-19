import sys
import os
import datetime

# Add project root to path
sys.path.append(os.getcwd())

from schedule_manager.scheduler import Scheduler, Company, Panel, JobRole, Candidate

def log(msg):
    print(f"[TEST] {msg}")

def run_test():
    log("Initializing Direct Scheduler Test...")
    
    # 1. Setup Mock Data
    cid = "sysco_test"
    
    # Create Panel 1 (12-1 Break)
    p1 = Panel(
        panel_id="P1",
        label="Sysco Panel A",
        job_role_ids=["jre_se"],
        slot_duration_minutes=30,
        reserved_walkin_slots=0,
        walk_in_open=False,
        breaks=[{"start": "12:00", "end": "13:00"}],
        slots=[], # initialize empty
        pending_schedule=[] # initialize empty
    )
    
    # Create Panel 2 (1-2 Break)
    p2 = Panel(
        panel_id="P2",
        label="Sysco Panel B",
        job_role_ids=["jre_se"],
        slot_duration_minutes=30,
        reserved_walkin_slots=0,
        walk_in_open=False,
        breaks=[{"start": "13:00", "end": "14:00"}],
        slots=[],
        pending_schedule=[]
    )
    
    company = Company(
        id=cid,
        name="Sysco Test",
        tier="Gold",
        job_roles=[JobRole(id="jre_se", title="SE", candidate_limit=50)],
        panels=[p1, p2],
        availability_start="09:00",
        availability_end="17:00",
        # break_duration_minutes removed if not in dataclass or optional
        breaks=[]
    )
    
    # Create Dummy Candidates
    candidates = []
    for i in range(20):
        c = Candidate(
            id=f"S{i}",
            name=f"Student {i}",
            email=f"s{i}@example.com",
            contact_number="123",
            gpa=3.5,
            experience_years=0,
            skills=[],
            preferred_companies=[cid],
            preferences_json=f'["{cid}"]',
            assigned_panels={}
        )
        candidates.append(c)
        
    log(f"Created company with 2 panels and {len(candidates)} candidates.")

    # 2. Run Scheduler
    scheduler = Scheduler([company], candidates, event_date="2026-02-20")
    log("Running scheduler logic...")
    schedule = scheduler.generate_schedule()
    
    # 3. Verify
    sysco_interviews = [i for i in schedule if i.company_id == cid]
    log(f"Generated {len(sysco_interviews)} interviews.")
    
    failures = 0
    p1_count = 0
    p2_count = 0
    
    for iv in sysco_interviews:
        start_time = iv.start_time.split("T")[1][:5]
        h, m = map(int, start_time.split(':'))
        start_min = h * 60 + m
        
        if iv.panel_id == "P1":
            p1_count += 1
            # Check 12:00-13:00 (720-780)
            if 720 <= start_min < 780:
                log(f"FAILURE: Panel A interview at {start_time}")
                failures += 1
        elif iv.panel_id == "P2":
            p2_count += 1
            # Check 13:00-14:00 (780-840)
            if 780 <= start_min < 840:
                log(f"FAILURE: Panel B interview at {start_time}")
                failures += 1
                
    log(f"Panel A Interviews: {p1_count}")
    log(f"Panel B Interviews: {p2_count}")
    
    if failures == 0:
        log("SUCCESS: Staggered lunch breaks respected. No overlaps.")
    else:
        log(f"FAILURE: {failures} overlaps found.")

if __name__ == "__main__":
    run_test()
