"""
test_all_features.py — Comprehensive feature verification for Career Fair Scheduling System.

Tests are organised by phase. Each class:
  - Sets up a clean temporary data directory with minimal fixture data
  - Exercises real Python objects (DataManager, Scheduler) or file operations
  - Asserts end-to-end correctness
  - Tears down the temp directory after each test

Run:
    python -m pytest test_all_features.py -v
    python -m pytest test_all_features.py -v -k "TestPhase5"
"""

import copy
import json
import math
import os
import shutil
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path

# ─── Helpers ──────────────────────────────────────────────────────────────────


def _write(path, data):
    with open(path, "w") as f:
        json.dump(data, f, indent=2)


def _read(path):
    with open(path) as f:
        return json.load(f)


def _make_company(company_id="co1", name="Test Co", roles=None, panels=None,
                  avail_start="09:00", avail_end="17:00", breaks=None):
    roles = roles or [{"id": f"{company_id}_se", "title": "Software Engineer",
                       "company_id": company_id, "duration_minutes": 30}]
    return {
        "id": company_id,
        "name": name,
        "job_roles": roles,
        "panels": panels or [],
        "availability_start": avail_start,
        "availability_end": avail_end,
        "breaks": breaks or [],
        "num_panels": 1,
        "walk_in_open": False,
    }


def _make_student(student_id, company_id, role_id, status="applied", priority=None):
    app = {"student_id": student_id, "company_id": company_id,
           "job_role_id": role_id, "status": status, "priority": priority, "cv_link": ""}
    return {"id": student_id, "name": f"Student {student_id}",
            "email": f"{student_id}@example.com", "applications": [app]}


def _make_panel(panel_id, label, role_ids, duration=30, reserved=0,
                walk_in=False, breaks=None):
    return {
        "panel_id": panel_id,
        "label": label,
        "job_role_ids": role_ids,
        "slot_duration_minutes": duration,
        "reserved_walkin_slots": reserved,
        "walk_in_open": walk_in,
        "breaks": breaks or [],
    }


def _interview_minutes(iv):
    """Return duration in minutes of an Interview dict."""
    start = datetime.fromisoformat(iv["start_time"])
    end = datetime.fromisoformat(iv["end_time"])
    return int((end - start).total_seconds() / 60)


def _interview_start_hhmm(iv):
    return iv["start_time"].split("T")[1][:5]


def _interview_end_hhmm(iv):
    return iv["end_time"].split("T")[1][:5]


def _hhmm_to_min(t):
    h, m = map(int, t.split(":"))
    return h * 60 + m


# ─── Base class ───────────────────────────────────────────────────────────────


class SchedulerTestBase(unittest.TestCase):
    """Base class: creates a temp data directory and runs the scheduler."""

    EVENT_DATE = "2026-02-20"

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.data_dir = os.path.join(self.tmp, "data")
        os.makedirs(self.data_dir)
        # default empty datasets
        _write(os.path.join(self.data_dir, "companies.json"), [])
        _write(os.path.join(self.data_dir, "students.json"), [])
        _write(os.path.join(self.data_dir, "schedule.json"), [])
        _write(os.path.join(self.data_dir, "config.json"), {"event_date": self.EVENT_DATE})

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _dm(self):
        from schedule_manager.data_manager import DataManager
        return DataManager(data_dir=self.data_dir)

    def _run_scheduler(self, companies, students):
        """Write companies/students to temp dir, run scheduler, return interviews."""
        _write(os.path.join(self.data_dir, "companies.json"), companies)
        _write(os.path.join(self.data_dir, "students.json"), students)
        from schedule_manager.scheduler import Scheduler
        dm = self._dm()
        sched = Scheduler(dm)
        interviews = sched.run(self.EVENT_DATE)
        return [{"id": iv.id, "student_id": iv.student_id, "company_id": iv.company_id,
                 "job_role_id": iv.job_role_id, "panel_id": iv.panel_id,
                 "start_time": iv.start_time, "end_time": iv.end_time,
                 "status": iv.status} for iv in interviews]


# ══════════════════════════════════════════════════════════════════════════════
# Phase 0 — Backup / Restore
# ══════════════════════════════════════════════════════════════════════════════


