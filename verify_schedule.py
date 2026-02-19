# THIS FILE IS NOT REQUIRED FOR THE MAIN APPLICATION
# It was created solely for verification purposes.
#
# import urllib.request
# import json
# import sys
#
# def verify():
#     base_url = "http://localhost:8000"
#     
#     print(f"Testing {base_url}...")
#     
#     # 1. Check if server is up (GET /)
#     try:
#         with urllib.request.urlopen(base_url) as response:
#             status = response.getcode()
#             print(f"Server Status: {status}")
#             if status != 200:
#                 print("Failed to reach server page.")
#                 sys.exit(1)
#     except Exception as e:
#         print(f"Server not reachable: {e}")
#         sys.exit(1)
#
#     # 2. Trigger Schedule Generation (POST /api/run-schedule)
#     print("Triggering schedule generation...")
#     try:
#         req = urllib.request.Request(f"{base_url}/api/run-schedule", method="POST")
#         with urllib.request.urlopen(req) as response:
#             status = response.getcode()
#             print(f"API Status: {status}")
#             data = json.loads(response.read().decode())
#             print(f"Response: {json.dumps(data, indent=2)}")
#             
#             if data.get("status") == "error":
#                 print("Scheduling failed!")
#                 sys.exit(1)
#                 
#             count = data.get("count", 0)
#             if count > 0:
#                 print(f"SUCCESS: Scheduled {count} interviews.")
#             else:
#                 print("WARNING: Scheduled 0 interviews (might be data issue or logic).")
#             
#     except Exception as e:
#         print(f"API call failed: {e}")
#         sys.exit(1)
#
# if __name__ == "__main__":
#     verify()
