import requests
import json
from datetime import datetime

try:
    r = requests.get('http://localhost:8000/api/live-queue')
    data = r.json()
    print(f"Status Code: {r.status_code}")
    print(f"Data Items: {len(data)}")
    
    # Check for INT-1
    for c in data:
        for p in c['panels']:
            if p['current']:
                print(f"  Panel {p['panel_id']} CURRENT: {p['current']['interview_id']} ({p['current']['status']})")
            if p['next']:
                print(f"  Panel {p['panel_id']} NEXT: {[x['interview_id'] for x in p['next']]}")
    
    print("\nRaw Data Snippet (first company):")
    print(json.dumps(data[0] if data else {}, indent=2))

except Exception as e:
    print(f"Error: {e}")
