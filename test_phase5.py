import requests
import json
import sys

BASE_URL = "http://localhost:8000"

def log(msg):
    print(f"[TEST] {msg}")

def run_test():
    # 1. Reset data
    log("Resetting data...")
    requests.post(f"{BASE_URL}/api/init")
    
    # 2. Configure a break for a company
    # We'll use 'sysco_labs_technologies_pvt_ltd'
    cid = "sysco_labs_technologies_pvt_ltd"
    
    # Get current settings
    r = requests.get(f"{BASE_URL}/api/company/{cid}")
    company = r.json()
    
    # Set a break from 13:00 to 14:00
    company["breaks"] = [{"start": "13:00", "end": "14:00"}]
    
    # Ensure it has panels and we treat them correctly.
    # The scheduler respects panel breaks. If panel breaks empty, uses company breaks.
    # Let's set a specific break for Panel 1 if it exists, else just company.
    if company.get("panels"):
        # Set Panel 1 break to 12:00-13:00 to start earlier
        company["panels"][0]["breaks"] = [{"start": "12:00", "end": "13:00"}]
        log("Setting Panel 1 break: 12:00-13:00")
    else:
        log("Setting Company break: 13:00-14:00")

    # Save settings
    log("Saving company settings...")
    r = requests.post(f"{BASE_URL}/api/company/{cid}/settings", json=company)
    if r.status_code != 200:
        log(f"Failed to save settings: {r.text}")
        return

    # 3. Run Schedule
    log("Running scheduler...")
    r = requests.post(f"{BASE_URL}/api/run-schedule", json={"event_date": "2026-02-20"})
    if r.status_code != 200:
        log(f"Scheduling failed: {r.text}")
        return

    # 4. Verify
    log("Verifying schedule...")
    r = requests.get(f"{BASE_URL}/api/schedule")
    schedule = r.json()
    
    # Filter for target company
    interviews = [i for i in schedule if i["company_id"] == cid]
    overlaps = 0
    
    # Define break window in minutes
    # If panel 1: 12:00 (720) - 13:00 (780)
    # If company: 13:00 (780) - 14:00 (840)
    
    # We need to know which break applies to which interview.
    # But for this test, we know what we set.
    
    for iv in interviews:
        pid = iv.get("panel_id")
        start_time = iv["start_time"].split("T")[1][:5] # HH:MM
        end_time = iv["end_time"].split("T")[1][:5]
        
        # Convert to minutes
        h, m = map(int, start_time.split(':'))
        start_min = h * 60 + m
        h, m = map(int, end_time.split(':'))
        end_min = h * 60 + m
        
        # Check against Panel 1 break (12:00-13:00)
        # Assuming only 1 panel for simplicity of this verification or checking pid.
        
        # Break range
        b_start, b_end = (720, 780) if company.get("panels") else (780, 840)
        
        # Check overlap: max(start, b_start) < min(end, b_end)
        if max(start_min, b_start) < min(end_min, b_end):
            log(f"FAILURE: Interview {iv['id']} at {start_time}-{end_time} overlaps with break!")
            overlaps += 1
            
    if overlaps == 0:
        log("SUCCESS: No interviews scheduled during break.")
    else:
        log(f"FAILURE: {overlaps} interviews overlapped with break.")

if __name__ == "__main__":
    run_test()
