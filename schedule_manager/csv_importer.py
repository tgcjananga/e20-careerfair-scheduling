import csv
from pathlib import Path
from typing import List
from schedule_manager.data_manager import DataManager, Student, Company, JobRole, Application, AppStatus

class CSVImporter:
    def __init__(self, data_manager: DataManager):
        self.dm = data_manager

    def import_companies(self, csv_path: str):
        """
        Expects CSV with headers: id, name, job_roles
        job_roles should be pipe-separated values: "Role1|Role2"
        """
        companies = []
        with open(csv_path, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                roles = []
                role_titles = row['job_roles'].split('|')
                for i, title in enumerate(role_titles):
                    if not title.strip(): continue
                    # Generate a simple role ID
                    idx = f"R{i+1}" 
                    # If we really wanted stable IDs we might need them in CSV
                    # For now, auto-generating based on index is okay for initial import
                    rid = f"{row['id']}-{idx}"
                    roles.append(JobRole(id=rid, title=title.strip(), company_id=row['id']))
                
                companies.append(Company(
                    id=row['id'],
                    name=row['name'],
                    job_roles=roles
                ))
        
        self.dm.save_companies(companies)
        print(f"Imported {len(companies)} companies from {csv_path}")

    def import_students(self, csv_path: str):
        """
        Expects CSV with headers: id, name, email
        """
        students = []
        with open(csv_path, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                students.append(Student(
                    id=row['id'],
                    name=row['name'],
                    email=row['email']
                ))
        
        # Note: This overwrites existing students. 
        # In a real app we might want to merge, but simple overwrite is safer for consistency now.
        self.dm.save_students(students)
        print(f"Imported {len(students)} students from {csv_path}")
    
    def import_applications(self, csv_path: str):
        """
        Expects CSV with headers: student_id, company_id, role_title, status, priority
        We match role_title to the company's job roles.
        """
        # We need to load existing students to attach applications to them
        students = self.dm.load_students()
        student_map = {s.id: s for s in students}
        
        # We need company data to find role IDs
        companies = self.dm.load_companies()
        # Map (company_id, role_title) -> role_id
        role_lookup = {}
        for c in companies:
            for r in c.job_roles:
                role_lookup[(c.id, r.title)] = r.id
        
        count = 0
        with open(csv_path, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                sid = row['student_id']
                cid = row['company_id']
                title = row['role_title']
                
                if sid not in student_map:
                    print(f"Warning: Student {sid} not found. Skipping application.")
                    continue
                
                # Find role ID
                rid = role_lookup.get((cid, title))
                if not rid:
                    # Fallback: try to find case-insensitive match? 
                    # For now just warn
                    print(f"Warning: Role '{title}' not found for Company {cid}. Skipping.")
                    continue
                
                status_str = row.get('status', 'applied').lower()
                try:
                    status = AppStatus(status_str)
                except ValueError:
                    status = AppStatus.APPLIED
                    
                prio_str = row.get('priority', '')
                priority = int(prio_str) if prio_str.isdigit() else None
                
                app = Application(
                    student_id=sid,
                    company_id=cid,
                    job_role_id=rid,
                    status=status,
                    priority=priority
                )
                
                student_map[sid].applications.append(app)
                count += 1
                
        self.dm.save_students(list(student_map.values()))
        print(f"Imported {count} applications from {csv_path}")

