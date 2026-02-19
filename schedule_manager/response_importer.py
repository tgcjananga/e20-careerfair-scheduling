import csv
import json
import re
from pathlib import Path
from typing import Dict, List

from .data_manager import DataManager, Student, Company, JobRole, Application, Panel, AppStatus


class ResponseImporter:
    def __init__(self, data_manager: DataManager):
        self.dm = data_manager

    def clean_id(self, text: str) -> str:
        """Sanitizes text to create a valid ID."""
        return re.sub(r'[^a-zA-Z0-9_]', '', text.lower().replace(' ', '_'))

    def _build_pref_blocks(self, header: list) -> list:
        """
        Scan the header row to build preference block descriptors.

        New CSV format per preference:
          Preference N Company | Preference N Position | [optional ghost col] | Shortlisted

        Returns list of dicts sorted by pref_num:
          {"pref_num": N, "company": col_idx, "position": col_idx, "shortlisted": col_idx}

        Works for any number of preferences and handles the Preference 2
        ghost-column anomaly by searching forward for the next "Shortlisted".
        """
        blocks = []
        for i, col in enumerate(header):
            m = re.match(r'Preference\s+(\d+)\s+Company', col.strip(), re.IGNORECASE)
            if m:
                pref_num     = int(m.group(1))
                company_idx  = i
                position_idx = i + 1  # always immediately follows company
                # Search forward (up to 4 cols) for the next "Shortlisted" column
                shortlisted_idx = None
                for j in range(i + 2, min(i + 6, len(header))):
                    if header[j].strip().lower() == 'shortlisted':
                        shortlisted_idx = j
                        break
                if shortlisted_idx is not None:
                    blocks.append({
                        "pref_num":    pref_num,
                        "company":     company_idx,
                        "position":    position_idx,
                        "shortlisted": shortlisted_idx,
                    })
        blocks.sort(key=lambda b: b["pref_num"])
        return blocks

    def import_responses(self, file_path: str):
        companies_map: Dict[str, Company] = {}
        students: List[Student] = []

        with open(file_path, 'r', encoding='utf-8') as f:
            reader = csv.reader(f)
            header = next(reader)

            # ── Build preference block map from actual header columns ─────────
            # New CSV layout (0-based):
            #   0  Name
            #   1  Email Address
            #   2  Registration Number  (e.g. E/20/121)
            #   3  Name (CV)            (ignored — not needed for scheduling)
            #   4+ Preference blocks detected dynamically
            pref_blocks = self._build_pref_blocks(header)
            print(f"[importer] detected {len(pref_blocks)} preference blocks: "
                  f"{[b['pref_num'] for b in pref_blocks]}")

            for row in reader:
                if not row:
                    continue

                # ── Student identity fields ───────────────────────────────────
                name   = row[0].strip() if len(row) > 0 else ""
                email  = row[1].strip() if len(row) > 1 else ""
                reg_no = row[2].strip() if len(row) > 2 else ""

                if not reg_no or not name:
                    print(f"[importer] skipping incomplete row: {row[:4]}")
                    continue

                # E/20/121 → E20121
                student_id = reg_no.replace('/', '')
                student = Student(id=student_id, name=name, email=email, applications=[])

                # ── Preference blocks ─────────────────────────────────────────
                for block in pref_blocks:
                    c_idx = block["company"]
                    p_idx = block["position"]
                    s_idx = block["shortlisted"]

                    if c_idx >= len(row) or p_idx >= len(row):
                        break

                    company_name = row[c_idx].strip()
                    role_title   = row[p_idx].strip()
                    shortlisted  = row[s_idx].strip() if s_idx < len(row) else "0"

                    if not company_name:
                        continue

                    # Company creation / retrieval
                    if company_name not in companies_map:
                        c_id = self.clean_id(company_name)
                        companies_map[company_name] = Company(
                            id=c_id, name=company_name, job_roles=[]
                        )
                    company = companies_map[company_name]

                    # JobRole creation / retrieval
                    job_role_id = self.clean_id(f"{company.id}_{role_title}")
                    if not any(r.id == job_role_id for r in company.job_roles):
                        company.job_roles.append(
                            JobRole(id=job_role_id, title=role_title, company_id=company.id)
                        )

                    # Application — status from shortlisted flag; priority from pref order
                    status = AppStatus.SHORTLISTED if shortlisted == "1" else AppStatus.APPLIED
                    app = Application(
                        student_id=student.id,
                        company_id=company.id,
                        job_role_id=job_role_id,
                        status=status,
                        priority=block["pref_num"],  # 1 = top choice, 8 = last
                        cv_link="",
                    )
                    student.applications.append(app)

                students.append(student)

        # ── Load company defaults template ───────────────────────────────────
        defaults = {}
        defaults_path = self.dm.data_dir / "company_defaults.json"
        if defaults_path.exists():
            try:
                with open(defaults_path) as _f:
                    defaults = json.load(_f)
            except Exception:
                defaults = {}

        # ── Merge with existing company config ────────────────────────────────
        # Priority: existing saved config > template defaults > bare dataclass defaults
        # For NEW companies (never seen before): template defaults are applied.
        # For EXISTING companies: their saved config is preserved in full.
        existing_companies: Dict[str, Company] = {}
        try:
            for c in self.dm.load_companies():
                existing_companies[c.id] = c
        except Exception:
            pass  # First import — no existing data, that's fine

        final_companies = []
        for company in companies_map.values():
            if company.id in existing_companies:
                # ── Existing company: preserve all manual config ──
                existing = existing_companies[company.id]
                company.panels             = existing.panels
                company.breaks             = existing.breaks
                company.availability_start = existing.availability_start
                company.availability_end   = existing.availability_end
                company.num_panels         = existing.num_panels
                company.walk_in_open       = existing.walk_in_open
                # Merge job_roles: keep existing (preserves duration_minutes),
                # append any brand-new roles from the CSV
                existing_role_ids = {r.id for r in existing.job_roles}
                for new_role in company.job_roles:
                    if new_role.id not in existing_role_ids:
                        existing.job_roles.append(new_role)
                company.job_roles = existing.job_roles
            else:
                # ── New company: apply template defaults ──
                company.availability_start = defaults.get("availability_start", "09:00")
                company.availability_end   = defaults.get("availability_end",   "17:00")
                company.breaks             = defaults.get("breaks", [])
                dp = defaults.get("default_panel", {})
                if dp:
                    company.panels = [Panel(
                        panel_id=f"{company.id}-P1",
                        label=dp.get("label", "Panel 1 (Default)"),
                        job_role_ids=[r.id for r in company.job_roles],
                        slot_duration_minutes=dp.get("slot_duration_minutes", 30),
                        reserved_walkin_slots=dp.get("reserved_walkin_slots", 0),
                        walk_in_open=dp.get("walk_in_open", False),
                        breaks=dp.get("breaks", []),
                    )]
                    company.num_panels = 1
            final_companies.append(company)

        # Save all data
        self.dm.save_companies(final_companies)
        self.dm.save_students(students)
        
        # Clear schedule
        # Function to clear schedule? DataManager doesn't seem to have a clear_schedule method exposed in previous snippets.
        # But `cli.py` might save interviews.
        # I'll manually overwrite schedule file if I can access it.
        schedule_file = self.dm.data_dir / "schedule.json"
        if schedule_file.exists():
             with open(schedule_file, 'w') as f:
                 f.write("[]") # Empty list
