import random
from schedule_manager.data_manager import DataManager, Student, Company, JobRole, Application, AppStatus

def seed():
    dm = DataManager()
    
    # 1. Create 16 Companies
    companies = []
    job_roles_titles = ["Software Engineer", "Data Scientist", "DevOps Engineer", "QA Engineer", "Product Manager"]
    
    for i in range(1, 17):
        c_id = f"C{i:03d}"
        c_name = f"Company {i}"
        
        # Each company has 1-3 job roles
        c_roles = []
        num_roles = random.randint(1, 3)
        selected_titles = random.sample(job_roles_titles, num_roles)
        
        for j, title in enumerate(selected_titles):
            r_id = f"{c_id}-R{j+1}"
            c_roles.append(JobRole(id=r_id, title=title, company_id=c_id))
            
        companies.append(Company(id=c_id, name=c_name, job_roles=c_roles))
        
    dm.save_companies(companies)
    print(f"Created {len(companies)} companies.")

    # 2. Create 90 Students
    students = []
    for i in range(1, 91):
        s_id = f"S{i:03d}"
        students.append(Student(
            id=s_id, 
            name=f"Student {i}", 
            email=f"student{i}@university.edu"
        ))
    
    # 3. Simulate Applications (Max 7 per student)
    # The user manual says: "companies will sort listed each students... sometimes they send priority"
    # We will simulate that:
    # - Students apply to random 3-7 companies
    # - Companies randomly shortlist ~30% of applicants
    # - Companies randomly assign priority 1-5 to some shortlisted candidates
    
    all_job_roles = [r for c in companies for r in c.job_roles]
    
    for student in students:
        num_apps = random.randint(3, 7)
        applied_roles = random.sample(all_job_roles, num_apps)
        
        for role in applied_roles:
            # Default status is APPLIED
            status = AppStatus.APPLIED
            priority = None
            
            # Randomly decide if shortlisted (30% chance)
            if random.random() < 0.3:
                status = AppStatus.SHORTLISTED
                # Randomly decide if prioritized (50% chance if shortlisted)
                if random.random() < 0.5:
                    priority = random.randint(1, 5)
            
            app = Application(
                student_id=student.id,
                company_id=role.company_id,
                job_role_id=role.id,
                status=status,
                priority=priority
            )
            student.applications.append(app)
            
    dm.save_students(students)
    print(f"Created {len(students)} students with applications.")

if __name__ == "__main__":
    seed()
