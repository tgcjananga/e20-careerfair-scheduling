import requests
import json
import sys
import time

BASE_URL = "http://127.0.0.1:8000"

def log(msg):
    print(f"[TEST] {msg}")

def run_test():
    log("Starting verification...")
    # 1. Reset data
    log("Resetting data (POST /api/init)...")
    try:
        r = requests.post(f"{BASE_URL}/api/init", timeout=10)
        if r.status_code != 200:
            log(f"Reset failed: {r.text}")
            return
        log("Reset complete.")
    except requests.exceptions.RequestException as e:
        log(f"Reset connection error: {e}")
        return

    # 2. Load from CSV (As requested)
    log("Loading data from CSV (POST /api/import-responses)...")
    try:
        r = requests.post(f"{BASE_URL}/api/import-responses", timeout=30)
        if r.status_code != 200:
            log(f"CSV Import failed: {r.text}")
            return
        log(f"Import result: {r.json().get('message')}")
    except requests.exceptions.RequestException as e:
        log(f"Import error: {e}")
        return
    
    cid = "sysco_labs_technologies_pvt_ltd"
    
    # 3. Get current company data (to get roles)
    log(f"Fetching company {cid} (GET /api/company/{cid})...")
    try:
        r = requests.get(f"{BASE_URL}/api/company/{cid}", timeout=10)
        if r.status_code != 200:
            log("Failed to fetch company - it might not exist in the CSV data?")
            return
        company = r.json()
    except requests.exceptions.RequestException as e:
        log(f"Fetch company error: {e}")
        return
    
    # 4. Add Panels with Staggered Breaks
    # Create Panel 1 (Sysco Panel A) - Break 12:00-13:00
    p1 = {
        "panel_id": f"{cid}-P1-TEST-CSV",
        "label": "Sysco Panel A",
        "job_role_ids": [r["id"] for r in company["job_roles"]], # All roles
        "slot_duration_minutes": 30,
        "reserved_walkin_slots": 0,
        "walk_in_open": False,
        "breaks": [{"start": "12:00", "end": "13:00"}]
    }
    
    # Create Panel 2 (Sysco Panel B) - Break 13:00-14:00
    p2 = {
        "panel_id": f"{cid}-P2-TEST-CSV",
        "label": "Sysco Panel B",
        "job_role_ids": [r["id"] for r in company["job_roles"]],
        "slot_duration_minutes": 30,
        "reserved_walkin_slots": 0,
        "walk_in_open": False,
        "breaks": [{"start": "13:00", "end": "14:00"}]
    }
    
    # We overwrite existing panels or append?
    # Logic in server: company.panels = new_panels
    # So we replace whatever was there (likely default panel) with our 2 test panels.
    company["panels"] = [p1, p2]
    company["num_panels"] = 2
    
    # Save settings
    log("Updating company with 2 panels & staggered breaks...")
    r = requests.post(f"{BASE_URL}/api/company/{cid}/settings", json=company)
    if r.status_code != 200:
        log(f"Failed to save settings: {r.text}")
        return

    # 5. Run Schedule
    log("Running scheduler (Timeout 120s)...")
    try:
        r = requests.post(f"{BASE_URL}/api/run-schedule", json={"event_date": "2026-02-20"}, timeout=120)
        if r.status_code != 200:
            log(f"Scheduling failed: {r.text}")
            return
        log(f"Scheduling complete: {r.json().get('message')}")
    except requests.exceptions.Timeout:
        log("Scheduling timed out after 120s")
        return
    except requests.exceptions.RequestException as e:
        log(f"Scheduling error: {e}")
        return

    # 6. Verify Results
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
        
        h, m = map(int, start_time.split(':'))
        start_min = h * 60 + m
        
        if pid == p1["panel_id"]:
            p1_count += 1
            if 720 <= start_min < 780:
                log(f"FAILURE: Panel A interview at {start_time}")
                failures += 1
        elif pid == p2["panel_id"]:
            p2_count += 1
            if 780 <= start_min < 840:
                log(f"FAILURE: Panel B interview at {start_time}")
                failures += 1
            
    log(f"Panel A Interviews: {p1_count}")
    log(f"Panel B Interviews: {p2_count}")
    
    if failures == 0:
        log("SUCCESS: Staggered lunch breaks respected. No overlaps found.")
    else:
        log(f"FAILURE: {failures} interviews overlapped with breaks.")

if __name__ == "__main__":
    run_test()
