import os
import re
import tempfile
import unittest

import database
from app import app, assign_teachers_to_sessions, database_connection
from database import initialize_database
from werkzeug.security import check_password_hash


class StudentHubAppTests(unittest.TestCase):
    def test_initialize_database_bootstraps_empty_database_without_demo_records(self):
        original_database = database.DATABASE
        with tempfile.TemporaryDirectory() as directory:
            database.DATABASE = os.path.join(directory, "fresh.db")
            try:
                initialize_database()
                with database_connection() as connection:
                    courses = connection.execute(
                        "SELECT name FROM courses ORDER BY name"
                    ).fetchall()
                    course_sequence = connection.execute(
                        "SELECT seq FROM sqlite_sequence WHERE name = 'courses'"
                    ).fetchone()[0]
                    student_count = connection.execute(
                        "SELECT COUNT(*) FROM students"
                    ).fetchone()[0]
                    tables = {
                        row["name"]
                        for row in connection.execute(
                            "SELECT name FROM sqlite_master WHERE type = 'table'"
                        )
                    }
                self.assertEqual(
                    {course["name"] for course in courses},
                    {"BCA", "BSc IT", "MCA", "BTech Computer Science", "BBA", "MCom"},
                )
                self.assertEqual(student_count, 0)
                self.assertTrue(
                    {"admins", "courses", "students", "teachers", "timetable"}
                    .issubset(tables)
                )
                initialize_database()
                with database_connection() as connection:
                    repeated_course_sequence = connection.execute(
                        "SELECT seq FROM sqlite_sequence WHERE name = 'courses'"
                    ).fetchone()[0]
                self.assertEqual(course_sequence, repeated_course_sequence)
            finally:
                database.DATABASE = original_database

    def setUp(self):
        self.temp_directory = tempfile.TemporaryDirectory()
        self.original_database = database.DATABASE
        database.DATABASE = os.path.join(self.temp_directory.name, "test.db")
        with database_connection() as connection:
            connection.executescript(
                """
                CREATE TABLE courses (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL UNIQUE
                );
                CREATE TABLE students (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    email TEXT NOT NULL UNIQUE,
                    phone TEXT,
                    gender TEXT,
                    course_id INTEGER NOT NULL,
                    date_of_birth TEXT,
                    enrollment_date TEXT DEFAULT CURRENT_DATE,
                    status TEXT NOT NULL DEFAULT 'Active',
                    FOREIGN KEY (course_id) REFERENCES courses(id)
                );
                CREATE TABLE admins (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    username TEXT NOT NULL UNIQUE,
                    password_hash TEXT NOT NULL
                );
                CREATE TABLE teachers (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    email TEXT NOT NULL UNIQUE,
                    phone TEXT,
                    course_id INTEGER NOT NULL,
                    qualification TEXT,
                    hire_date TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'Active',
                    FOREIGN KEY (course_id) REFERENCES courses(id)
                );
                CREATE TABLE timetable (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    course_id INTEGER NOT NULL,
                    teacher_id INTEGER NOT NULL,
                    subject TEXT NOT NULL,
                    weekday TEXT NOT NULL CHECK (
                        weekday IN ('Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday')
                    ),
                    period INTEGER NOT NULL CHECK (period BETWEEN 1 AND 6),
                    FOREIGN KEY (course_id) REFERENCES courses(id) ON DELETE RESTRICT,
                    FOREIGN KEY (teacher_id) REFERENCES teachers(id) ON DELETE RESTRICT,
                    UNIQUE (course_id, weekday, period),
                    UNIQUE (teacher_id, weekday, period)
                );
                CREATE TABLE timetable_seed (
                    id INTEGER PRIMARY KEY CHECK (id = 1),
                    seeded_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                INSERT INTO courses (name) VALUES ('BCA'), ('MCA');
                """
            )
        app.config.update(
            TESTING=True,
            SECRET_KEY="test-only-secret",
            SESSION_COOKIE_SECURE=False,
        )
        self.client = app.test_client()

    def tearDown(self):
        database.DATABASE = self.original_database
        self.temp_directory.cleanup()

    def csrf_token(self, path):
        response = self.client.get(path)
        self.assertEqual(response.status_code, 200)
        match = re.search(rb'name="csrf_token" value="([^"]+)"', response.data)
        self.assertIsNotNone(match)
        return match.group(1).decode()

    def create_admin(self):
        token = self.csrf_token("/setup")
        return self.client.post(
            "/setup",
            data={
                "csrf_token": token,
                "username": "admin",
                "password": "a-very-long-test-password",
                "confirm_password": "a-very-long-test-password",
            },
        )

    def test_first_run_setup_hashes_password_and_closes_setup(self):
        response = self.create_admin()
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.headers["Location"], "/dashboard")
        with database_connection() as connection:
            admin = connection.execute(
                "SELECT username, password_hash FROM admins"
            ).fetchone()
        self.assertEqual(admin["username"], "admin")
        self.assertTrue(
            check_password_hash(admin["password_hash"], "a-very-long-test-password")
        )
        self.assertNotEqual(admin["password_hash"], "a-very-long-test-password")
        self.assertEqual(self.client.get("/setup").headers["Location"], "/login")

    def test_csrf_is_required_and_private_pages_require_login(self):
        self.assertEqual(self.client.get("/about").status_code, 200)
        api_response = self.client.get("/api/students")
        self.assertEqual(api_response.status_code, 401)
        self.assertEqual(api_response.get_json(), {"error": "Authentication required."})
        response = self.client.get("/students")
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.headers["Location"], "/login")
        response = self.client.get("/teachers")
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.headers["Location"], "/login")
        response = self.client.get("/timetable")
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.headers["Location"], "/login")
        response = self.client.post(
            "/setup",
            data={
                "username": "admin",
                "password": "a-very-long-test-password",
                "confirm_password": "a-very-long-test-password",
            },
        )
        self.assertEqual(response.status_code, 400)

    def test_login_student_crud_search_filters_export_and_dashboard(self):
        self.create_admin()
        with self.client.session_transaction() as session:
            session.clear()

        login_response = self.client.post(
            "/login",
            data={
                "csrf_token": self.csrf_token("/login"),
                "username": "admin",
                "password": "a-very-long-test-password",
            },
        )
        self.assertEqual(login_response.status_code, 302)
        self.assertEqual(login_response.headers["Location"], "/dashboard")

        form_token = self.csrf_token("/students/new")
        create_response = self.client.post(
            "/students/new",
            data={
                "csrf_token": form_token,
                "name": "Jamie Example",
                "email": "jamie@example.test",
                "phone": "123456",
                "gender": "",
                "course_id": "1",
                "date_of_birth": "2002-03-04",
                "enrollment_date": "2025-08-01",
                "status": "Active",
            },
        )
        self.assertEqual(create_response.status_code, 302)

        listing = self.client.get("/students?q=Jamie&status=Active&course_id=1")
        self.assertEqual(listing.status_code, 200)
        self.assertIn(b"Jamie Example", listing.data)
        self.assertIn(b"1 record", listing.data)

        api_response = self.client.get(
            "/api/students?q=Jamie&status=Active&course_id=1"
        )
        self.assertEqual(api_response.status_code, 200)
        self.assertEqual(api_response.mimetype, "application/json")
        api_data = api_response.get_json()
        self.assertEqual(api_data["pagination"]["total"], 1)
        self.assertEqual(api_data["pagination"]["page"], 1)
        self.assertEqual(
            api_data["students"],
            [
                {
                    "id": 1,
                    "name": "Jamie Example",
                    "email": "jamie@example.test",
                    "status": "Active",
                    "course": "BCA",
                }
            ],
        )

        with database_connection() as connection:
            student_id = connection.execute(
                "SELECT id FROM students WHERE email = ?", ("jamie@example.test",)
            ).fetchone()["id"]

        detail = self.client.get(f"/students/{student_id}")
        self.assertEqual(detail.status_code, 200)
        self.assertIn(b"jamie@example.test", detail.data)

        edit_token = self.csrf_token(f"/students/{student_id}/edit")
        edited = self.client.post(
            f"/students/{student_id}/edit",
            data={
                "csrf_token": edit_token,
                "name": "Jamie Updated",
                "email": "jamie@example.test",
                "phone": "",
                "gender": "",
                "course_id": "2",
                "date_of_birth": "",
                "enrollment_date": "2025-08-01",
                "status": "Inactive",
            },
        )
        self.assertEqual(edited.status_code, 302)
        filtered = self.client.get("/students?status=Inactive&course_id=2")
        self.assertIn(b"Jamie Updated", filtered.data)
        self.assertNotIn(b"Jamie Example", filtered.data)

        export = self.client.get("/students/export.csv?status=Inactive&course_id=2")
        self.assertEqual(export.status_code, 200)
        self.assertIn("attachment; filename=students.csv", export.headers["Content-Disposition"])
        self.assertIn(b"Jamie Updated", export.data)

        dashboard = self.client.get("/dashboard")
        self.assertEqual(dashboard.status_code, 200)
        self.assertIn(b"Enrollments over the last six months", dashboard.data)
        self.assertIn(b"Inactive Teachers", dashboard.data)

        delete_token = self.csrf_token(f"/students/{student_id}")
        deleted = self.client.post(
            f"/students/{student_id}/delete", data={"csrf_token": delete_token}
        )
        self.assertEqual(deleted.status_code, 302)
        self.assertEqual(self.client.get(f"/students/{student_id}").status_code, 404)

    def test_student_form_rejects_invalid_data(self):
        self.create_admin()
        token = self.csrf_token("/students/new")
        response = self.client.post(
            "/students/new",
            data={
                "csrf_token": token,
                "name": "",
                "email": "not-an-email",
                "course_id": "999",
                "date_of_birth": "",
                "enrollment_date": "not-a-date",
                "status": "Unknown",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Enter a valid email address.", response.data)
        with database_connection() as connection:
            self.assertEqual(
                connection.execute("SELECT COUNT(*) FROM students").fetchone()[0], 0
            )

    def test_student_list_paginates(self):
        self.create_admin()
        with database_connection() as connection:
            connection.executemany(
                """
                INSERT INTO students (name, email, course_id, status)
                VALUES (?, ?, 1, 'Active')
                """,
                [
                    (f"Student {number:02}", f"student{number}@example.test")
                    for number in range(12)
                ],
            )
            connection.commit()
        first_page = self.client.get("/students")
        self.assertIn(b"Page 1 of 2", first_page.data)
        second_page = self.client.get("/students?page=2")
        self.assertIn(b"Page 2 of 2", second_page.data)

    def test_teacher_crud_search_filter_and_export(self):
        self.create_admin()
        create_token = self.csrf_token("/teachers/new")
        created = self.client.post(
            "/teachers/new",
            data={
                "csrf_token": create_token,
                "name": "Taylor Teacher",
                "email": "taylor@example.test",
                "phone": "555-0100",
                "course_id": "1",
                "qualification": "M.Ed.",
                "hire_date": "2024-08-15",
                "status": "Active",
            },
        )
        self.assertEqual(created.status_code, 302)
        self.assertEqual(created.headers["Location"], "/teachers")

        listing = self.client.get("/teachers?q=555-0100&status=Active&course_id=1")
        self.assertEqual(listing.status_code, 200)
        self.assertIn(b"Taylor Teacher", listing.data)

        with database_connection() as connection:
            teacher_id = connection.execute(
                "SELECT id FROM teachers WHERE email = ?",
                ("taylor@example.test",),
            ).fetchone()["id"]

        detail = self.client.get(f"/teachers/{teacher_id}")
        self.assertEqual(detail.status_code, 200)
        self.assertIn(b"M.Ed.", detail.data)

        edit_token = self.csrf_token(f"/teachers/{teacher_id}/edit")
        edited = self.client.post(
            f"/teachers/{teacher_id}/edit",
            data={
                "csrf_token": edit_token,
                "name": "Taylor Updated",
                "email": "taylor@example.test",
                "phone": "555-0101",
                "course_id": "2",
                "qualification": "Ph.D.",
                "hire_date": "2024-08-15",
                "status": "Inactive",
            },
        )
        self.assertEqual(edited.status_code, 302)
        self.assertEqual(edited.headers["Location"], f"/teachers/{teacher_id}")
        self.assertIn(b"Taylor Updated", self.client.get("/teachers?status=Inactive").data)

        export = self.client.get("/teachers/export.csv?status=Inactive&course_id=2")
        self.assertEqual(export.status_code, 200)
        self.assertIn("attachment; filename=teachers.csv", export.headers["Content-Disposition"])
        self.assertIn(b"Taylor Updated", export.data)

        delete_token = self.csrf_token(f"/teachers/{teacher_id}")
        deleted = self.client.post(
            f"/teachers/{teacher_id}/delete", data={"csrf_token": delete_token}
        )
        self.assertEqual(deleted.status_code, 302)
        self.assertEqual(self.client.get(f"/teachers/{teacher_id}").status_code, 404)

    def test_teacher_form_rejects_invalid_data(self):
        self.create_admin()
        token = self.csrf_token("/teachers/new")
        response = self.client.post(
            "/teachers/new",
            data={
                "csrf_token": token,
                "name": "",
                "email": "not-an-email",
                "course_id": "999",
                "qualification": "Q" * 151,
                "hire_date": "not-a-date",
                "status": "Unknown",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Enter a valid email address.", response.data)
        self.assertIn(b"Hire date must be a valid date.", response.data)
        with database_connection() as connection:
            self.assertEqual(
                connection.execute("SELECT COUNT(*) FROM teachers").fetchone()[0], 0
            )

    def test_timetable_prevents_course_and_teacher_conflicts(self):
        self.create_admin()
        with database_connection() as connection:
            connection.executemany(
                """
                INSERT INTO teachers
                    (name, email, course_id, hire_date, status)
                VALUES (?, ?, ?, '2024-01-01', 'Active')
                """,
                [
                    ("Teacher One", "teacher1@example.test", 1),
                    ("Teacher Two", "teacher2@example.test", 2),
                ],
            )
            connection.execute(
                """
                INSERT INTO timetable
                    (course_id, teacher_id, subject, weekday, period)
                VALUES (1, 1, 'Existing Lecture', 'Monday', 1)
                """
            )
            connection.commit()

        page = self.client.get("/timetable?course_id=1")
        self.assertEqual(page.status_code, 200)
        self.assertIn(b"Existing Lecture", page.data)
        self.assertIn(b"Lunch break 12:00", page.data)

        token = re.search(
            rb'name="csrf_token" value="([^"]+)"', page.data
        ).group(1).decode()
        teacher_conflict = self.client.post(
            "/timetable?course_id=2",
            data={
                "csrf_token": token,
                "course_id": "2",
                "teacher_id": "1",
                "subject": "Conflicting Lecture",
                "weekday": "Monday",
                "period": "1",
            },
        )
        self.assertEqual(teacher_conflict.status_code, 302)
        with database_connection() as connection:
            self.assertEqual(
                connection.execute(
                    "SELECT COUNT(*) FROM timetable WHERE subject = 'Conflicting Lecture'"
                ).fetchone()[0],
                0,
            )

        course_conflict = self.client.post(
            "/timetable?course_id=1",
            data={
                "csrf_token": token,
                "course_id": "1",
                "teacher_id": "2",
                "subject": "Another Conflicting Lecture",
                "weekday": "Monday",
                "period": "1",
            },
        )
        self.assertEqual(course_conflict.status_code, 302)
        valid_entry = self.client.post(
            "/timetable?course_id=1",
            data={
                "csrf_token": token,
                "course_id": "1",
                "teacher_id": "2",
                "subject": "Artificial Intelligence",
                "weekday": "Monday",
                "period": "2",
            },
        )
        self.assertEqual(valid_entry.status_code, 302)
        with database_connection() as connection:
            self.assertEqual(
                connection.execute(
                    "SELECT COUNT(*) FROM timetable WHERE subject = 'Artificial Intelligence'"
                ).fetchone()[0],
                1,
            )

    def test_timetable_assignments_use_multiple_subject_appropriate_teachers(self):
        teachers = [
            {
                "id": 1,
                "name": "Computing Teacher One",
                "qualification": "M.Sc., Information Technology",
            },
            {
                "id": 2,
                "name": "Computing Teacher Two",
                "qualification": "Ph.D., Computer Science",
            },
            {
                "id": 3,
                "name": "Business Teacher",
                "qualification": "MBA, Human Resources",
            },
        ]
        sessions = [
            {
                "course_id": 1,
                "subject": "Programming Fundamentals",
                "weekday": "Monday",
                "period": 1,
            },
            {
                "course_id": 2,
                "subject": "Principles of Management",
                "weekday": "Monday",
                "period": 1,
            },
            {
                "course_id": 1,
                "subject": "Data Structures",
                "weekday": "Monday",
                "period": 2,
            },
        ]

        assignments = assign_teachers_to_sessions(sessions, teachers)
        computing_course_teachers = {
            teacher_id
            for item, teacher_id in assignments
            if item["course_id"] == 1
        }
        teacher_for_management = next(
            teacher_id
            for item, teacher_id in assignments
            if item["subject"] == "Principles of Management"
        )
        self.assertEqual(len(computing_course_teachers), 2)
        self.assertEqual(teacher_for_management, 3)
        business_teacher_ids = {
            teacher["id"]
            for teacher in teachers
            if "mba" in teacher["qualification"].lower()
        }
        technical_terms = (
            "program",
            "algorithm",
            "data structure",
            "database",
            "web",
            "network",
            "cloud",
            "cyber",
            "artificial intelligence",
            "machine learning",
            "operating system",
            "computer",
            "information technology",
            "software",
            "python",
        )
        for item, teacher_id in assignments:
            is_business_technology = any(
                term in item["subject"].lower()
                for term in (
                    "information system",
                    "digital commerce",
                    "analytics",
                    "data analysis",
                )
            ) or (
                "information technology" in item["subject"].lower()
                and (
                    "business" in item["subject"].lower()
                    or "accounting" in item["subject"].lower()
                )
            )
            if any(term in item["subject"].lower() for term in technical_terms):
                if not is_business_technology:
                    self.assertNotIn(teacher_id, business_teacher_ids)
