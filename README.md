# Career Fair Interview Scheduler

A Python-based automated interview scheduling system for university career fairs. It matches students to companies based on applications, priorities, and time constraints using Google's **OR-Tools** for optimal scheduling.

## Features
*   **Optimal Scheduling**: Uses Constraint Programming (CP-SAT) to maximize the number of interviews.
*   **Conflict Resolution**: Ensures no double-booking for students or companies.
*   **Priority Handling**: Prioritizes "Shortlisted" candidates and higher-ranked applications.
*   **Web Dashboard**: View schedules, stats, and manage data via a local browser interface.
*   **Export**: Download schedules as CSV for students and companies.

## 🛠️ Setup & Installation

The project uses Python's standard library for the core web server but requires `ortools` for the advanced scheduler.

### 1. Prerequisites
*   Python 3.8+
*   `pip` (Python Package Manager)

### 2. Create Virtual Environment
Since the system environment might be managed externally, it's best to use a virtual environment:

```bash
# Create virtual environment named 'venv'
python3 -m venv venv

# Activate the environment
# On Linux/Mac:
source venv/bin/activate
# On Windows:
# venv\Scripts\activate
```

### 3. Install Dependencies
```bash
pip install -r requirements.txt
```

## 🏃‍♂️ How to Run

1.  **Start the Server**:
    ```bash
    python3 server.py
    ```
2.  **Open Dashboard**:
    Go to [http://localhost:8000](http://localhost:8000) in your web browser.

3.  **Generate Schedule**:
    *   Click the **"Generate Schedule"** button on the dashboard.
    *   The system will process all applications and optimize the slots.
    *   View results in the **Students** or **Companies** tabs.

## 🧠 How the Scheduler Works (OR-Tools)

The scheduler models the problem as a **Constraint Satisfaction Problem (CSP)**:

### 1. Variables
*   The valid applications are mapped to possible time slots.
*   `x[student, company, slot]` is a binary variable (1 = scheduled, 0 = not scheduled).

### 2. Constraints (Hard Rules)
*   **One Interview Per Slot (Student)**: A student cannot have two interviews at the same time.
*   **One Interview Per Slot (Company)**: A company panel can only interview one student at a time.
*   **Single Occurrence**: An application (Student + Company pair) can be scheduled at most once.

### 3. Objective (Optimization)
The solver tries to **Maximize** the total score:
*   **Base Score**: Every scheduled interview gets points.
*   **Shortlist Bonus**: Shortlisted applications get significantly higher points to ensure they are prioritized.
*   **Priority Bonus**: Applications ranked higher (e.g., Priority 1 vs 5) get extra points.

This ensures that while we try to fit everyone in, the most important interviews are secured first!

## 📂 Project Structure
*   `server.py`: Main web server and API.
*   `schedule_manager/`:
    *   `scheduler.py`: The logic engine (OR-Tools).
    *   `data_manager.py`: Handles JSON data loading/saving.
    *   `data/`: Stores `students.json`, `companies.json`, and `schedule.json`.
*   `web/`: Frontend HTML/JS files.
