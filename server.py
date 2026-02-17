import http.server
import socketserver
import json
import os
from urllib.parse import urlparse, parse_qs
from dataclasses import asdict

from schedule_manager.data_manager import DataManager, Interview
from schedule_manager.scheduler import Scheduler
from schedule_manager.reporting import generate_html_report
from seed_data import seed

PORT = 8000
WEB_DIR = os.path.join(os.path.dirname(__file__), 'web')

class InterviewRequestHandler(http.server.SimpleHTTPRequestHandler):
    
    def do_GET(self):
        # API Endpoints
        if self.path.startswith('/api/export/'):
            self.handle_api_export()
            return
        if self.path.startswith('/api/'):
            self.handle_api_get()
            return

        # Static File Serving (Root -> index.html)
        if self.path == '/':
            self.path = '/web/index.html'
        elif not self.path.startswith('/web/'):
            self.path = '/web' + self.path
            
        return super().do_GET()

    def handle_api_export(self):
        dm = DataManager()
        parsed = urlparse(self.path)
        path_parts = parsed.path.split('/')
        # /api/export/[type]/[id?]
        
        export_type = path_parts[3] if len(path_parts) > 3 else None
        target_id = path_parts[4] if len(path_parts) > 4 else None
        
        # Load Data
        companies = {c.id: c for c in dm.load_companies()}
        students = {s.id: s for s in dm.load_students()}
        
        schedule_path = "schedule_manager/data/schedule.json"
        interviews = []
        if os.path.exists(schedule_path):
            with open(schedule_path, 'r') as f:
                data = json.load(f)
                interviews = [Interview(**i) for i in data]

        csv_content = ""
        filename = "export.csv"
        
        if export_type == "companies":
            csv_content = "Company ID,Company Name,Time,Student ID,Student Name,Role\n"
            filename = "all_companies_schedule.csv"
            
            # Sort by Company then Time
            interviews.sort(key=lambda x: (x.company_id, x.start_time))
            
            for i in interviews:
                c = companies.get(i.company_id)
                s = students.get(i.student_id)
                c_name = c.name if c else i.company_id
                s_name = s.name if s else i.student_id
                time_str = i.start_time.split('T')[1][:5]
                
                csv_content += f"{i.company_id},{c_name},{time_str},{i.student_id},{s_name},{i.job_role_id}\n"

        elif export_type == "students":
            csv_content = "Student ID,Student Name,Time,Company,Role\n"
            filename = "all_students_schedule.csv"
            
            interviews.sort(key=lambda x: (x.student_id, x.start_time))
            
            for i in interviews:
                c = companies.get(i.company_id)
                s = students.get(i.student_id)
                c_name = c.name if c else i.company_id
                s_name = s.name if s else i.student_id
                time_str = i.start_time.split('T')[1][:5]
                
                csv_content += f"{i.student_id},{s_name},{time_str},{c_name},{i.job_role_id}\n"
                
        elif export_type == "company" and target_id:
            c = companies.get(target_id)
            c_name = c.name if c else target_id
            filename = f"schedule_{target_id}.csv"
            csv_content = f"Schedule for {c_name}\nTime,Student ID,Student Name,Role\n"
            
            company_interviews = [i for i in interviews if i.company_id == target_id]
            company_interviews.sort(key=lambda x: x.start_time)
            
            for i in company_interviews:
                s = students.get(i.student_id)
                s_name = s.name if s else i.student_id
                time_str = i.start_time.split('T')[1][:5]
                csv_content += f"{time_str},{i.student_id},{s_name},{i.job_role_id}\n"

        elif export_type == "student" and target_id:
            s = students.get(target_id)
            s_name = s.name if s else target_id
            filename = f"schedule_{target_id}.csv"
            csv_content = f"Schedule for {s_name}\nTime,Company,Role\n"
            
            student_interviews = [i for i in interviews if i.student_id == target_id]
            student_interviews.sort(key=lambda x: x.start_time)
            
            for i in student_interviews:
                c = companies.get(i.company_id)
                c_name = c.name if c else i.company_id
                time_str = i.start_time.split('T')[1][:5]
                csv_content += f"{time_str},{c_name},{i.job_role_id}\n"

        self.send_response(200)
        self.send_header('Content-type', 'text/csv')
        self.send_header('Content-Disposition', f'attachment; filename="{filename}"')
        self.end_headers()
        self.wfile.write(csv_content.encode('utf-8'))

    def do_POST(self):
        if self.path.startswith('/api/'):
            self.handle_api_post()
        else:
            self.send_error(404)

    def handle_api_get(self):
        dm = DataManager()
        parsed_path = urlparse(self.path)
        
        response_data = {}
        
        if parsed_path.path == '/api/companies':
            companies = dm.load_companies()
            # We also want the interviews to show schedule
            # Ideally we have a better data structure, but for now:
            # We can load the schedule.json if it exists
            # Or we can just return companies and let frontend fetch schedule separately
            response_data = [asdict(c) for c in companies]
            
        elif parsed_path.path == '/api/students':
            students = dm.load_students()
            response_data = [asdict(s) for s in students]
            
        elif parsed_path.path == '/api/schedule':
            interviews = []
            schedule_path = "schedule_manager/data/schedule.json"
            if os.path.exists(schedule_path):
                with open(schedule_path, 'r') as f:
                    interviews = json.load(f)
            response_data = interviews

        self.send_json(response_data)

    def handle_api_post(self):
        dm = DataManager()
        parsed_path = urlparse(self.path)
        
        response_data = {"status": "success"}
        
        if parsed_path.path == '/api/init':
            seed()
            response_data["message"] = "Data reset to seed values."
            
        elif parsed_path.path == '/api/run-schedule':
            scheduler = Scheduler(dm)
            interviews = scheduler.run("2024-10-25")
            
            # Save schedule
            with open("schedule_manager/data/schedule.json", "w") as f:
                json.dump([asdict(i) for i in interviews], f, indent=2)
                
            response_data["message"] = f"Scheduled {len(interviews)} interviews."
            response_data["count"] = len(interviews)

        self.send_json(response_data)

    def send_json(self, data):
        self.send_response(200)
        self.send_header('Content-type', 'application/json')
        self.end_headers()
        self.wfile.write(json.dumps(data).encode('utf-8'))

if __name__ == "__main__":
    # Ensure data directory exists
    DataManager() 
    
    print(f"Starting Web Server at http://localhost:{PORT}")
    print("Press Ctrl+C to stop.")
    
    # Allow address reuse
    socketserver.TCPServer.allow_reuse_address = True
    
    with socketserver.TCPServer(("", PORT), InterviewRequestHandler) as httpd:
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\nStopping server...")
            httpd.shutdown()
