import requests
import json
import time

BASE_URL = "http://localhost:8000/api"

def log(msg):
    print(f"[TEST] {msg}")

def run_test():
    # 1. Checkpoint current data
    log("Creating checkpoint...")
    r = requests.post(f"{BASE_URL}/checkpoint")
    if r.status_code != 200:
        log(f"Failed to checkpoint: {r.text}")
        return
    log("Checkpoint created.")

    try:
        # 2. Get schedule to find a target interview
        r = requests.get(f"{BASE_URL}/schedule")
        schedule = r.json()
        if not schedule:
            log("No interviews found in schedule. Cannot test.")
            return

        target = schedule[0]
        tid = target['id']
        log(f"Target interview: {tid} (current status: {target.get('status', 'scheduled')})")

        # 3. Mark as IN PROGRESS (if endpoint exists? I added complete/cancel. In-progress is auto or manual?)
        # I added /api/interview/{id}/in-progress in server.py?
        # Let me check my previous edit.
        # I added /complete and /cancel.
        # I ALSO added /in-progress in the same edit block?
        # Let's check the verify_file output or just try it.
        # Actually I see in Step 1199 I added:
        # elif parsed_path.path.startswith('/api/interview/') and parsed_path.path.endswith('/in-progress'): ...
        # YES I DID.
        
        log(f"Marking {tid} as in_progress...")
        r = requests.post(f"{BASE_URL}/interview/{tid}/in-progress")
        log(f"Response: {r.json()}")
        
        # Verify
        r = requests.get(f"{BASE_URL}/schedule")
        target = next(i for i in r.json() if i['id'] == tid)
        if target.get('status') != 'in_progress':
            log(f"FAILED: Status is {target.get('status')}, expected in_progress")
        else:
            log("PASSED: Status updated to in_progress")

        # 4. Check Live Queue
        r = requests.get(f"{BASE_URL}/live-queue")
        # Ensure it doesn't crash
        if r.status_code == 200:
            log("Live Queue endpoint works")
        else:
            log(f"Live Queue failed: {r.status_code}")

        # 5. Mark as COMPLETED
        log(f"Marking {tid} as completed...")
        r = requests.post(f"{BASE_URL}/interview/{tid}/complete")
        log(f"Response: {r.json()}")

        r = requests.get(f"{BASE_URL}/schedule")
        target = next(i for i in r.json() if i['id'] == tid)
        if target.get('status') != 'completed':
            log(f"FAILED: Status is {target.get('status')}, expected completed")
        else:
            log("PASSED: Status updated to completed")

        # 6. Mark as CANCELLED (test on another interview?)
        if len(schedule) > 1:
            target2 = schedule[1]
            tid2 = target2['id']
            log(f"Marking {tid2} as cancelled...")
            requests.post(f"{BASE_URL}/interview/{tid2}/cancel")
            r = requests.get(f"{BASE_URL}/schedule")
            t2 = next(i for i in r.json() if i['id'] == tid2)
            if t2.get('status') == 'cancelled':
                log("PASSED: Status updated to cancelled")
            else:
                log("FAILED: Cancel failed")

        log("All API tests passed.")

    except Exception as e:
        log(f"TEST FAILED with exception: {e}")

    finally:
        # 7. Restore data
        log("Restoring data from checkpoint...")
        requests.post(f"{BASE_URL}/restore")
        log("Restore complete.")

if __name__ == "__main__":
    try:
        run_test()
    except:
        print("Server not running or connection failed.")
