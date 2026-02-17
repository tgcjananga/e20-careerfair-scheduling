import json
from dataclasses import dataclass, field, asdict
from typing import List, Dict, Optional
from enum import Enum
from pathlib import Path

class AppStatus(str, Enum):
    APPLIED = "applied"
    SHORTLISTED = "shortlisted"
    WAITLISTED = "waitlisted"
    REJECTED = "rejected"

@dataclass
class JobRole:
    id: str
    title: str
    company_id: str
    duration_minutes: int = 30

@dataclass
class Company:
    id: str
    name: str
    job_roles: List[JobRole] = field(default_factory=list)

@dataclass
class Application:
    student_id: str
    company_id: str
    job_role_id: str
    status: AppStatus = AppStatus.APPLIED
    priority: Optional[int] = None  # 1 (High) to 5 (Low), None if not ranked
    cv_link: str = ""

@dataclass
class Student:
    id: str
    name: str
    email: str
    applications: List[Application] = field(default_factory=list)

@dataclass
class Interview:
    id: str
    student_id: str
    company_id: str
    job_role_id: str
    start_time: str # ISO format
    end_time: str   # ISO format
    
class DataManager:
    def __init__(self, data_dir: str = "schedule_manager/data"):
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.students_file = self.data_dir / "students.json"
        self.companies_file = self.data_dir / "companies.json"
        
    def _save(self, path: Path, data: List[Dict]):
        with open(path, 'w') as f:
            json.dump(data, f, indent=2)

    def _load(self, path: Path) -> List[Dict]:
        if not path.exists():
            return []
        with open(path, 'r') as f:
            return json.load(f)

    def save_students(self, students: List[Student]):
        self._save(self.students_file, [asdict(s) for s in students])

    def load_students(self) -> List[Student]:
        data = self._load(self.students_file)
        students = []
        for s_data in data:
            # Reconstruct Application objects
            apps = [Application(**a) for a in s_data.get("applications", [])]
            s_data["applications"] = apps
            students.append(Student(**s_data))
        return students

    def save_companies(self, companies: List[Company]):
        self._save(self.companies_file, [asdict(c) for c in companies])

    def load_companies(self) -> List[Company]:
        data = self._load(self.companies_file)
        companies = []
        for c_data in data:
            # Reconstruct JobRole objects
            roles = [JobRole(**r) for r in c_data.get("job_roles", [])]
            c_data["job_roles"] = roles
            companies.append(Company(**c_data))
        return companies
