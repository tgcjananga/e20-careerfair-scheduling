import csv
import re
from pathlib import Path
from typing import Dict, List, Set, Tuple

from .data_manager import DataManager, Student, Company, JobRole, Application, AppStatus

class ResponseImporter:
    def __init__(self, data_manager: DataManager):
        self.dm = data_manager

    def clean_id(self, text: str) -> str:
        """Sanitizes text to create a valid ID."""
        return re.sub(r'[^a-zA-Z0-9_]', '', text.lower().replace(' ', '_'))

    def import_responses(self, file_path: str):
        companies_map: Dict[str, Company] = {} # name -> Company
        students: List[Student] = []

        with open(file_path, 'r', encoding='utf-8') as f:
            reader = csv.reader(f)
            header = next(reader) # Skip header

            for row in reader:
                if not row: continue
                
                # Extract Student Data
                # Index 2: Email, 3: Name with Initials (Wickramasinghe G.H), 4: Reg No (E/20/XXX)
                # Correction based on file view:
                # 0: Timestamp
                # 1: Email Address
                # 2: Name with Initials
                # 3: Name Used in CV
                # 4: Reg No
                
                email = row[1].strip()
                name = row[2].strip() # Name with Initials
                try:
                    reg_no = row[4].strip()
                except IndexError:
                    print(f"Skipping incomplete row: {row}")
                    continue

                student_id = reg_no.replace('/', '') # E20121
                
                student = Student(id=student_id, name=name, email=email, applications=[])
                
                # Extract Preferences
                # Preference 1 starts at index 5.
                # Pattern: Company, Role, CV Link
                # Indices: 5,6,7 | 8,9,10 | 11,12,13 | 14,15,16 | 17,18,19
                
                prefs_start_idx = 5
                pref_block_size = 3
                
                for i in range(5): # Up to 5 preferences
                    base_idx = prefs_start_idx + (i * pref_block_size)
                    
                    if base_idx + 2 >= len(row):
                        break
                        
                    company_name = row[base_idx].strip()
                    role_title = row[base_idx+1].strip()
                    cv_link = row[base_idx+2].strip()
                    
                    if not company_name:
                        continue
                        
                    # Handle Company creation/retrieval
                    if company_name not in companies_map:
                        c_id = self.clean_id(company_name)
                        companies_map[company_name] = Company(id=c_id, name=company_name, job_roles=[])
                    
                    company = companies_map[company_name]
                    
                    # Handle JobRole creation/retrieval
                    job_role_id = self.clean_id(f"{company.id}_{role_title}")
                    
                    # Check if role exists
                    role_exists = False
                    for role in company.job_roles:
                        if role.id == job_role_id:
                            role_exists = True
                            break
                    
                    if not role_exists:
                        # Create new role
                        new_role = JobRole(id=job_role_id, title=role_title, company_id=company.id)
                        company.job_roles.append(new_role)
                    
                    # Create Application
                    # DataManager Application doesn't have cv_link field in the class definition I saw earlier? 
                    # Let's check DataManager definition. 
                    # If it doesn't have it, I might need to add it or ignore it for now.
                    # The user said "add these datas". The CSV has CV links.
                    # I should probably update Application class to support CV link if I can.
                    # But for now, let's stick to existing schema + maybe add it if easy.
                    # Wait, the `Application` dataclass in `data_manager.py` did NOT show a `cv_link` field.
                    # I will add it to the Application class if I can edit `data_manager.py`, otherwise I'll lose that data.
                    # Given the user context "upload your cv", it's important.
                    # I'll check `data_manager.py` again. It has `student_id`, `company_id`, `job_role_id`, `status`, `priority`.
                    # I should add `cv_link` to `Application` class.
                    
                    app = Application(
                        student_id=student.id,
                        company_id=company.id,
                        job_role_id=job_role_id,
                        status=AppStatus.APPLIED,
                        # priority=i+1, # User requested to remove priority
                        cv_link=cv_link
                    )
                    # Hack: if I modify DataManager, I need to update parsing logic. 
                    # For now, I will just create the object. I'll update DataManager content in a separate step.
                    
                    student.applications.append(app)

                students.append(student)

        # Save all data
        self.dm.save_companies(list(companies_map.values()))
        self.dm.save_students(students)
        
        # Clear schedule
        # Function to clear schedule? DataManager doesn't seem to have a clear_schedule method exposed in previous snippets.
        # But `cli.py` might save interviews.
        # I'll manually overwrite schedule file if I can access it.
        schedule_file = self.dm.data_dir / "schedule.json"
        if schedule_file.exists():
             with open(schedule_file, 'w') as f:
                 f.write("[]") # Empty list
