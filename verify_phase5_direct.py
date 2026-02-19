import sys
import os
import json
from datetime import date

# Add project root to path
sys.path.append(os.getcwd())

from schedule_manager.data_manager import DataManager, Panel
from schedule_manager.response_importer import ResponseImporter
from schedule_manager.scheduler import Scheduler

def log(msg):
    print(f"[TEST] {msg}")

def run_test():
    log("Starting Direct CSV Integration Test...")
    
    # 1. Initialize DataManager and Import CSV
    dm = DataManager()
    
    # We need to simulate a clean state?
    # DataManager loads from JSON files. We might want to seed first?
    # But seed() is in seed_data.py
    from seed_data import seed
    log("Seeding initial data...")
    seed()
    
    log("Importing from CSV 'Carrier Fair - 2026_responses.csv'...")
    importer = ResponseImporter(dm)
    if not os.path.exists("Carrier Fair - 2026_responses.csv"):
        log("ERROR: CSV file not found!")
        return

    try:
        importer.import_responses("Carrier Fair - 2026_responses.csv")
        log("CSV Import successful.")
    except Exception as e:
        log(f"CSV Import failed: {e}")
        return

    # 2. Modify Company Data (Sysco)
    cid = "sysco_labs_technologies_pvt_ltd"
    company = dm.get_company(cid)
    if not company:
        log(f"ERROR: Company {cid} not found after import.")
        return
    
    log(f"Found Company: {company.name}")
    
    # Create Panel 1 (12-1 Break)
    # We must use proper dataclasses if models.py defines them
    # But wait, earlier I checked and Panel is usually a dataclass or Pydantic model
    # Let's inspect what Panel is
    
    # Create Panel 1
    p1 = Panel(
        panel_id=f"{cid}-P1-DIRECT",
        label="Sysco Panel A",
        job_role_ids=[r.id for r in company.job_roles],
        slot_duration_minutes=30,
        reserved_walkin_slots=0,
        walk_in_open=False,
        breaks=[{"start": "12:00", "end": "13:00"}]
    )
    
    # Create Panel 2
    p2 = Panel(
        panel_id=f"{cid}-P2-DIRECT",
        label="Sysco Panel B",
        job_role_ids=[r.id for r in company.job_roles],
        slot_duration_minutes=30,
        reserved_walkin_slots=0,
        walk_in_open=False,
        breaks=[{"start": "13:00", "end": "14:00"}]
    )
    
    company.panels = [p1, p2]
    company.num_panels = 2
    log("Configured Sysco with 2 panels & staggered breaks.")
    
    # Save this back to DM? 
    # DataManager might cache companies. 
    # But dm.save_companies([company]) logic needed?
    # DM doesn't have save_companies public method usually exposed in this way, 
    # but Scheduler takes DM as input.
    # Actually, Scheduler(dm) usually calls dm.load_companies().
    # So we need to save the modified company to disk or inject it.
    # Let's check Scheduler init.
    # Scheduler(dm) -> self.companies = dm.load_companies()
    
    # So we need to save our changes to disk before initializing Scheduler
    # OR we can just instantiate Scheduler and then overwrite scheduler.companies
    
    scheduler = Scheduler(dm)
    # Overwrite the company in scheduler's memory
    for i, c in enumerate(scheduler.companies):
        if c.id == cid:
            scheduler.companies[i] = company
            break
            
    # 3. Run Scheduler
    log("Running Scheduler...")
    event_date = "2026-02-20"
    interviews = scheduler.run(event_date)
    log(f"Scheduler finished. Generated {len(interviews)} interviews.")
    
    # 4. Verify Results
    sysco_interviews = [i for i in interviews if i.company_id == cid]
    log(f"Sysco Interviews: {len(sysco_interviews)}")
    
    failures = 0
    p1_count = 0
    p2_count = 0
    
    for iv in sysco_interviews:
        # iv is an Interview object (dataclass or dict? likely dataclass)
        start_time = iv.start_time.split("T")[1][:5]
        h, m = map(int, start_time.split(':'))
        start_min = h * 60 + m
        
        pid = iv.panel_id
        
        if pid == p1.panel_id:
            p1_count += 1
            if 720 <= start_min < 780:
                log(f"FAILURE: Panel A interview at {start_time}")
                failures += 1
        elif pid == p2.panel_id:
            p2_count += 1
            if 780 <= start_min < 840:
                log(f"FAILURE: Panel B interview at {start_time}")
                failures += 1
    
    log(f"Panel A Count: {p1_count}")
    log(f"Panel B Count: {p2_count}")
    
    if failures == 0:
        log("SUCCESS: Staggered lunch breaks respected.")
    else:
        log(f"FAILURE: {failures} overlaps found.")

if __name__ == "__main__":
    run_test()
