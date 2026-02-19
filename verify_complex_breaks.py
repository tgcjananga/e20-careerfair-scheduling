import requests
import json
import sys
import time

BASE_URL = "http://localhost:8000"

def log(msg):
    print(f"[TEST] {msg}")

def run_test():
    log("Waiting 5s for server to stabilize...")
    time.sleep(5)
    
    # 1. Reset data to clean state
    log("Resetting data...")
    try:
        requests.post(f"{BASE_URL}/api/init")
    except requests.exceptions.ConnectionError:
        log("Connection refused. Server might not be running.")
        return
    
    cid = "sysco_labs_technologies_pvt_ltd"
    
    # 2. Get current company data
    log(f"Fetching company {cid}...")
    r = requests.get(f"{BASE_URL}/api/company/{cid}")
    if r.status_code != 200:
        log("Failed to fetch company")
        return
    company = r.json()
    
    # 3. Add a second panel (Simulate UI adding panel)
    # Current panels usually empty or 1 default. Let's ensure we have 2 specific panels.
    
    # Create Panel 1 (Sysco Panel A) - Break 12:00-13:00
    p1 = {
        "panel_id": f"{cid}-P1-TEST-123", # Fixed ID for test consistency
        "label": "Sysco Panel A",
        "job_role_ids": [r["id"] for r in company["job_roles"]], # All roles
        "slot_duration_minutes": 30,
        "reserved_walkin_slots": 0,
        "walk_in_open": False,
        "breaks": [{"start": "12:00", "end": "13:00"}]
    }
    
    # Create Panel 2 (Sysco Panel B) - Break 13:00-14:00
    p2 = {
        "panel_id": f"{cid}-P2-TEST-456",
        "label": "Sysco Panel B",
        "job_role_ids": [r["id"] for r in company["job_roles"]],
        "slot_duration_minutes": 30,
        "reserved_walkin_slots": 0,
        "walk_in_open": False,
        "breaks": [{"start": "13:00", "end": "14:00"}]
    }
    
    company["panels"] = [p1, p2]
    company["num_panels"] = 2
    
    # Save settings
    log("Updating company with 2 panels & staggered breaks...")
    r = requests.post(f"{BASE_URL}/api/company/{cid}/settings", json=company)
    if r.status_code != 200:
        log(f"Failed to save settings: {r.text}")
        return

    # 4. Run Schedule
    log("Running scheduler...")
    r = requests.post(f"{BASE_URL}/api/run-schedule", json={"event_date": "2026-02-20"})
    if r.status_code != 200:
        log(f"Scheduling failed: {r.text}")
        return

    # 5. Verify Results
    log("Verifying schedule...")
    r = requests.get(f"{BASE_URL}/api/schedule")
    schedule = r.json()
    
    sysco_interviews = [i for i in schedule if i["company_id"] == cid]
    log(f"Found {len(sysco_interviews)} interviews for Sysco.")
    
    failures = 0
    p1_count = 0
    p2_count = 0
    
    for iv in sysco_interviews:
        pid = iv.get("panel_id")
        start_time = iv["start_time"].split("T")[1][:5] # HH:MM
        
        # Convert to minutes for easy comparison
        h, m = map(int, start_time.split(':'))
        start_min = h * 60 + m
        
        # Ranges
        # 12:00-13:00 is 720-780
        # 13:00-14:00 is 780-840
        
        if pid == p1["panel_id"]:
            p1_count += 1
            if 720 <= start_min < 780:
                log(f"FAILURE: Panel A interview at {start_time} (Inside 12:00-13:00 break)")
                failures += 1
        elif pid == p2["panel_id"]:
            p2_count += 1
            if 780 <= start_min < 840:
                log(f"FAILURE: Panel B interview at {start_time} (Inside 13:00-14:00 break)")
                failures += 1
        else:
            log(f"WARNING: Unknown panel ID {pid}")
            
    log(f"Panel A Interviews: {p1_count}")
    log(f"Panel B Interviews: {p2_count}")
    
    if failures == 0:
        log("SUCCESS: Staggered lunch breaks respected. No overlaps found.")
    else:
        log(f"FAILURE: {failures} interviews overlapped with breaks.")

if __name__ == "__main__":
    run_test()
