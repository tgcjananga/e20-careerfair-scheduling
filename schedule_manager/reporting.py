from typing import List, Dict
from schedule_manager.data_manager import Interview, Student, Company

def generate_html_report(interviews: List[Interview], students: List[Student], companies: List[Company]) -> str:
    # Organize data for easy rendering
    
    # 1. Company Schedules
    company_map = {c.id: c for c in companies}
    student_map = {s.id: s for s in students}
    
    company_schedules: Dict[str, List[Interview]] = {}
    for i in interviews:
        if i.company_id not in company_schedules:
            company_schedules[i.company_id] = []
        company_schedules[i.company_id].append(i)
        
    for cid in company_schedules:
        company_schedules[cid].sort(key=lambda x: x.start_time)

    html = f"""
    <html>
    <head>
        <title>Interview Schedule</title>
        <style>
            body {{ font-family: sans-serif; padding: 20px; }}
            h1, h2 {{ color: #333; }}
            .section {{ margin-bottom: 40px; }}
            table {{ border-collapse: collapse; width: 100%; margin-bottom: 20px; }}
            th, td {{ border: 1px solid #ddd; padding: 8px; text-align: left; }}
            th {{ background-color: #f2f2f2; }}
            .company-block {{ background: #fafafa; padding: 15px; border-radius: 8px; margin-bottom: 20px; border: 1px solid #eee; }}
        </style>
    </head>
    <body>
        <h1>Career Fair Interview Schedule</h1>
        
        <div class="section">
            <h2>Summary</h2>
            <p>Total Interviews Scheduled: <strong>{len(interviews)}</strong></p>
        </div>
        
        <div class="section">
            <h2>Schedule by Company</h2>
    """
    
    # Render Company Tables
    for c in companies:
        if c.id not in company_schedules:
            continue
            
        html += f"""
            <div class="company-block">
                <h3>{c.name} ({len(company_schedules[c.id])} interviews)</h3>
                <table>
                    <thead>
                        <tr>
                            <th>Time</th>
                            <th>Student</th>
                            <th>Role</th>
                        </tr>
                    </thead>
                    <tbody>
        """
        
        for interview in company_schedules[c.id]:
            student_name = student_map[interview.student_id].name
            time_str = interview.start_time.split("T")[1][:5] # Simple HH:MM extraction
            role_id = interview.job_role_id
            
            # Find role title (inefficient but fine for small n)
            role_title = role_id
            for r in c.job_roles:
                if r.id == role_id:
                    role_title = r.title
                    break
            
            html += f"""
                        <tr>
                            <td>{time_str}</td>
                            <td>{student_name}</td>
                            <td>{role_title}</td>
                        </tr>
            """
            
        html += """
                    </tbody>
                </table>
            </div>
        """
        
    html += """
    </body>
    </html>
    """
    
    return html

def generate_student_html_report(interviews: List[Interview], students: List[Student], companies: List[Company]) -> str:
    company_map = {c.id: c for c in companies}
    student_map = {s.id: s for s in students}
    
    # Organize by Student
    student_schedules: Dict[str, List[Interview]] = {}
    for i in interviews:
        if i.student_id not in student_schedules:
            student_schedules[i.student_id] = []
        student_schedules[i.student_id].append(i)
        
    for sid in student_schedules:
        student_schedules[sid].sort(key=lambda x: x.start_time)

    html = f"""
    <html>
    <head>
        <title>Student Interview Schedule</title>
        <style>
            body {{ font-family: sans-serif; padding: 20px; }}
            h1, h2 {{ color: #333; }}
            .section {{ margin-bottom: 40px; }}
            table {{ border-collapse: collapse; width: 100%; margin-bottom: 20px; }}
            th, td {{ border: 1px solid #ddd; padding: 8px; text-align: left; }}
            th {{ background-color: #f2f2f2; }}
            .student-block {{ background: #e8f4f8; padding: 15px; border-radius: 8px; margin-bottom: 20px; border: 1px solid #dde; page-break-inside: avoid; }}
        </style>
    </head>
    <body>
        <h1>Student Interview Schedules</h1>
        
        <div class="section">
            <h2>Summary</h2>
            <p>Total Interviews Scheduled: <strong>{len(interviews)}</strong></p>
        </div>
        
        <div class="section">
            <h2>Schedule by Student</h2>
    """
    
    # Sort students by name for easier lookup
    sorted_students = sorted(students, key=lambda s: s.name)
    
    for s in sorted_students:
        if s.id not in student_schedules:
            continue
            
        html += f"""
            <div class="student-block">
                <h3>{s.name} ({s.id})</h3>
                <table>
                    <thead>
                        <tr>
                            <th>Time</th>
                            <th>Company</th>
                            <th>Role</th>
                        </tr>
                    </thead>
                    <tbody>
        """
        
        for interview in student_schedules[s.id]:
            company = company_map[interview.company_id]
            time_str = interview.start_time.split("T")[1][:5]
            
            # Find role title
            role_title = interview.job_role_id
            for r in company.job_roles:
                if r.id == interview.job_role_id:
                    role_title = r.title
                    break
            
            html += f"""
                        <tr>
                            <td>{time_str}</td>
                            <td>{company.name}</td>
                            <td>{role_title}</td>
                        </tr>
            """
            
        html += """
                    </tbody>
                </table>
            </div>
        """
        
    html += """
    </body>
    </html>
    """
    return html
