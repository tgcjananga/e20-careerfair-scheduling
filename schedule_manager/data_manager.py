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
class Panel:
    panel_id: str                        # e.g. "sysco-P1"
    label: str                           # display name, e.g. "Panel 1"
    job_role_ids: List[str] = field(default_factory=list)  # which roles this panel handles
    slot_duration_minutes: int = 30      # interview duration for this panel
    walk_in_open: bool = False           # walk-in enabled for this panel
    reserved_walkin_slots: int = 0       # slots kept free for walk-ins (Phase 2d)
    breaks: List[dict] = field(default_factory=list)  # [{"start": "13:00", "end": "14:00"}]

@dataclass
class Company:
    id: str
    name: str
    job_roles: List[JobRole] = field(default_factory=list)
    panels: List[Panel] = field(default_factory=list)  # per-panel config (Phase 1a+)
    availability_start: str = "09:00"   # company interview window start (Phase 1c)
    availability_end: str = "17:00"     # company interview window end (Phase 1c)
    breaks: List[dict] = field(default_factory=list)  # [{"start": "13:00", "end": "14:00"}]
    # --- Backward-compat fields (kept so old JSON loads without errors) ---
    num_panels: int = 1                  # derived: len(panels) when panels exist
    walk_in_open: bool = False           # global walk-in toggle (legacy)

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
    panel_id: str = "default"  # Phase 2a: assigned panel
    start_time: str = ""       # ISO format
    end_time: str = ""         # ISO format
    status: str = "scheduled"  # Phase 3: scheduled | in_progress | completed | cancelled

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
            # Reconstruct Panel objects (new field — safe default if missing)
            raw_panels = c_data.get("panels", [])
            panels = [Panel(**p) for p in raw_panels]
            c_data["panels"] = panels
            # Strip unknown keys to avoid dataclass errors from old JSON
            known = {f.name for f in Company.__dataclass_fields__.values()}
            c_data = {k: v for k, v in c_data.items() if k in known}
            c_data["job_roles"] = roles
            c_data["panels"] = panels
            companies.append(Company(**c_data))
        return companies

    def get_company(self, company_id: str) -> Optional[Company]:
        """Return a single company by id, or None."""
        for c in self.load_companies():
            if c.id == company_id:
                return c
        return None

    def save_company(self, updated: Company):
        """Update a single company in companies.json, preserving all others."""
        companies = self.load_companies()
        for i, c in enumerate(companies):
            if c.id == updated.id:
                companies[i] = updated
                break
        self.save_companies(companies)
