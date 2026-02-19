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

        elif parsed_path.path.startswith('/api/company/') and not parsed_path.path.endswith('/panels') and not parsed_path.path.endswith('/settings'):
            company_id = parsed_path.path.split('/api/company/')[1].strip('/')
            company = dm.get_company(company_id)
            if company is None:
                self.send_response(404)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps({"error": "Company not found"}).encode())
                return
            from dataclasses import asdict as _asdict
            c_dict = _asdict(company)
            # Auto-create default panel if none exist
            if not c_dict['panels']:
                c_dict['panels'] = [{
                    "panel_id": f"{company.id}-P1",
                    "label": "Panel 1 (Default)",
                    "job_role_ids": [r.id for r in company.job_roles],
                    "slot_duration_minutes": 30,
                    "walk_in_open": company.walk_in_open,
                    "reserved_walkin_slots": 0
                }]
            response_data = c_dict

        elif parsed_path.path == '/api/live-queue':
            from datetime import datetime
            companies = dm.load_companies()
            students_list = dm.load_students()
            student_map = {s.id: s for s in students_list}

            # Load role title lookup: {job_role_id: title}
            role_map = {}
            for c in companies:
                for r in c.job_roles:
                    role_map[r.id] = r.title

            # Load schedule
            schedule_path = "schedule_manager/data/schedule.json"
            raw_interviews = []
            if os.path.exists(schedule_path):
                with open(schedule_path, 'r') as f:
                    raw_interviews = json.load(f)

            now = datetime.now()

            def make_entry(iv):
                s = student_map.get(iv['student_id'])
                return {
                    "interview_id": iv['id'],
                    "student_id": iv['student_id'],
                    "student_name": s.name if s else iv['student_id'],
                    "start_time": iv['start_time'].split('T')[1][:5] if 'T' in iv['start_time'] else iv['start_time'],
                    "end_time": iv['end_time'].split('T')[1][:5] if 'T' in iv['end_time'] else iv['end_time'],
                    "role": role_map.get(iv['job_role_id'], iv['job_role_id']),
                    "status": iv.get('status', 'scheduled'),  # Phase 3
                }

            result = []
            for c in companies:
                # Filter interviews for this company
                c_ivs = [iv for iv in raw_interviews if iv['company_id'] == c.id]
                c_ivs.sort(key=lambda x: x['start_time'])

                # Group by panel_id (defaults to "default" for old schedules)
                panels_dict = {}
                for iv in c_ivs:
                    pid = iv.get('panel_id', 'default')
                    if pid not in panels_dict:
                        panels_dict[pid] = []
                    panels_dict[pid].append(iv)

                # If no interviews at all, still show one empty panel
                if not panels_dict:
                    panels_dict['default'] = []

                panels_out = []
                for pid, ivs in panels_dict.items():
                    # Determine label from company panels config
                    panel_label = "Panel 1"
                    for p in c.panels:
                        if p.panel_id == pid:
                            panel_label = p.label
                            break
                    if pid == 'default' and not c.panels:
                        panel_label = "Panel 1"

                    # Find current, next1, next2
                    # Phase 3: use status field if set; fallback to time-based
                    current = None
                    upcoming = []
                    past_candidates = []

                    for iv in ivs:
                        iv_status = iv.get('status', 'scheduled')
                        if iv_status in ('cancelled'):
                            continue  # skip cancelled (deleted) interviews completely? 
                            # User might want to see previous even if cancelled? No, usually not.
                            # But if they want to Complete a 'scheduled' one that expired.
                            # If status is 'completed', we might still want to show it as "Previous: Done".
                        
                        # Note: we need to parse times even for completed ones now to find the "previous" one.
                        try:
                            start_dt = datetime.fromisoformat(iv['start_time'])
                            end_dt = datetime.fromisoformat(iv['end_time'])
                            
                            # Check for Current
                            # If we manually set in_progress, it takes precedence for "current"
                            if iv_status == 'in_progress':
                                current = make_entry(iv)
                            
                            # Check time-based
                            elif start_dt <= now < end_dt:
                                # Overwrite current if multiple match (last wins), unless one is specifically in_progress? 
                                # Let's assume time-based match is valid 'current' if no explicit in_progress exists
                                if not current or current['status'] != 'in_progress':
                                    current = make_entry(iv)
                            
                            elif start_dt > now:
                                upcoming.append(iv)
                            
                            elif end_dt <= now:
                                past_candidates.append(iv)
                                
                        except Exception:
                            pass

                    # Sort past candidates by end_time ascending, so the last one is the most recent
                    past_candidates.sort(key=lambda x: x['end_time'])
                    previous = make_entry(past_candidates[-1]) if past_candidates else None

                    panels_out.append({
                        "panel_id": pid,
                        "panel_label": panel_label,
                        "previous": previous,
                        "current": current,
                        "next": [make_entry(iv) for iv in upcoming[:2]]
                    })

                result.append({
                    "company_id": c.id,
                    "company_name": c.name,
                    "panels": panels_out
                })

            response_data = result

        elif parsed_path.path == '/api/admin-summary':

            from datetime import datetime, date
            companies = dm.load_companies()
            interviews = []
            schedule_path = "schedule_manager/data/schedule.json"
            if os.path.exists(schedule_path):
                with open(schedule_path, 'r') as f:
                    interviews = json.load(f)

            # Read saved event_date from config (set when schedule was last run)
            config_path = "schedule_manager/data/config.json"
            event_date_str = date.today().strftime('%Y-%m-%d')
            if os.path.exists(config_path):
                with open(config_path, 'r') as f:
                    cfg = json.load(f)
                    event_date_str = cfg.get('event_date', event_date_str)

            now = datetime.now()
            summary = []
            for c in companies:
                company_interviews = [i for i in interviews if i['company_id'] == c.id]
                company_interviews.sort(key=lambda x: x['start_time'])

                # Determine interview window from schedule
                if company_interviews:
                    interview_start = company_interviews[0]['start_time'].split('T')[1][:5]
                    interview_end = company_interviews[-1]['end_time'].split('T')[1][:5]
                else:
                    interview_start = "09:00"
                    interview_end = "17:00"

                # Find next upcoming interview
                next_interview = None
                for i in company_interviews:
                    try:
                        slot_dt = datetime.fromisoformat(i['start_time'])
                        if slot_dt > now:
                            next_interview = i['start_time'].split('T')[1][:5]
                            break
                    except Exception:
                        pass

                # Estimate remaining capacity using event_date
                from datetime import timedelta
                try:
                    day_start = datetime.strptime(f"{event_date_str} 09:00", "%Y-%m-%d %H:%M")
                    day_end = datetime.strptime(f"{event_date_str} 17:00", "%Y-%m-%d %H:%M")
                    total_slots = int((day_end - day_start).seconds / 60 / 30)
                    total_capacity = total_slots * c.num_panels
                    # On the event day, count only future slots
                    if now.strftime('%Y-%m-%d') == event_date_str:
                        elapsed_minutes = max(0, (now - day_start).seconds // 60)
                        elapsed_slots = elapsed_minutes // 30
                        remaining_total = max(0, total_slots - elapsed_slots) * c.num_panels
                        slots_remaining = max(0, remaining_total - len([i for i in company_interviews
                            if datetime.fromisoformat(i['start_time']) >= now]))
                    else:
                        slots_remaining = max(0, total_capacity - len(company_interviews))
                except Exception:
                    slots_remaining = 0

                summary.append({
                    "id": c.id,
                    "name": c.name,
                    "num_panels": c.num_panels,
                    "walk_in_open": c.walk_in_open,
                    "positions": [r.title for r in c.job_roles],
                    "interview_start": interview_start,
                    "interview_end": interview_end,
                    "total_scheduled": len(company_interviews),
                    "next_interview_at": next_interview,
                    "slots_remaining_today": slots_remaining
                })
            response_data = summary

        elif parsed_path.path == '/api/statistics':
            students_path  = "schedule_manager/data/students.json"
            companies_path = "schedule_manager/data/companies.json"
            schedule_path  = "schedule_manager/data/schedule.json"
            students_data, companies_data, interviews_data = [], [], []
            if os.path.exists(students_path):
                with open(students_path) as f: students_data  = json.load(f)
            if os.path.exists(companies_path):
                with open(companies_path) as f: companies_data = json.load(f)
            if os.path.exists(schedule_path):
                with open(schedule_path)  as f: interviews_data = json.load(f)

            total_students = len(students_data)
            total_applications = 0
            shortlisted_apps   = 0
            shortlisted_students = 0
            walkin_students      = 0
            for s in students_data:
                apps = s.get("applications", [])
                total_applications += len(apps)
                cnt = sum(1 for a in apps if a.get("status") == "shortlisted")
                shortlisted_apps += cnt
                if cnt > 0:
                    shortlisted_students += 1
                else:
                    walkin_students += 1

            walkin_enabled = sum(1 for c in companies_data if c.get("walk_in_open", False))
            total_reserved = sum(
                p.get("reserved_walkin_slots", 0)
                for c in companies_data for p in c.get("panels", [])
            )

            walkin_student_list = sorted(
                [{"id": s["id"], "name": s.get("name", ""), "email": s.get("email", ""),
                  "application_count": len(s.get("applications", []))}
                 for s in students_data
                 if not any(a.get("status") == "shortlisted" for a in s.get("applications", []))],
                key=lambda x: x["name"]
            )

            company_names = {c["id"]: c["name"] for c in companies_data}
            breakdown = {}
            for s in students_data:
                for a in s.get("applications", []):
                    cid = a.get("company_id")
                    if cid not in breakdown:
                        breakdown[cid] = {"shortlisted": 0, "applied": 0}
                    if a.get("status") == "shortlisted":
                        breakdown[cid]["shortlisted"] += 1
                    else:
                        breakdown[cid]["applied"] += 1
            breakdown_list = sorted(
                [{"company_id": cid, "company_name": company_names.get(cid, cid),
                  "shortlisted": v["shortlisted"], "applied": v["applied"]}
                 for cid, v in breakdown.items()],
                key=lambda x: -x["shortlisted"]
            )
            response_data = {
                "students":      {"total": total_students, "shortlisted": shortlisted_students,
                                   "walkin_candidates": walkin_students},
                "applications":  {"total": total_applications, "shortlisted": shortlisted_apps,
                                   "applied": total_applications - shortlisted_apps},
                "companies":     {"total": len(companies_data), "walkin_enabled": walkin_enabled,
                                   "total_reserved_walkin_slots": total_reserved},
                "interviews":    {"total_scheduled": len(interviews_data)},
                "per_company":   breakdown_list,
                "walkin_students": walkin_student_list,
            }

        elif parsed_path.path == '/api/checkpoint-info':
            config_path = "schedule_manager/data/config.json"
            data_dir = "schedule_manager/data"
            cfg = {}
            if os.path.exists(config_path):
                with open(config_path, 'r') as f:
                    cfg = json.load(f)
            backup_files = ["companies", "students", "schedule"]
            backups_exist = {f: os.path.exists(f"{data_dir}/{f}.backup.json") for f in backup_files}
            response_data = {
                "last_checkpoint": cfg.get("last_checkpoint", None),
                "backups_exist": backups_exist
            }

        elif parsed_path.path == '/api/company-defaults':
            defaults_path = "schedule_manager/data/company_defaults.json"
            if os.path.exists(defaults_path):
                with open(defaults_path, 'r') as f:
                    response_data = json.load(f)
            else:
                response_data = {
                    "availability_start": "09:00",
                    "availability_end": "17:00",
                    "breaks": [],
                    "default_panel": {
                        "label": "Panel 1 (Default)",
                        "slot_duration_minutes": 30,
                        "reserved_walkin_slots": 0,
                        "walk_in_open": False,
                        "breaks": []
                    }
                }

        self.send_json(response_data)

    def handle_api_post(self):
        dm = DataManager()
        parsed_path = urlparse(self.path)
        
        response_data = {"status": "success"}
        
        if parsed_path.path == '/api/import-responses':
            csv_path = "Carrier Fair - 2026_responses.csv"
            try:
                if not os.path.exists(csv_path):
                    response_data["status"] = "error"
                    response_data["message"] = f"CSV file not found: {csv_path}"
                else:
                    from schedule_manager.response_importer import ResponseImporter
                    importer = ResponseImporter(dm)
                    importer.import_responses(csv_path)
                    # Reload counts
                    students = dm.load_students()
                    companies = dm.load_companies()
                    response_data["message"] = f"Imported {len(students)} students and {len(companies)} companies from CSV."
                    response_data["students"] = len(students)
                    response_data["companies"] = len(companies)
            except Exception as e:
                print(f"Error importing responses: {e}")
                response_data["status"] = "error"
                response_data["message"] = str(e)

        elif parsed_path.path == '/api/company-defaults':
            # POST /api/company-defaults — save the template applied to new companies on CSV import
            try:
                content_length = int(self.headers.get('Content-Length', 0))
                body = json.loads(self.rfile.read(content_length).decode('utf-8')) if content_length > 0 else {}
                defaults_path = "schedule_manager/data/company_defaults.json"
                with open(defaults_path, 'w') as f:
                    json.dump(body, f, indent=2)
                response_data["message"] = "Company defaults saved."
            except Exception as e:
                response_data["status"] = "error"
                response_data["message"] = str(e)

        elif parsed_path.path == '/api/init':
            seed()
            response_data["message"] = "Data reset to seed values."

        elif parsed_path.path == '/api/checkpoint':
            import shutil
            from datetime import datetime
            data_dir = "schedule_manager/data"
            config_path = f"{data_dir}/config.json"
            files_to_backup = ["companies.json", "students.json", "schedule.json"]
            backed_up = []
            try:
                for fname in files_to_backup:
                    src = f"{data_dir}/{fname}"
                    dst = f"{data_dir}/{fname.replace('.json', '.backup.json')}"
                    if os.path.exists(src):
                        shutil.copy2(src, dst)
                        backed_up.append(fname)
                # Record timestamp in config
                cfg = {}
                if os.path.exists(config_path):
                    with open(config_path, 'r') as f:
                        cfg = json.load(f)
                cfg["last_checkpoint"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                with open(config_path, 'w') as f:
                    json.dump(cfg, f, indent=2)
                response_data["message"] = f"Checkpoint saved: {', '.join(backed_up)}"
                response_data["timestamp"] = cfg["last_checkpoint"]
            except Exception as e:
                response_data["status"] = "error"
                response_data["message"] = str(e)

        elif parsed_path.path == '/api/restore':
            import shutil
            data_dir = "schedule_manager/data"
            config_path = f"{data_dir}/config.json"
            files_to_restore = ["companies.json", "students.json", "schedule.json"]
            restored = []
            missing = []
            try:
                for fname in files_to_restore:
                    src = f"{data_dir}/{fname.replace('.json', '.backup.json')}"
                    dst = f"{data_dir}/{fname}"
                    if os.path.exists(src):
                        shutil.copy2(src, dst)
                        restored.append(fname)
                    else:
                        missing.append(fname)
                # Get checkpoint timestamp
                checkpoint_ts = "unknown"
                if os.path.exists(config_path):
                    with open(config_path, 'r') as f:
                        cfg = json.load(f)
                        checkpoint_ts = cfg.get("last_checkpoint", "unknown")
                msg = f"Restored: {', '.join(restored)}"
                if missing:
                    msg += f" | No backup found for: {', '.join(missing)}"
                response_data["message"] = msg
                response_data["checkpoint_timestamp"] = checkpoint_ts
                response_data["restored"] = restored
                response_data["missing_backups"] = missing
            except Exception as e:
                response_data["status"] = "error"
                response_data["message"] = str(e)


        elif parsed_path.path.startswith('/api/interview/') and parsed_path.path.endswith('/complete'):
            # POST /api/interview/{id}/complete — mark interview as completed
            parts = parsed_path.path.split('/')
            interview_id = parts[3] if len(parts) >= 5 else None
            schedule_path = "schedule_manager/data/schedule.json"
            try:
                if not interview_id:
                    raise ValueError("Missing interview id")
                if not os.path.exists(schedule_path):
                    raise FileNotFoundError("schedule.json not found")
                with open(schedule_path, 'r') as f:
                    schedule = json.load(f)
                found = False
                for iv in schedule:
                    if iv['id'] == interview_id:
                        iv['status'] = 'completed'
                        found = True
                        break
                if not found:
                    raise ValueError(f"Interview {interview_id} not found")
                with open(schedule_path, 'w') as f:
                    json.dump(schedule, f, indent=2)
                response_data["message"] = f"Interview {interview_id} marked as completed."
                response_data["interview_id"] = interview_id
            except Exception as e:
                response_data["status"] = "error"
                response_data["message"] = str(e)

        elif parsed_path.path.startswith('/api/interview/') and parsed_path.path.endswith('/cancel'):
            # POST /api/interview/{id}/cancel — mark interview as cancelled
            parts = parsed_path.path.split('/')
            interview_id = parts[3] if len(parts) >= 5 else None
            schedule_path = "schedule_manager/data/schedule.json"
            try:
                if not interview_id:
                    raise ValueError("Missing interview id")
                if not os.path.exists(schedule_path):
                    raise FileNotFoundError("schedule.json not found")
                with open(schedule_path, 'r') as f:
                    schedule = json.load(f)
                found = False
                for iv in schedule:
                    if iv['id'] == interview_id:
                        iv['status'] = 'cancelled'
                        found = True
                        break
                if not found:
                    raise ValueError(f"Interview {interview_id} not found")
                with open(schedule_path, 'w') as f:
                    json.dump(schedule, f, indent=2)
                response_data["message"] = f"Interview {interview_id} cancelled."
                response_data["interview_id"] = interview_id
            except Exception as e:
                response_data["status"] = "error"
                response_data["message"] = str(e)

        elif parsed_path.path.startswith('/api/interview/') and parsed_path.path.endswith('/in-progress'):
            # POST /api/interview/{id}/in-progress — mark interview as in progress
            parts = parsed_path.path.split('/')
            interview_id = parts[3] if len(parts) >= 5 else None
            schedule_path = "schedule_manager/data/schedule.json"
            try:
                if not interview_id:
                    raise ValueError("Missing interview id")
                if not os.path.exists(schedule_path):
                    raise FileNotFoundError("schedule.json not found")
                with open(schedule_path, 'r') as f:
                    schedule = json.load(f)
                found = False
                for iv in schedule:
                    if iv['id'] == interview_id:
                        iv['status'] = 'in_progress'
                        found = True
                        break
                if not found:
                    raise ValueError(f"Interview {interview_id} not found")
                with open(schedule_path, 'w') as f:
                    json.dump(schedule, f, indent=2)
                response_data["message"] = f"Interview {interview_id} marked as in progress."
                response_data["interview_id"] = interview_id
            except Exception as e:
                response_data["status"] = "error"
                response_data["message"] = str(e)

        elif parsed_path.path == '/api/run-schedule':
            try:
                # Read event_date from POST body JSON, fallback to today
                content_length = int(self.headers.get('Content-Length', 0))
                body = {}
                if content_length > 0:
                    raw = self.rfile.read(content_length)
                    body = json.loads(raw.decode('utf-8'))
                from datetime import date
                event_date = body.get('event_date', date.today().strftime('%Y-%m-%d'))

                # Save event_date to config — read-merge-write to preserve last_checkpoint (Bug #3 fix)
                config_path = "schedule_manager/data/config.json"
                cfg = {}
                if os.path.exists(config_path):
                    with open(config_path, 'r') as f:
                        try:
                            cfg = json.load(f)
                        except Exception:
                            cfg = {}
                cfg["event_date"] = event_date
                with open(config_path, 'w') as f:
                    json.dump(cfg, f, indent=2)

                # The Scheduler now uses OR-Tools internally if available
                from schedule_manager.scheduler import Scheduler
                scheduler = Scheduler(dm)
                interviews = scheduler.run(event_date)
                
                # Check how many were scheduled to guess if it worked well
                msg = f"Scheduled {len(interviews)} interviews."
                if hasattr(scheduler, 'ORTOOLS_AVAILABLE') and not scheduler.ORTOOLS_AVAILABLE:
                     msg += " (Warning: OR-Tools not found, optimization disabled)"
                
                response_data["message"] = msg
                response_data["count"] = len(interviews)

                # Save schedule
                with open("schedule_manager/data/schedule.json", "w") as f:
                    json.dump([asdict(i) for i in interviews], f, indent=2)

            except Exception as e:
                print(f"Error running scheduler: {e}")
                response_data["status"] = "error"
                response_data["message"] = str(e)

        elif parsed_path.path.startswith('/api/toggle-walkin/'):
            path_parts = parsed_path.path.split('/')
            company_id = path_parts[3] if len(path_parts) > 3 else None
            if company_id:
                try:
                    companies = dm.load_companies()
                    for c in companies:
                        if c.id == company_id:
                            c.walk_in_open = not c.walk_in_open
                            response_data["walk_in_open"] = c.walk_in_open
                            response_data["message"] = f"Walk-in {'opened' if c.walk_in_open else 'closed'} for {c.name}"
                            break
                    dm.save_companies(companies)
                except Exception as e:
                    response_data["status"] = "error"
                    response_data["message"] = str(e)
            else:
                response_data["status"] = "error"
                response_data["message"] = "Company ID not provided"

        elif parsed_path.path.startswith('/api/company/') and parsed_path.path.endswith('/settings'):
            # POST /api/company/{id}/settings — save full company object
            company_id = parsed_path.path.split('/api/company/')[1].replace('/settings', '').strip('/')
            try:
                content_length = int(self.headers.get('Content-Length', 0))
                body = json.loads(self.rfile.read(content_length).decode('utf-8')) if content_length > 0 else {}
                company = dm.get_company(company_id)
                if company is None:
                    response_data["status"] = "error"
                    response_data["message"] = "Company not found"
                else:
                    company.availability_start = body.get('availability_start', company.availability_start)
                    company.availability_end = body.get('availability_end', company.availability_end)
                    company.breaks = body.get('breaks', company.breaks)
                    
                    # Update panels if provided
                    if "panels" in body:
                        raw_panels = body["panels"]
                        from schedule_manager.data_manager import Panel
                        new_panels = [Panel(**p) for p in raw_panels]
                        company.panels = new_panels
                        company.num_panels = len(new_panels) # Keep num_panels in sync for backward compat

                    dm.save_company(company)
                    response_data["status"] = "success"
                    response_data["message"] = f"Settings saved for {company.name}"
                    response_data["availability_start"] = company.availability_start
                    response_data["availability_end"] = company.availability_end
            except Exception as e:
                response_data["status"] = "error"
                response_data["message"] = str(e)

        elif parsed_path.path.startswith('/api/company/') and parsed_path.path.endswith('/panels'):
            # POST /api/company/{id}/panels — save all panels for a company (Bug #1 fix)
            company_id = parsed_path.path.split('/api/company/')[1].replace('/panels', '').strip('/')
            try:
                content_length = int(self.headers.get('Content-Length', 0))
                raw_panels = json.loads(self.rfile.read(content_length).decode('utf-8')) if content_length > 0 else []
                company = dm.get_company(company_id)
                if company is None:
                    response_data["status"] = "error"
                    response_data["message"] = "Company not found"
                else:
                    from schedule_manager.data_manager import Panel
                    panels = [Panel(**p) for p in raw_panels]
                    company.panels = panels
                    company.num_panels = len(panels)
                    dm.save_company(company)
                    response_data["message"] = f"Saved {len(panels)} panel(s) for {company.name}"
                    response_data["num_panels"] = len(panels)
            except Exception as e:
                response_data["status"] = "error"
                response_data["message"] = str(e)

        elif parsed_path.path.startswith('/api/toggle-panel-walkin/'):
            # POST /api/toggle-panel-walkin/{company_id}/{panel_id}
            parts = parsed_path.path.split('/')
            # path: ['', 'api', 'toggle-panel-walkin', company_id, panel_id]
            if len(parts) >= 5:
                company_id = parts[3]
                panel_id = parts[4]
                try:
                    company = dm.get_company(company_id)
                    if company is None:
                        response_data["status"] = "error"
                        response_data["message"] = "Company not found"
                    else:
                        toggled = False
                        for p in company.panels:
                            if p.panel_id == panel_id:
                                p.walk_in_open = not p.walk_in_open
                                response_data["walk_in_open"] = p.walk_in_open
                                response_data["message"] = f"Panel walk-in {'opened' if p.walk_in_open else 'closed'}"
                                toggled = True
                                break
                        if not toggled:
                            response_data["status"] = "error"
                            response_data["message"] = "Panel not found"
                        else:
                            dm.save_company(company)
                except Exception as e:
                    response_data["status"] = "error"
                    response_data["message"] = str(e)

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