class TestPhase0_Backup(SchedulerTestBase):

    def _checkpoint(self):
        """Directly replicate the checkpoint logic from server.py."""
        files = ["companies.json", "students.json", "schedule.json"]
        for fname in files:
            src = os.path.join(self.data_dir, fname)
            dst = os.path.join(self.data_dir, fname.replace(".json", ".backup.json"))
            if os.path.exists(src):
                shutil.copy2(src, dst)
        config_path = os.path.join(self.data_dir, "config.json")
        cfg = _read(config_path) if os.path.exists(config_path) else {}
        cfg["last_checkpoint"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        _write(config_path, cfg)

    def test_checkpoint_creates_all_backup_files(self):
        self._checkpoint()
        for fname in ["companies.backup.json", "students.backup.json", "schedule.backup.json"]:
            self.assertTrue(os.path.exists(os.path.join(self.data_dir, fname)),
                            f"{fname} was not created")

    def test_checkpoint_saves_timestamp(self):
        self._checkpoint()
        cfg = _read(os.path.join(self.data_dir, "config.json"))
        ts = cfg.get("last_checkpoint")
        self.assertIsNotNone(ts, "last_checkpoint missing from config.json")
        # Parse to verify format
        datetime.strptime(ts, "%Y-%m-%d %H:%M:%S")

    def test_checkpoint_info_preserves_event_date(self):
        """Running a schedule after checkpoint should NOT lose last_checkpoint (Bug #3 fix)."""
        self._checkpoint()
        original_ts = _read(os.path.join(self.data_dir, "config.json"))["last_checkpoint"]

        # Simulate what run-schedule does after Bug #3 fix (read-merge-write)
        config_path = os.path.join(self.data_dir, "config.json")
        cfg = _read(config_path)
        cfg["event_date"] = "2026-02-21"  # update only event_date
        _write(config_path, cfg)

        # last_checkpoint must still be present
        cfg_after = _read(config_path)
        self.assertIn("last_checkpoint", cfg_after,
                      "last_checkpoint was erased after updating event_date (Bug #3 not fixed)")
        self.assertEqual(cfg_after["last_checkpoint"], original_ts,
                         "last_checkpoint value changed unexpectedly")

    def test_checkpoint_info_missing_backups_shows_false(self):
        # No checkpoint taken -> backup files absent
        for fname in ["companies.backup.json", "students.backup.json", "schedule.backup.json"]:
            path = os.path.join(self.data_dir, fname)
            self.assertFalse(os.path.exists(path),
                             f"Unexpected backup file {fname} already exists")


class TestPhase0_Restore(SchedulerTestBase):

    def _checkpoint(self):
        files = ["companies.json", "students.json", "schedule.json"]
        for fname in files:
            src = os.path.join(self.data_dir, fname)
            dst = os.path.join(self.data_dir, fname.replace(".json", ".backup.json"))
            if os.path.exists(src):
                shutil.copy2(src, dst)
        config_path = os.path.join(self.data_dir, "config.json")
        cfg = _read(config_path) if os.path.exists(config_path) else {}
        cfg["last_checkpoint"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        _write(config_path, cfg)

    def _restore(self):
        files = ["companies.json", "students.json", "schedule.json"]
        for fname in files:
            src = os.path.join(self.data_dir, fname.replace(".json", ".backup.json"))
            dst = os.path.join(self.data_dir, fname)
            if os.path.exists(src):
                shutil.copy2(src, dst)

    def test_restore_copies_backup_to_working(self):
        original = [{"id": "test", "name": "Test Co", "job_roles": [], "panels": [],
                     "availability_start": "09:00", "availability_end": "17:00",
                     "breaks": [], "num_panels": 1, "walk_in_open": False}]
        _write(os.path.join(self.data_dir, "companies.json"), original)
        self._checkpoint()
        # Corrupt working file
        _write(os.path.join(self.data_dir, "companies.json"), [])
        self._restore()
        restored = _read(os.path.join(self.data_dir, "companies.json"))
        self.assertEqual(restored, original, "Restored companies.json does not match original")

    def test_run_schedule_preserves_checkpoint(self):
        """After checkpoint, updating config for event_date must NOT erase last_checkpoint."""
        self._checkpoint()
        ts = _read(os.path.join(self.data_dir, "config.json"))["last_checkpoint"]

        # Simulate the FIXED run-schedule config update
        config_path = os.path.join(self.data_dir, "config.json")
        cfg = _read(config_path)
        cfg["event_date"] = "2026-02-22"
        _write(config_path, cfg)

        cfg_after = _read(config_path)
        self.assertIn("last_checkpoint", cfg_after)
        self.assertEqual(cfg_after["last_checkpoint"], ts)


# ══════════════════════════════════════════════════════════════════════════════
# Phase 1a — Per-panel Job Role Assignment
# ══════════════════════════════════════════════════════════════════════════════


class TestPhase1a_PanelJobRoles(SchedulerTestBase):

    def test_panel_save_persists_to_disk(self):
        """Saving panels via DataManager persists to disk and reloads correctly."""
        from schedule_manager.data_manager import DataManager, Panel
        co = _make_company("co1", panels=[])
        _write(os.path.join(self.data_dir, "companies.json"), [co])
        dm = self._dm()
        company = dm.get_company("co1")
        panel = Panel(panel_id="co1-P1", label="Panel 1",
                      job_role_ids=["co1_se"], slot_duration_minutes=30)
        company.panels = [panel]
        dm.save_company(company)

        # Reload from disk
        reloaded = dm.get_company("co1")
        self.assertEqual(len(reloaded.panels), 1)
        self.assertEqual(reloaded.panels[0].job_role_ids, ["co1_se"])

    def test_multi_panel_different_roles(self):
        from schedule_manager.data_manager import DataManager, Panel
        roles = [
            {"id": "co1_se", "title": "SE", "company_id": "co1", "duration_minutes": 30},
            {"id": "co1_qa", "title": "QA", "company_id": "co1", "duration_minutes": 30},
        ]
        co = _make_company("co1", roles=roles)
        _write(os.path.join(self.data_dir, "companies.json"), [co])
        dm = self._dm()
        company = dm.get_company("co1")
        company.panels = [
            Panel(panel_id="co1-P1", label="SE Panel", job_role_ids=["co1_se"]),
            Panel(panel_id="co1-P2", label="QA Panel", job_role_ids=["co1_qa"]),
        ]
        dm.save_company(company)
        reloaded = dm.get_company("co1")
        self.assertEqual(len(reloaded.panels), 2)
        ids = {p.panel_id: p.job_role_ids for p in reloaded.panels}
        self.assertEqual(ids["co1-P1"], ["co1_se"])
        self.assertEqual(ids["co1-P2"], ["co1_qa"])

    def test_panel_reload_roundtrip_preserves_all_fields(self):
        from schedule_manager.data_manager import DataManager, Panel
        co = _make_company("co1")
        _write(os.path.join(self.data_dir, "companies.json"), [co])
        dm = self._dm()
        company = dm.get_company("co1")
        panel = Panel(panel_id="co1-P1", label="My Panel", job_role_ids=["co1_se"],
                      slot_duration_minutes=45, reserved_walkin_slots=2,
                      walk_in_open=True, breaks=[{"start": "12:00", "end": "13:00"}])
        company.panels = [panel]
        dm.save_company(company)
        reloaded = dm.get_company("co1").panels[0]
        self.assertEqual(reloaded.slot_duration_minutes, 45)
        self.assertEqual(reloaded.reserved_walkin_slots, 2)
        self.assertTrue(reloaded.walk_in_open)
        self.assertEqual(reloaded.breaks, [{"start": "12:00", "end": "13:00"}])


# ══════════════════════════════════════════════════════════════════════════════
# Phase 1b — Variable Interview Durations
# ══════════════════════════════════════════════════════════════════════════════


class TestPhase1b_VariableDurations(SchedulerTestBase):

    def test_panel_duration_45_used_by_scheduler(self):
        panel = _make_panel("co1-P1", "Panel 1", ["co1_se"], duration=45)
        roles = [{"id": "co1_se", "title": "SE", "company_id": "co1", "duration_minutes": 30}]
        co = _make_company("co1", roles=roles, panels=[panel])
        students = [_make_student(f"S{i:03d}", "co1", "co1_se") for i in range(5)]
        interviews = self._run_scheduler([co], students)
        self.assertGreater(len(interviews), 0, "No interviews scheduled")
        for iv in interviews:
            dur = _interview_minutes(iv)
            self.assertEqual(dur, 45, f"Expected 45-min interview, got {dur}")

    def test_default_duration_30_when_no_panel(self):
        """No panels configured → falls back to role.duration_minutes == 30."""
        co = _make_company("co1")  # no panels
        students = [_make_student(f"S{i:03d}", "co1", "co1_se") for i in range(3)]
        interviews = self._run_scheduler([co], students)
        self.assertGreater(len(interviews), 0)
        for iv in interviews:
            dur = _interview_minutes(iv)
            self.assertEqual(dur, 30)

    def test_slots_needed_calculation(self):
        """Units: math.ceil(dur / 30) gives correct slots_needed."""
        self.assertEqual(math.ceil(30 / 30), 1)
        self.assertEqual(math.ceil(45 / 30), 2)
        self.assertEqual(math.ceil(60 / 30), 2)
        self.assertEqual(math.ceil(90 / 30), 3)

    def test_60min_panel_no_overlap_same_panel(self):
        """Two students assigned to a 60-min panel must not overlap."""
        panel = _make_panel("co1-P1", "Panel 1", ["co1_se"], duration=60)
        roles = [{"id": "co1_se", "title": "SE", "company_id": "co1", "duration_minutes": 30}]
        co = _make_company("co1", roles=roles, panels=[panel])
        students = [_make_student(f"S{i:03d}", "co1", "co1_se") for i in range(4)]
        interviews = self._run_scheduler([co], students)
        # Check no two interviews for the same panel overlap
        times = sorted(
            [(datetime.fromisoformat(iv["start_time"]),
              datetime.fromisoformat(iv["end_time"])) for iv in interviews]
        )
        for i in range(len(times) - 1):
            self.assertLessEqual(times[i][1], times[i + 1][0],
                                 f"Interviews overlap: {times[i]} and {times[i+1]}")


# ══════════════════════════════════════════════════════════════════════════════
# Phase 1c — Company Availability Windows
# ══════════════════════════════════════════════════════════════════════════════


class TestPhase1c_AvailabilityWindow(SchedulerTestBase):

    def test_no_interview_before_window_start(self):
        co = _make_company("co1", avail_start="13:00", avail_end="17:00")
        students = [_make_student(f"S{i:03d}", "co1", "co1_se") for i in range(5)]
        interviews = self._run_scheduler([co], students)
        self.assertGreater(len(interviews), 0)
        for iv in interviews:
            start_min = _hhmm_to_min(_interview_start_hhmm(iv))
            self.assertGreaterEqual(start_min, _hhmm_to_min("13:00"),
                                    f"Interview starts before window: {iv['start_time']}")

    def test_no_interview_after_window_end(self):
        co = _make_company("co1", avail_start="09:00", avail_end="11:00")
        students = [_make_student(f"S{i:03d}", "co1", "co1_se") for i in range(5)]
        interviews = self._run_scheduler([co], students)
        for iv in interviews:
            end_min = _hhmm_to_min(_interview_end_hhmm(iv))
            self.assertLessEqual(end_min, _hhmm_to_min("11:00"),
                                 f"Interview ends after window: {iv['end_time']}")

    def test_default_window_09_to_17(self):
        co = _make_company("co1")  # defaults
        students = [_make_student(f"S{i:03d}", "co1", "co1_se") for i in range(3)]
        interviews = self._run_scheduler([co], students)
        for iv in interviews:
            self.assertGreaterEqual(_hhmm_to_min(_interview_start_hhmm(iv)),
                                    _hhmm_to_min("09:00"))
            self.assertLessEqual(_hhmm_to_min(_interview_end_hhmm(iv)),
                                 _hhmm_to_min("17:00"))

    def test_settings_save_persists_window(self):
        co = _make_company("co1")
        _write(os.path.join(self.data_dir, "companies.json"), [co])
        dm = self._dm()
        company = dm.get_company("co1")
        company.availability_start = "10:00"
        company.availability_end = "15:00"
        dm.save_company(company)
        reloaded = dm.get_company("co1")
        self.assertEqual(reloaded.availability_start, "10:00")
        self.assertEqual(reloaded.availability_end, "15:00")


# ══════════════════════════════════════════════════════════════════════════════
# Phase 1d — Walk-in Slot Reservation
# ══════════════════════════════════════════════════════════════════════════════


class TestPhase1d_WalkinReservation(SchedulerTestBase):

    def test_reserved_2_slots_leaves_last_2_empty(self):
        """With reserved_walkin_slots=2, last 2 daily slots must have no interviews."""
        panel = _make_panel("co1-P1", "Panel 1", ["co1_se"], reserved=2)
        roles = [{"id": "co1_se", "title": "SE", "company_id": "co1", "duration_minutes": 30}]
        co = _make_company("co1", roles=roles, panels=[panel])
        # Enough students to fill every slot
        students = [_make_student(f"S{i:03d}", "co1", "co1_se") for i in range(20)]
        interviews = self._run_scheduler([co], students)
        self.assertGreater(len(interviews), 0)
        latest_start = max(_hhmm_to_min(_interview_start_hhmm(iv)) for iv in interviews)
        # Day ends 17:00 = 1020 min; last 2 slots are 16:00 (960) and 16:30 (990)
        self.assertLess(latest_start, _hhmm_to_min("16:00"),
                        f"Expected last slot < 16:00 with 2 reserved, got {latest_start // 60}:{latest_start % 60:02d}")

    def test_reserved_0_can_use_all_slots(self):
        panel = _make_panel("co1-P1", "Panel 1", ["co1_se"], reserved=0)
        roles = [{"id": "co1_se", "title": "SE", "company_id": "co1", "duration_minutes": 30}]
        co = _make_company("co1", roles=roles, panels=[panel])
        students = [_make_student(f"S{i:03d}", "co1", "co1_se") for i in range(20)]
        interviews = self._run_scheduler([co], students)
        latest_start = max(_hhmm_to_min(_interview_start_hhmm(iv)) for iv in interviews)
        # With 0 reserved, 16:30 slot (990 min) should be available
        self.assertGreaterEqual(latest_start, _hhmm_to_min("16:00"),
                                "Expected interviews to use late slots with 0 reserved")


# ══════════════════════════════════════════════════════════════════════════════
# Phase 2a — panel_id Written to Each Interview
# ══════════════════════════════════════════════════════════════════════════════


class TestPhase2a_PanelIdOnInterviews(SchedulerTestBase):

    def test_all_interviews_have_panel_id(self):
        panel = _make_panel("co1-P1", "Panel 1", ["co1_se"])
        roles = [{"id": "co1_se", "title": "SE", "company_id": "co1", "duration_minutes": 30}]
        co = _make_company("co1", roles=roles, panels=[panel])
        students = [_make_student(f"S{i:03d}", "co1", "co1_se") for i in range(3)]
        interviews = self._run_scheduler([co], students)
        for iv in interviews:
            self.assertIn("panel_id", iv)
            self.assertNotEqual(iv["panel_id"], "", "panel_id should not be empty")

    def test_panel_id_matches_defined_panel(self):
        panel = _make_panel("co1-P1", "Panel 1", ["co1_se"])
        roles = [{"id": "co1_se", "title": "SE", "company_id": "co1", "duration_minutes": 30}]
        co = _make_company("co1", roles=roles, panels=[panel])
        students = [_make_student(f"S{i:03d}", "co1", "co1_se") for i in range(3)]
        interviews = self._run_scheduler([co], students)
        for iv in interviews:
            self.assertEqual(iv["panel_id"], "co1-P1",
                             f"Expected panel_id 'co1-P1', got '{iv['panel_id']}'")

    def test_two_panels_produce_two_panel_ids(self):
        roles = [
            {"id": "co1_se", "title": "SE", "company_id": "co1", "duration_minutes": 30},
            {"id": "co1_qa", "title": "QA", "company_id": "co1", "duration_minutes": 30},
        ]
        panels = [
            _make_panel("co1-P1", "SE Panel", ["co1_se"]),
            _make_panel("co1-P2", "QA Panel", ["co1_qa"]),
        ]
        co = _make_company("co1", roles=roles, panels=panels)
        students = (
            [_make_student(f"SE{i}", "co1", "co1_se") for i in range(3)] +
            [_make_student(f"QA{i}", "co1", "co1_qa") for i in range(3)]
        )
        interviews = self._run_scheduler([co], students)
        panel_ids_used = {iv["panel_id"] for iv in interviews}
        self.assertIn("co1-P1", panel_ids_used)
        self.assertIn("co1-P2", panel_ids_used)

    def test_same_role_shared_across_two_panels(self):
        """Both panels handle the same role — students should be split across both panels,
        not all funnelled into one. This was the last-write-wins bug in panel_for_role."""
        roles = [{"id": "co1_se", "title": "SE", "company_id": "co1", "duration_minutes": 30}]
        panels = [
            _make_panel("co1-P1", "Panel A", ["co1_se"]),
            _make_panel("co1-P2", "Panel B", ["co1_se"]),
        ]
        co = _make_company("co1", roles=roles, panels=panels)
        # 20 students → single panel can only hold 16 in a full day; 2 panels should fit all 20
        students = [_make_student(f"S{i:03d}", "co1", "co1_se") for i in range(20)]
        interviews = self._run_scheduler([co], students)
        panel_ids_used = {iv["panel_id"] for iv in interviews}
        # Both panels must be used
        self.assertIn("co1-P1", panel_ids_used, "Panel A received no interviews (same-role sharing broken)")
        self.assertIn("co1-P2", panel_ids_used, "Panel B received no interviews (same-role sharing broken)")
        # No student may appear twice
        student_ids = [iv["student_id"] for iv in interviews]
        self.assertEqual(len(student_ids), len(set(student_ids)), "A student was double-booked across panels")


# ══════════════════════════════════════════════════════════════════════════════
# Phase 2b — Multi-slot Blocking for Variable Durations
# ══════════════════════════════════════════════════════════════════════════════


class TestPhase2b_MultiSlotBlocking(SchedulerTestBase):

    def _no_overlaps(self, interviews):
        """Return True if no two interviews from the same panel overlap."""
        from collections import defaultdict
        by_panel = defaultdict(list)
        for iv in interviews:
            by_panel[iv["panel_id"]].append(iv)
        for panel_ivs in by_panel.values():
            sorted_ivs = sorted(panel_ivs, key=lambda x: x["start_time"])
            for i in range(len(sorted_ivs) - 1):
                end = datetime.fromisoformat(sorted_ivs[i]["end_time"])
                start_next = datetime.fromisoformat(sorted_ivs[i + 1]["start_time"])
                if end > start_next:
                    return False
        return True

    def test_45min_no_panel_overlap(self):
        panel = _make_panel("co1-P1", "Panel 1", ["co1_se"], duration=45)
        roles = [{"id": "co1_se", "title": "SE", "company_id": "co1", "duration_minutes": 30}]
        co = _make_company("co1", roles=roles, panels=[panel])
        students = [_make_student(f"S{i:03d}", "co1", "co1_se") for i in range(6)]
        interviews = self._run_scheduler([co], students)
        self.assertTrue(self._no_overlaps(interviews), "Panel has overlapping 45-min interviews")

    def test_45min_student_no_double_book(self):
        """Student with two 45-min interviews (different companies) must not overlap."""
        roles1 = [{"id": "co1_se", "title": "SE", "company_id": "co1", "duration_minutes": 30}]
        roles2 = [{"id": "co2_se", "title": "SE", "company_id": "co2", "duration_minutes": 30}]
        panel1 = _make_panel("co1-P1", "Panel 1", ["co1_se"], duration=45)
        panel2 = _make_panel("co2-P1", "Panel 1", ["co2_se"], duration=45)
        co1 = _make_company("co1", roles=roles1, panels=[panel1])
        co2 = _make_company("co2", roles=roles2, panels=[panel2])
        # Student S001 applies to both
        student = {
            "id": "S001", "name": "Student S001", "email": "s001@example.com",
            "applications": [
                {"student_id": "S001", "company_id": "co1", "job_role_id": "co1_se",
                 "status": "applied", "priority": None, "cv_link": ""},
                {"student_id": "S001", "company_id": "co2", "job_role_id": "co2_se",
                 "status": "applied", "priority": None, "cv_link": ""},
            ]
        }
        interviews = self._run_scheduler([co1, co2], [student])
        s001_ivs = [iv for iv in interviews if iv["student_id"] == "S001"]
        if len(s001_ivs) >= 2:
            s001_ivs.sort(key=lambda x: x["start_time"])
            end0 = datetime.fromisoformat(s001_ivs[0]["end_time"])
            start1 = datetime.fromisoformat(s001_ivs[1]["start_time"])
            self.assertLessEqual(end0, start1,
                                 f"Student S001 double-booked: {s001_ivs[0]['end_time']} > {s001_ivs[1]['start_time']}")


# ══════════════════════════════════════════════════════════════════════════════
# Phase 2e — Priority-Weighted Objective
# ══════════════════════════════════════════════════════════════════════════════


class TestPhase2e_PriorityWeights(SchedulerTestBase):

    def test_shortlisted_scheduled_over_applied_when_capacity_limited(self):
        """When only 1 slot available: SHORTLISTED beats APPLIED."""
        # 1-slot day: avail 09:00–09:30 only
        co = _make_company("co1", avail_start="09:00", avail_end="09:30")
        students = [
            _make_student("SLISTED", "co1", "co1_se", status="shortlisted"),
            _make_student("APPLIED", "co1", "co1_se", status="applied"),
        ]
        interviews = self._run_scheduler([co], students)
        self.assertEqual(len(interviews), 1)
        self.assertEqual(interviews[0]["student_id"], "SLISTED",
                         "SHORTLISTED student should win when capacity is 1")

    def test_priority_1_wins_over_priority_5_when_capacity_limited(self):
        co = _make_company("co1", avail_start="09:00", avail_end="09:30")
        students = [
            _make_student("PRIO1", "co1", "co1_se", priority=1),
            _make_student("PRIO5", "co1", "co1_se", priority=5),
        ]
        interviews = self._run_scheduler([co], students)
        self.assertEqual(len(interviews), 1)
        self.assertEqual(interviews[0]["student_id"], "PRIO1",
                         "Priority-1 student should win when capacity is 1")

    def test_objective_value_positive(self):
        """Scheduler finds a non-trivial schedule."""
        co = _make_company("co1")
        students = [_make_student(f"S{i:03d}", "co1", "co1_se") for i in range(5)]
        interviews = self._run_scheduler([co], students)
        self.assertGreater(len(interviews), 0, "Expected at least 1 interview scheduled")


# ══════════════════════════════════════════════════════════════════════════════
# Phase 3 — Interview Status Tracking
# ══════════════════════════════════════════════════════════════════════════════


class TestPhase3_StatusTracking(SchedulerTestBase):

    def _make_schedule(self):
        schedule = [
            {"id": "INT-1", "student_id": "S001", "company_id": "co1",
             "job_role_id": "co1_se", "panel_id": "co1-P0",
             "start_time": f"{self.EVENT_DATE}T09:00:00",
             "end_time": f"{self.EVENT_DATE}T09:30:00",
             "status": "scheduled"},
        ]
        _write(os.path.join(self.data_dir, "schedule.json"), schedule)
        return schedule

    def _update_status(self, interview_id, new_status):
        """Replicate server-side status update logic."""
        path = os.path.join(self.data_dir, "schedule.json")
        schedule = _read(path)
        for iv in schedule:
            if iv["id"] == interview_id:
                iv["status"] = new_status
                break
        _write(path, schedule)

    def test_mark_complete(self):
        self._make_schedule()
        self._update_status("INT-1", "completed")
        schedule = _read(os.path.join(self.data_dir, "schedule.json"))
        self.assertEqual(schedule[0]["status"], "completed")

    def test_mark_cancel(self):
        self._make_schedule()
        self._update_status("INT-1", "cancelled")
        schedule = _read(os.path.join(self.data_dir, "schedule.json"))
        self.assertEqual(schedule[0]["status"], "cancelled")

    def test_mark_in_progress(self):
        self._make_schedule()
        self._update_status("INT-1", "in_progress")
        schedule = _read(os.path.join(self.data_dir, "schedule.json"))
        self.assertEqual(schedule[0]["status"], "in_progress")

    def test_new_scheduler_interviews_default_scheduled(self):
        co = _make_company("co1")
        students = [_make_student("S001", "co1", "co1_se")]
        interviews = self._run_scheduler([co], students)
        for iv in interviews:
            self.assertEqual(iv["status"], "scheduled",
                             f"New interview should default to 'scheduled', got '{iv['status']}'")


# ══════════════════════════════════════════════════════════════════════════════
# Phase 3 — Live Queue Logic
# ══════════════════════════════════════════════════════════════════════════════


class TestPhase3_LiveQueue(SchedulerTestBase):

    def _build_queue(self, raw_interviews, now_str):
        """Replicate the Live Queue grouping logic from server.py."""
        from datetime import datetime as dt
        now = dt.fromisoformat(now_str)

        def make_entry(iv):
            return {
                "interview_id": iv["id"],
                "student_id": iv["student_id"],
                "start_time": iv["start_time"].split("T")[1][:5],
                "end_time": iv["end_time"].split("T")[1][:5],
                "status": iv.get("status", "scheduled"),
            }

        panels_dict = {}
        for iv in sorted(raw_interviews, key=lambda x: x["start_time"]):
            pid = iv.get("panel_id", "default")
            panels_dict.setdefault(pid, []).append(iv)

        result = {}
        for pid, ivs in panels_dict.items():
            current, upcoming, past = None, [], []
            for iv in ivs:
                status = iv.get("status", "scheduled")
                if status == "cancelled":
                    continue
                start_dt = dt.fromisoformat(iv["start_time"])
                end_dt = dt.fromisoformat(iv["end_time"])
                if status == "in_progress":
                    current = make_entry(iv)
                elif start_dt <= now < end_dt:
                    if not current or current["status"] != "in_progress":
                        current = make_entry(iv)
                elif start_dt > now:
                    upcoming.append(iv)
                else:
                    past.append(iv)
            past.sort(key=lambda x: x["end_time"])
            result[pid] = {
                "previous": make_entry(past[-1]) if past else None,
                "current": current,
                "next": [make_entry(iv) for iv in upcoming[:2]],
            }
        return result

    def _make_iv(self, iv_id, student_id, start_hhmm, end_hhmm, panel_id="co1-P0", status="scheduled"):
        d = self.EVENT_DATE
        return {"id": iv_id, "student_id": student_id, "company_id": "co1",
                "job_role_id": "co1_se", "panel_id": panel_id,
                "start_time": f"{d}T{start_hhmm}:00", "end_time": f"{d}T{end_hhmm}:00",
                "status": status}

    def test_current_determined_by_time(self):
        ivs = [self._make_iv("INT-1", "S001", "09:00", "09:30")]
        queue = self._build_queue(ivs, f"{self.EVENT_DATE}T09:15:00")
        self.assertIsNotNone(queue["co1-P0"]["current"])
        self.assertEqual(queue["co1-P0"]["current"]["interview_id"], "INT-1")

    def test_previous_is_most_recent_past(self):
        ivs = [
            self._make_iv("INT-1", "S001", "09:00", "09:30", status="completed"),
            self._make_iv("INT-2", "S002", "09:30", "10:00", status="completed"),
        ]
        queue = self._build_queue(ivs, f"{self.EVENT_DATE}T10:15:00")
        prev = queue["co1-P0"]["previous"]
        self.assertIsNotNone(prev)
        self.assertEqual(prev["interview_id"], "INT-2", "Previous should be the most recent past")

    def test_in_progress_overrides_time(self):
        ivs = [self._make_iv("INT-1", "S001", "09:00", "09:30", status="in_progress")]
        # now is PAST the interview's end time
        queue = self._build_queue(ivs, f"{self.EVENT_DATE}T10:00:00")
        self.assertIsNotNone(queue["co1-P0"]["current"])
        self.assertEqual(queue["co1-P0"]["current"]["interview_id"], "INT-1")

    def test_cancelled_excluded_from_queue(self):
        ivs = [self._make_iv("INT-1", "S001", "09:00", "09:30", status="cancelled")]
        queue = self._build_queue(ivs, f"{self.EVENT_DATE}T09:15:00")
        self.assertIsNone(queue["co1-P0"]["current"])
        self.assertEqual(queue["co1-P0"]["next"], [])
        self.assertIsNone(queue["co1-P0"]["previous"])

    def test_panels_grouped_separately(self):
        ivs = [
            self._make_iv("INT-1", "S001", "09:00", "09:30", panel_id="co1-P1"),
            self._make_iv("INT-2", "S002", "09:00", "09:30", panel_id="co1-P2"),
        ]
        queue = self._build_queue(ivs, f"{self.EVENT_DATE}T09:15:00")
        self.assertIn("co1-P1", queue)
        self.assertIn("co1-P2", queue)
        self.assertEqual(queue["co1-P1"]["current"]["interview_id"], "INT-1")
        self.assertEqual(queue["co1-P2"]["current"]["interview_id"], "INT-2")


# ══════════════════════════════════════════════════════════════════════════════
# Phase 5 — Company-Level Break Config
# ══════════════════════════════════════════════════════════════════════════════


class TestPhase5_CompanyBreaks(SchedulerTestBase):

    def test_break_slots_excluded(self):
        """No interview should start at 12:00 or 12:30 when break is 12:00–13:00."""
        co = _make_company("co1", breaks=[{"start": "12:00", "end": "13:00"}])
        students = [_make_student(f"S{i:03d}", "co1", "co1_se") for i in range(20)]
        interviews = self._run_scheduler([co], students)
        self.assertGreater(len(interviews), 0)
        for iv in interviews:
            start = _interview_start_hhmm(iv)
            self.assertNotIn(start, ["12:00", "12:30"],
                             f"Interview scheduled during break: {start}")

    def test_slot_before_break_allowed(self):
        """11:30 slot is valid (ends at 12:00 = break boundary, no overlap)."""
        co = _make_company("co1", breaks=[{"start": "12:00", "end": "13:00"}])
        students = [_make_student(f"S{i:03d}", "co1", "co1_se") for i in range(20)]
        interviews = self._run_scheduler([co], students)
        starts = {_interview_start_hhmm(iv) for iv in interviews}
        self.assertIn("11:30", starts, "11:30 slot should be usable (ends at 12:00, no overlap)")

    def test_slot_after_break_allowed(self):
        """13:00 slot is valid (starts exactly at break end)."""
        co = _make_company("co1", breaks=[{"start": "12:00", "end": "13:00"}])
        students = [_make_student(f"S{i:03d}", "co1", "co1_se") for i in range(20)]
        interviews = self._run_scheduler([co], students)
        starts = {_interview_start_hhmm(iv) for iv in interviews}
        self.assertIn("13:00", starts, "13:00 slot should be usable (starts at break end)")

    def test_settings_save_persists_company_break(self):
        co = _make_company("co1")
        _write(os.path.join(self.data_dir, "companies.json"), [co])
        dm = self._dm()
        company = dm.get_company("co1")
        company.breaks = [{"start": "12:00", "end": "13:00"}]
        dm.save_company(company)
        reloaded = dm.get_company("co1")
        self.assertEqual(reloaded.breaks, [{"start": "12:00", "end": "13:00"}])


# ══════════════════════════════════════════════════════════════════════════════
# Phase 5 — Panel-Level Break Override
# ══════════════════════════════════════════════════════════════════════════════


class TestPhase5_PanelBreaks(SchedulerTestBase):

    def test_panel_break_overrides_company_break(self):
        """Panel A has break 13:00–14:00; company break is 12:00–13:00.
        Panel A should be blocked at 13:00 (panel break) but free at 12:00."""
        roles = [{"id": "co1_se", "title": "SE", "company_id": "co1", "duration_minutes": 30}]
        panel = _make_panel("co1-P1", "Panel A", ["co1_se"],
                            breaks=[{"start": "13:00", "end": "14:00"}])
        co = _make_company("co1", roles=roles, panels=[panel],
                           breaks=[{"start": "12:00", "end": "13:00"}])
        students = [_make_student(f"S{i:03d}", "co1", "co1_se") for i in range(20)]
        interviews = self._run_scheduler([co], students)
        self.assertGreater(len(interviews), 0)
        starts = {_interview_start_hhmm(iv) for iv in interviews}
        # 13:00 must be excluded (panel break)
        self.assertNotIn("13:00", starts, "Panel override break at 13:00 not respected")
        self.assertNotIn("13:30", starts, "Panel override break at 13:30 not respected")
        # 12:00 should be available (company break overridden by panel break)
        self.assertIn("12:00", starts, "12:00 should be available since panel overrides company break")

    def test_panel_break_empty_inherits_company_break(self):
        """Panel with empty breaks=[] should inherit company break (Bug #5: documented behavior)."""
        roles = [{"id": "co1_se", "title": "SE", "company_id": "co1", "duration_minutes": 30}]
        panel = _make_panel("co1-P1", "Panel B", ["co1_se"], breaks=[])  # empty = inherit
        co = _make_company("co1", roles=roles, panels=[panel],
                           breaks=[{"start": "12:00", "end": "13:00"}])
        students = [_make_student(f"S{i:03d}", "co1", "co1_se") for i in range(20)]
        interviews = self._run_scheduler([co], students)
        for iv in interviews:
            start = _interview_start_hhmm(iv)
            self.assertNotIn(start, ["12:00", "12:30"],
                             f"Panel with empty breaks should inherit company break; got {start}")

    def test_panel_break_save_persists(self):
        from schedule_manager.data_manager import Panel
        co = _make_company("co1")
        _write(os.path.join(self.data_dir, "companies.json"), [co])
        dm = self._dm()
        company = dm.get_company("co1")
        company.panels = [Panel(panel_id="co1-P1", label="Panel 1",
                                job_role_ids=["co1_se"],
                                breaks=[{"start": "12:00", "end": "13:00"}])]
        dm.save_company(company)
        reloaded = dm.get_company("co1").panels[0]
        self.assertEqual(reloaded.breaks, [{"start": "12:00", "end": "13:00"}])


# ══════════════════════════════════════════════════════════════════════════════
# Phase 5 — Multi-Panel Staggered Breaks
# ══════════════════════════════════════════════════════════════════════════════


class TestPhase5_MultiPanelStaggeredBreaks(SchedulerTestBase):

    def _setup_staggered(self):
        """Panel A: SE role, break 12:00–13:00. Panel B: QA role, break 13:00–14:00."""
        roles = [
            {"id": "co1_se", "title": "SE", "company_id": "co1", "duration_minutes": 30},
            {"id": "co1_qa", "title": "QA", "company_id": "co1", "duration_minutes": 30},
        ]
        panels = [
            _make_panel("co1-P1", "Panel A", ["co1_se"],
                        breaks=[{"start": "12:00", "end": "13:00"}]),
            _make_panel("co1-P2", "Panel B", ["co1_qa"],
                        breaks=[{"start": "13:00", "end": "14:00"}]),
        ]
        co = _make_company("co1", roles=roles, panels=panels)
        students = (
            [_make_student(f"SE{i:02d}", "co1", "co1_se") for i in range(15)] +
            [_make_student(f"QA{i:02d}", "co1", "co1_qa") for i in range(15)]
        )
        return co, students

    def test_panel_a_excluded_12_to_13(self):
        co, students = self._setup_staggered()
        interviews = self._run_scheduler([co], students)
        pa_ivs = [iv for iv in interviews if iv["panel_id"] == "co1-P1"]
        self.assertGreater(len(pa_ivs), 0)
        for iv in pa_ivs:
            start = _interview_start_hhmm(iv)
            self.assertNotIn(start, ["12:00", "12:30"],
                             f"Panel A should be blocked 12:00–13:00, got {start}")

    def test_panel_b_excluded_13_to_14(self):
        co, students = self._setup_staggered()
        interviews = self._run_scheduler([co], students)
        pb_ivs = [iv for iv in interviews if iv["panel_id"] == "co1-P2"]
        self.assertGreater(len(pb_ivs), 0)
        for iv in pb_ivs:
            start = _interview_start_hhmm(iv)
            self.assertNotIn(start, ["13:00", "13:30"],
                             f"Panel B should be blocked 13:00–14:00, got {start}")

    def test_panel_b_can_interview_during_panel_a_break(self):
        """Panel B (QA) should be able to work during Panel A's break (12:00–13:00)."""
        co, students = self._setup_staggered()
        interviews = self._run_scheduler([co], students)
        pb_ivs = [iv for iv in interviews if iv["panel_id"] == "co1-P2"]
        pb_starts = {_interview_start_hhmm(iv) for iv in pb_ivs}
        self.assertTrue(
            "12:00" in pb_starts or "12:30" in pb_starts,
            "Panel B should be able to conduct interviews during Panel A's 12:00–13:00 break"
        )

    def test_panel_a_can_interview_during_panel_b_break(self):
        """Panel A (SE) should be able to work during Panel B's break (13:00–14:00)."""
        co, students = self._setup_staggered()
        interviews = self._run_scheduler([co], students)
        pa_ivs = [iv for iv in interviews if iv["panel_id"] == "co1-P1"]
        pa_starts = {_interview_start_hhmm(iv) for iv in pa_ivs}
        self.assertTrue(
            "13:00" in pa_starts or "13:30" in pa_starts,
            "Panel A should be able to conduct interviews during Panel B's 13:00–14:00 break"
        )

    def test_staggered_breaks_no_student_double_book(self):
        """A student with apps to both panels must not be double-booked."""
        roles = [
            {"id": "co1_se", "title": "SE", "company_id": "co1", "duration_minutes": 30},
            {"id": "co1_qa", "title": "QA", "company_id": "co1", "duration_minutes": 30},
        ]
        panels = [
            _make_panel("co1-P1", "Panel A", ["co1_se"],
                        breaks=[{"start": "12:00", "end": "13:00"}]),
            _make_panel("co1-P2", "Panel B", ["co1_qa"],
                        breaks=[{"start": "13:00", "end": "14:00"}]),
        ]
        co = _make_company("co1", roles=roles, panels=panels)
        # Student applies to both roles
        student = {
            "id": "DUAL", "name": "Dual Role", "email": "dual@example.com",
            "applications": [
                {"student_id": "DUAL", "company_id": "co1", "job_role_id": "co1_se",
                 "status": "applied", "priority": 1, "cv_link": ""},
                {"student_id": "DUAL", "company_id": "co1", "job_role_id": "co1_qa",
                 "status": "applied", "priority": 2, "cv_link": ""},
            ]
        }
        interviews = self._run_scheduler([co], [student])
        dual_ivs = sorted([iv for iv in interviews if iv["student_id"] == "DUAL"],
                          key=lambda x: x["start_time"])
        if len(dual_ivs) >= 2:
            end0 = datetime.fromisoformat(dual_ivs[0]["end_time"])
            start1 = datetime.fromisoformat(dual_ivs[1]["start_time"])
            self.assertLessEqual(end0, start1,
                                 f"Student DUAL is double-booked: {dual_ivs[0]['end_time']} overlaps {dual_ivs[1]['start_time']}")

    def test_design_gap_bug5_empty_panel_breaks_inherits_company(self):
        """
        Bug #5 DOCUMENTATION TEST — expected to FAIL until sentinel logic is implemented.

        Scenario: Company break 12:00–13:00. Panel C has breaks=[] (wants to work during
        that hour but can't express it). Panel C should ideally have 12:00 available but
        currently inherits the company break.

        This test is intentionally asserting the CURRENT (limited) behaviour to document
        Bug #5 as a known limitation.
        """
        roles = [{"id": "co1_se", "title": "SE", "company_id": "co1", "duration_minutes": 30}]
        panel_c = _make_panel("co1-P1", "Panel C", ["co1_se"], breaks=[])  # intended: no break
        co = _make_company("co1", roles=roles, panels=[panel_c],
                           breaks=[{"start": "12:00", "end": "13:00"}])
        students = [_make_student(f"S{i:03d}", "co1", "co1_se") for i in range(20)]
        interviews = self._run_scheduler([co], students)
        starts = {_interview_start_hhmm(iv) for iv in interviews}
        # Document current behaviour: 12:00 is NOT available (inherited break)
        # When Bug #5 is fixed, this assertion should be changed to assertIn("12:00", starts)
        self.assertNotIn("12:00", starts,
                         "Bug #5 documented: Panel C with breaks=[] inherits company break. "
                         "12:00 should be available after Bug #5 fix (sentinel logic).")


if __name__ == "__main__":
    unittest.main(verbosity=2)
