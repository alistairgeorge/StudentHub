import csv
import io
import itertools
import os
import re
import secrets
import sqlite3
from contextlib import contextmanager
from datetime import date
from functools import wraps

from flask import (
    Flask,
    abort,
    flash,
    jsonify,
    make_response,
    redirect,
    render_template,
    request,
    session,
    url_for,
)
from werkzeug.security import check_password_hash, generate_password_hash

from database import get_db_connection, initialize_database

app = Flask(__name__)
app.config["SECRET_KEY"] = os.environ.get("FLASK_SECRET_KEY") or secrets.token_hex(32)
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
app.config["SESSION_COOKIE_SECURE"] = os.environ.get(
    "SESSION_COOKIE_SECURE", ""
).lower() in ("1", "true")

if not os.environ.get("FLASK_SECRET_KEY"):
    app.logger.warning(
        "FLASK_SECRET_KEY is not set; sessions will not survive application restarts."
    )

initialize_database()


@contextmanager
def database_connection():
    connection = get_db_connection()
    try:
        yield connection
    finally:
        connection.close()


WEEKDAYS = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday")
PERIODS = (
    {"number": 1, "start": "09:00", "end": "10:00"},
    {"number": 2, "start": "10:00", "end": "11:00"},
    {"number": 3, "start": "11:00", "end": "12:00"},
    {"number": 4, "start": "13:00", "end": "14:00"},
    {"number": 5, "start": "14:00", "end": "15:00"},
    {"number": 6, "start": "15:00", "end": "16:00"},
)


def assign_teachers_to_sessions(sessions, teachers):
    weekday_order = {weekday: index for index, weekday in enumerate(WEEKDAYS)}
    grouped_sessions = {}
    for item in sessions:
        key = (weekday_order[item["weekday"]], item["period"])
        grouped_sessions.setdefault(key, []).append(item)

    if any(len(items) > len(teachers) for items in grouped_sessions.values()):
        raise ValueError("There are not enough active teachers for the timetable slots.")

    course_teacher_load = {}
    assigned = []
    for slot in sorted(grouped_sessions):
        items = grouped_sessions[slot]
        best_assignment = None
        best_score = None
        for teacher_group in itertools.permutations(teachers, len(items)):
            score = 0
            valid_assignment = True
            for item, teacher in zip(items, teacher_group):
                qualification = (teacher["qualification"] or "").lower()
                subject = item["subject"].lower()
                course_id = item["course_id"]
                count = course_teacher_load.get((course_id, teacher["id"]), 0)
                score += count * count * 0.1

                is_business_core = any(
                    term in subject
                    for term in (
                        "management",
                        "marketing",
                        "financial",
                        "accounting",
                        "commerce",
                    )
                )
                is_research = "research methods" in subject
                is_business_technology = any(
                    term in subject
                    for term in (
                        "information system",
                        "digital commerce",
                        "analytics",
                        "data analysis",
                    )
                ) or (
                    "information technology" in subject
                    and ("business" in subject or "accounting" in subject)
                )
                is_technology_topic = any(
                    term in subject
                    for term in (
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
                )
                is_business_specialist = "mba" in qualification or "human resource" in qualification
                is_computing_specialist = any(
                    term in qualification
                    for term in (
                        "computer",
                        "information technology",
                        "mca",
                        "m.sc.",
                        "m.sc",
                        "ph.d.",
                        "phd",
                    )
                )

                if (
                    is_business_specialist
                    and is_technology_topic
                    and not is_business_technology
                ):
                    valid_assignment = False
                    break

                if is_business_core:
                    score += -20 if is_business_specialist else 20
                elif is_research:
                    score += (
                        -20
                        if "ph.d." in qualification or "phd" in qualification
                        else 20 if is_business_specialist else 0
                    )
                elif is_business_technology:
                    score += -6 if is_computing_specialist else 8
                elif is_technology_topic:
                    score += 100 if is_business_specialist else (-10 if is_computing_specialist else 0)
                if ("artificial intelligence" in subject or "machine learning" in subject) and (
                    "ph.d." in qualification or "phd" in qualification
                ):
                    score -= 4
                if "computer engineering" in qualification and any(
                    term in subject
                    for term in ("architecture", "operating systems", "networks")
                ):
                    score -= 5

            if not valid_assignment:
                continue
            if best_score is None or score < best_score:
                best_score = score
                best_assignment = teacher_group

        if best_assignment is None:
            raise ValueError("Unable to assign teachers to timetable slots.")
        for item, teacher in zip(items, best_assignment):
            assigned.append((item, teacher["id"]))
            key = (item["course_id"], teacher["id"])
            course_teacher_load[key] = course_teacher_load.get(key, 0) + 1

    return assigned


def seed_initial_timetable():
    required_teacher_emails = (
        "ananya.rao@example.test",
        "rohan.iyer@example.test",
        "meera.nair@example.test",
        "vikram.desai@example.test",
        "priya.menon@example.test",
    )
    subject_lists = {
        "BCA": (
            "Programming Fundamentals",
            "Data Structures",
            "Database Systems",
            "Web Technologies",
            "Computer Networks",
            "Artificial Intelligence",
        ),
        "BSc IT": (
            "Information Technology",
            "Python Programming",
            "Cloud Computing",
            "Cybersecurity",
            "Database Management",
            "Artificial Intelligence",
        ),
        "MCA": (
            "Advanced Algorithms",
            "Software Engineering",
            "Machine Learning",
            "Database Systems",
            "Cloud Architecture",
            "Artificial Intelligence",
        ),
        "BTech Computer Science": (
            "Algorithms",
            "Computer Architecture",
            "Operating Systems",
            "Computer Networks",
            "Machine Learning",
            "Artificial Intelligence",
        ),
        "BBA": (
            "Business Information Systems",
            "Digital Commerce",
            "Business Data Analytics",
            "Principles of Management",
            "Marketing Fundamentals",
            "Information Technology for Business",
        ),
        "MCom": (
            "Financial Information Systems",
            "Business Analytics",
            "Research Methods",
            "Digital Commerce",
            "Data Analysis for Commerce",
            "Information Technology for Accounting",
        ),
    }

    with database_connection() as connection:
        connection.execute("BEGIN IMMEDIATE")
        if connection.execute(
            "SELECT 1 FROM timetable_seed WHERE id = 1"
        ).fetchone():
            connection.rollback()
            return

        courses = {
            row["name"]: row["id"]
            for row in connection.execute("SELECT id, name FROM courses")
        }
        teacher_by_email = {
            row["email"]: row
            for row in connection.execute(
                """
                SELECT id, email, qualification
                FROM teachers WHERE status = 'Active'
                """
            )
        }
        required_courses = (
            "BCA",
            "BSc IT",
            "MCA",
            "BTech Computer Science",
            "BBA",
            "MCom",
        )
        if any(name not in courses for name in required_courses):
            connection.rollback()
            app.logger.warning("Skipping example timetable: required courses are missing.")
            return
        if any(email not in teacher_by_email for email in required_teacher_emails):
            connection.rollback()
            app.logger.warning("Skipping example timetable: required active teachers are missing.")
            return

        active_teachers = [
            teacher_by_email[email] for email in required_teacher_emails
        ]
        sessions = []
        for weekday_index, weekday in enumerate(WEEKDAYS):
            for period in PERIODS:
                omitted_course = required_courses[period["number"] - 1]
                for course_name in required_courses:
                    if course_name == omitted_course:
                        continue
                    subject_options = subject_lists[course_name]
                    subject = subject_options[
                        (weekday_index + period["number"] - 1) % len(subject_options)
                    ]
                    sessions.append(
                        {
                            "course_id": courses[course_name],
                            "subject": subject,
                            "weekday": weekday,
                            "period": period["number"],
                        }
                    )

        assignments = assign_teachers_to_sessions(sessions, active_teachers)
        connection.executemany(
            """
            INSERT INTO timetable (course_id, teacher_id, subject, weekday, period)
            VALUES (?, ?, ?, ?, ?)
            """,
            [
                (
                    item["course_id"],
                    teacher_id,
                    item["subject"],
                    item["weekday"],
                    item["period"],
                )
                for item, teacher_id in assignments
            ],
        )
        connection.execute("INSERT INTO timetable_seed (id) VALUES (1)")
        connection.commit()


seed_initial_timetable()


@app.before_request
def protect_post_requests():
    if request.method == "POST":
        submitted_token = request.form.get("csrf_token", "")
        session_token = session.get("csrf_token", "")
        if not session_token or not secrets.compare_digest(
            submitted_token, session_token
        ):
            abort(400, description="The form expired or could not be verified.")


@app.context_processor
def inject_template_values():
    token = session.setdefault("csrf_token", secrets.token_urlsafe(32))
    return {"csrf_token": token}


def login_required(view):
    @wraps(view)
    def wrapped_view(*args, **kwargs):
        if "admin_id" not in session:
            return redirect(url_for("login"))
        return view(*args, **kwargs)

    return wrapped_view


def has_admin_account():
    with database_connection() as connection:
        return connection.execute("SELECT 1 FROM admins LIMIT 1").fetchone() is not None


def get_courses():
    with database_connection() as connection:
        return connection.execute("SELECT id, name FROM courses ORDER BY name").fetchall()


def get_dashboard_data():
    with database_connection() as connection:
        cursor = connection.cursor()

        cursor.execute("SELECT COUNT(*) AS total_students FROM students")
        total_students = cursor.fetchone()["total_students"]

        cursor.execute(
            "SELECT COUNT(*) AS active_students FROM students WHERE status = 'Active'"
        )
        active_students = cursor.fetchone()["active_students"]

        cursor.execute(
            "SELECT COUNT(*) AS inactive_students FROM students WHERE status = 'Inactive'"
        )
        inactive_students = cursor.fetchone()["inactive_students"]

        cursor.execute("SELECT COUNT(*) AS total_courses FROM courses")
        total_courses = cursor.fetchone()["total_courses"]

        cursor.execute("SELECT COUNT(*) AS total_teachers FROM teachers")
        total_teachers = cursor.fetchone()["total_teachers"]

        cursor.execute(
            "SELECT COUNT(*) AS active_teachers FROM teachers WHERE status = 'Active'"
        )
        active_teachers = cursor.fetchone()["active_teachers"]

        cursor.execute(
            "SELECT COUNT(*) AS inactive_teachers FROM teachers WHERE status = 'Inactive'"
        )
        inactive_teachers = cursor.fetchone()["inactive_teachers"]

        cursor.execute(
            """
            SELECT
                students.id,
                students.name,
                courses.name AS course,
                students.status
            FROM students
            INNER JOIN courses
                ON students.course_id = courses.id
            ORDER BY students.id DESC
            LIMIT 5
            """
        )
        recent_students = cursor.fetchall()

        cursor.execute(
            """
            SELECT
                courses.name AS course,
                COUNT(students.id) AS total
            FROM courses
            LEFT JOIN students
                ON courses.id = students.course_id
            GROUP BY courses.id, courses.name
            ORDER BY total DESC, courses.name
            """
        )
        raw_course_stats = cursor.fetchall()

        today = date.today()
        months = []
        for month_offset in range(5, -1, -1):
            month_index = today.year * 12 + today.month - 1 - month_offset
            year, month_number = divmod(month_index, 12)
            month_number += 1
            months.append((f"{year:04d}-{month_number:02d}", date(year, month_number, 1)))

        cursor.execute(
            """
            SELECT strftime('%Y-%m', enrollment_date) AS month, COUNT(*) AS total
            FROM students
            WHERE enrollment_date >= ?
            GROUP BY strftime('%Y-%m', enrollment_date)
            """,
            (months[0][1].isoformat(),),
        )
        monthly_totals = {row["month"]: row["total"] for row in cursor.fetchall()}

    enrollment_stats = [
        {
            "label": month.strftime("%b %Y"),
            "total": monthly_totals.get(month_key, 0),
        }
        for month_key, month in months
    ]
    max_monthly_total = max((item["total"] for item in enrollment_stats), default=0)
    for item in enrollment_stats:
        item["width"] = (
            round(item["total"] / max_monthly_total * 100)
            if max_monthly_total
            else 0
        )

    max_course_total = max((row["total"] for row in raw_course_stats), default=0)
    course_stats = [
        {
            "course": row["course"],
            "total": row["total"],
            "width": round(row["total"] / max_course_total * 100)
            if max_course_total
            else 0,
        }
        for row in raw_course_stats
    ]

    return {
        "total_students": total_students,
        "active_students": active_students,
        "inactive_students": inactive_students,
        "total_courses": total_courses,
        "total_teachers": total_teachers,
        "active_teachers": active_teachers,
        "inactive_teachers": inactive_teachers,
        "recent_students": recent_students,
        "course_stats": course_stats,
        "enrollment_stats": enrollment_stats,
    }


def get_student_filters(args):
    search = (args.get("q") or "").strip()[:100]
    status = args.get("status", "")
    if status not in ("Active", "Inactive"):
        status = ""

    course_value = args.get("course_id", "")
    course_id = int(course_value) if course_value.isdigit() else None

    conditions = []
    parameters = []
    if search:
        conditions.append("(students.name LIKE ? OR students.email LIKE ?)")
        wildcard_search = f"%{search}%"
        parameters.extend((wildcard_search, wildcard_search))
    if status:
        conditions.append("students.status = ?")
        parameters.append(status)
    if course_id is not None:
        conditions.append("students.course_id = ?")
        parameters.append(course_id)

    where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""
    return search, status, course_id, where_clause, parameters


def validate_student_form():
    form_data = {
        "name": request.form.get("name", "").strip(),
        "email": request.form.get("email", "").strip(),
        "phone": request.form.get("phone", "").strip(),
        "gender": request.form.get("gender", "").strip(),
        "course_id": request.form.get("course_id", "").strip(),
        "date_of_birth": request.form.get("date_of_birth", "").strip(),
        "enrollment_date": request.form.get("enrollment_date", "").strip(),
        "status": request.form.get("status", ""),
    }
    errors = []

    if not form_data["name"] or len(form_data["name"]) > 150:
        errors.append("Enter a name no longer than 150 characters.")
    if (
        not form_data["email"]
        or len(form_data["email"]) > 254
        or not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", form_data["email"])
    ):
        errors.append("Enter a valid email address.")
    if len(form_data["phone"]) > 30:
        errors.append("Phone number must be 30 characters or fewer.")
    if len(form_data["gender"]) > 50:
        errors.append("Gender must be 50 characters or fewer.")

    try:
        form_data["course_id"] = int(form_data["course_id"])
        if form_data["course_id"] < 1:
            raise ValueError
    except ValueError:
        form_data["course_id"] = None
        errors.append("Choose a valid course.")

    for field, label in (
        ("date_of_birth", "Date of birth"),
        ("enrollment_date", "Enrollment date"),
    ):
        value = form_data[field]
        if value:
            try:
                date.fromisoformat(value)
            except ValueError:
                errors.append(f"{label} must be a valid date.")
    if form_data["status"] not in ("Active", "Inactive"):
        errors.append("Choose a valid student status.")

    return form_data, errors


def render_student_form(form_data, errors, student=None):
    return render_template(
        "student_form.html",
        form_data=form_data,
        errors=errors,
        courses=get_courses(),
        editing=student is not None,
        student=student,
    )


def get_teacher_filters(args):
    search = (args.get("q") or "").strip()[:100]
    status = args.get("status", "")
    if status not in ("Active", "Inactive"):
        status = ""

    course_value = args.get("course_id", "")
    course_id = int(course_value) if course_value.isdigit() else None

    conditions = []
    parameters = []
    if search:
        conditions.append(
            "(teachers.name LIKE ? OR teachers.email LIKE ? OR teachers.phone LIKE ?)"
        )
        wildcard_search = f"%{search}%"
        parameters.extend((wildcard_search, wildcard_search, wildcard_search))
    if status:
        conditions.append("teachers.status = ?")
        parameters.append(status)
    if course_id is not None:
        conditions.append("teachers.course_id = ?")
        parameters.append(course_id)

    where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""
    return search, status, course_id, where_clause, parameters


def validate_teacher_form():
    form_data = {
        "name": request.form.get("name", "").strip(),
        "email": request.form.get("email", "").strip(),
        "phone": request.form.get("phone", "").strip(),
        "course_id": request.form.get("course_id", "").strip(),
        "qualification": request.form.get("qualification", "").strip(),
        "hire_date": request.form.get("hire_date", "").strip(),
        "status": request.form.get("status", ""),
    }
    errors = []

    if not form_data["name"] or len(form_data["name"]) > 150:
        errors.append("Enter a name no longer than 150 characters.")
    if (
        not form_data["email"]
        or len(form_data["email"]) > 254
        or not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", form_data["email"])
    ):
        errors.append("Enter a valid email address.")
    if len(form_data["phone"]) > 30:
        errors.append("Phone number must be 30 characters or fewer.")
    if len(form_data["qualification"]) > 150:
        errors.append("Qualification must be 150 characters or fewer.")

    try:
        form_data["course_id"] = int(form_data["course_id"])
        if form_data["course_id"] < 1:
            raise ValueError
    except ValueError:
        form_data["course_id"] = None
        errors.append("Choose a valid course or department.")

    try:
        date.fromisoformat(form_data["hire_date"])
    except ValueError:
        errors.append("Hire date must be a valid date.")
    if form_data["status"] not in ("Active", "Inactive"):
        errors.append("Choose a valid teacher status.")

    return form_data, errors


def render_teacher_form(form_data, errors, teacher=None):
    return render_template(
        "teacher_form.html",
        form_data=form_data,
        errors=errors,
        courses=get_courses(),
        editing=teacher is not None,
        teacher=teacher,
    )


@app.route("/")
@login_required
def home():
    return render_template("index.html", **get_dashboard_data())


@app.route("/students")
@login_required
def students():
    search, status, course_id, where_clause, parameters = get_student_filters(
        request.args
    )
    page = max(request.args.get("page", 1, type=int) or 1, 1)
    per_page = 10

    with database_connection() as connection:
        total = connection.execute(
            f"""
            SELECT COUNT(*)
            FROM students
            INNER JOIN courses ON students.course_id = courses.id
            {where_clause}
            """,
            parameters,
        ).fetchone()[0]

        total_pages = max(1, (total + per_page - 1) // per_page)
        page = min(page, total_pages)
        student_list = connection.execute(
            f"""
            SELECT
                students.id,
                students.name,
                students.email,
                students.status,
                courses.name AS course
            FROM students
            INNER JOIN courses ON students.course_id = courses.id
            {where_clause}
            ORDER BY students.name COLLATE NOCASE, students.id
            LIMIT ? OFFSET ?
            """,
            [*parameters, per_page, (page - 1) * per_page],
        ).fetchall()

    return render_template(
        "students.html",
        students=student_list,
        courses=get_courses(),
        search=search,
        status_filter=status,
        course_filter=course_id,
        page=page,
        total_pages=total_pages,
        total=total,
    )


@app.route("/api/students")
def students_api():
    if "admin_id" not in session:
        return jsonify(error="Authentication required."), 401

    search, status, course_id, where_clause, parameters = get_student_filters(
        request.args
    )
    page = max(request.args.get("page", 1, type=int) or 1, 1)
    per_page = 10

    with database_connection() as connection:
        total = connection.execute(
            f"""
            SELECT COUNT(*)
            FROM students
            INNER JOIN courses ON students.course_id = courses.id
            {where_clause}
            """,
            parameters,
        ).fetchone()[0]

        total_pages = max(1, (total + per_page - 1) // per_page)
        page = min(page, total_pages)
        student_list = connection.execute(
            f"""
            SELECT
                students.id,
                students.name,
                students.email,
                students.status,
                courses.name AS course
            FROM students
            INNER JOIN courses ON students.course_id = courses.id
            {where_clause}
            ORDER BY students.name COLLATE NOCASE, students.id
            LIMIT ? OFFSET ?
            """,
            [*parameters, per_page, (page - 1) * per_page],
        ).fetchall()

    return jsonify(
        students=[dict(student) for student in student_list],
        pagination={
            "page": page,
            "per_page": per_page,
            "total": total,
            "total_pages": total_pages,
        },
    )


@app.route("/teachers")
@login_required
def teachers():
    search, status, course_id, where_clause, parameters = get_teacher_filters(
        request.args
    )
    page = max(request.args.get("page", 1, type=int) or 1, 1)
    per_page = 10

    with database_connection() as connection:
        total = connection.execute(
            f"""
            SELECT COUNT(*)
            FROM teachers
            INNER JOIN courses ON teachers.course_id = courses.id
            {where_clause}
            """,
            parameters,
        ).fetchone()[0]

        total_pages = max(1, (total + per_page - 1) // per_page)
        page = min(page, total_pages)
        teacher_list = connection.execute(
            f"""
            SELECT teachers.id, teachers.name, teachers.email, teachers.status,
                   courses.name AS course
            FROM teachers
            INNER JOIN courses ON teachers.course_id = courses.id
            {where_clause}
            ORDER BY teachers.name COLLATE NOCASE, teachers.id
            LIMIT ? OFFSET ?
            """,
            [*parameters, per_page, (page - 1) * per_page],
        ).fetchall()

    return render_template(
        "teachers.html",
        teachers=teacher_list,
        courses=get_courses(),
        search=search,
        status_filter=status,
        course_filter=course_id,
        page=page,
        total_pages=total_pages,
        total=total,
    )


@app.route("/teachers/new", methods=("GET", "POST"))
@login_required
def create_teacher():
    form_data = {
        "name": "",
        "email": "",
        "phone": "",
        "course_id": "",
        "qualification": "",
        "hire_date": date.today().isoformat(),
        "status": "Active",
    }
    if request.method == "POST":
        form_data, errors = validate_teacher_form()
        if not errors:
            with database_connection() as connection:
                if not connection.execute(
                    "SELECT 1 FROM courses WHERE id = ?", (form_data["course_id"],)
                ).fetchone():
                    errors.append("Choose a valid course or department.")
                else:
                    try:
                        connection.execute(
                            """
                            INSERT INTO teachers
                                (name, email, phone, course_id, qualification,
                                 hire_date, status)
                            VALUES (?, ?, ?, ?, ?, ?, ?)
                            """,
                            (
                                form_data["name"],
                                form_data["email"],
                                form_data["phone"] or None,
                                form_data["course_id"],
                                form_data["qualification"] or None,
                                form_data["hire_date"],
                                form_data["status"],
                            ),
                        )
                        connection.commit()
                    except sqlite3.IntegrityError:
                        errors.append("A teacher with that email address already exists.")
                    else:
                        flash("Teacher added successfully.", "success")
                        return redirect(url_for("teachers"))
    else:
        errors = []

    return render_teacher_form(form_data, errors)


@app.route("/teachers/<int:teacher_id>")
@login_required
def teacher_detail(teacher_id):
    with database_connection() as connection:
        teacher = connection.execute(
            """
            SELECT teachers.*, courses.name AS course
            FROM teachers
            INNER JOIN courses ON teachers.course_id = courses.id
            WHERE teachers.id = ?
            """,
            (teacher_id,),
        ).fetchone()
    if teacher is None:
        abort(404)
    return render_template("teacher_detail.html", teacher=teacher)


@app.route("/teachers/<int:teacher_id>/edit", methods=("GET", "POST"))
@login_required
def edit_teacher(teacher_id):
    with database_connection() as connection:
        teacher = connection.execute(
            "SELECT * FROM teachers WHERE id = ?", (teacher_id,)
        ).fetchone()
    if teacher is None:
        abort(404)

    form_data = {
        key: teacher[key] or ""
        for key in (
            "name",
            "email",
            "phone",
            "course_id",
            "qualification",
            "hire_date",
            "status",
        )
    }
    if request.method == "POST":
        form_data, errors = validate_teacher_form()
        if not errors:
            with database_connection() as connection:
                if not connection.execute(
                    "SELECT 1 FROM courses WHERE id = ?", (form_data["course_id"],)
                ).fetchone():
                    errors.append("Choose a valid course or department.")
                else:
                    try:
                        connection.execute(
                            """
                            UPDATE teachers
                            SET name = ?, email = ?, phone = ?, course_id = ?,
                                qualification = ?, hire_date = ?, status = ?
                            WHERE id = ?
                            """,
                            (
                                form_data["name"],
                                form_data["email"],
                                form_data["phone"] or None,
                                form_data["course_id"],
                                form_data["qualification"] or None,
                                form_data["hire_date"],
                                form_data["status"],
                                teacher_id,
                            ),
                        )
                        connection.commit()
                    except sqlite3.IntegrityError:
                        errors.append("A teacher with that email address already exists.")
                    else:
                        flash("Teacher details updated.", "success")
                        return redirect(url_for("teacher_detail", teacher_id=teacher_id))
    else:
        errors = []

    return render_teacher_form(form_data, errors, teacher)


@app.route("/teachers/<int:teacher_id>/delete", methods=("POST",))
@login_required
def delete_teacher(teacher_id):
    try:
        with database_connection() as connection:
            cursor = connection.execute(
                "DELETE FROM teachers WHERE id = ?", (teacher_id,)
            )
            connection.commit()
    except sqlite3.IntegrityError:
        flash("This teacher has timetable entries. Remove those entries first.", "error")
        return redirect(url_for("teacher_detail", teacher_id=teacher_id))
    if cursor.rowcount:
        flash("Teacher deleted.", "success")
    else:
        flash("That teacher no longer exists.", "error")
    return redirect(url_for("teachers"))


@app.route("/teachers/export.csv")
@login_required
def export_teachers():
    _, _, _, where_clause, parameters = get_teacher_filters(request.args)
    with database_connection() as connection:
        records = connection.execute(
            f"""
            SELECT teachers.id, teachers.name, teachers.email, teachers.phone,
                   courses.name AS course, teachers.qualification,
                   teachers.hire_date, teachers.status
            FROM teachers
            INNER JOIN courses ON teachers.course_id = courses.id
            {where_clause}
            ORDER BY teachers.name COLLATE NOCASE, teachers.id
            """,
            parameters,
        ).fetchall()

    output = io.StringIO(newline="")
    writer = csv.writer(output)
    writer.writerow(
        ("ID", "Name", "Email", "Phone", "Course / department",
         "Qualification", "Hire date", "Status")
    )
    for record in records:
        values = []
        for value in record:
            if isinstance(value, str) and value.lstrip(" \t\r\n").startswith(
                ("=", "+", "-", "@")
            ):
                value = "'" + value
            values.append(value)
        writer.writerow(values)

    response = make_response("\ufeff" + output.getvalue())
    response.headers["Content-Type"] = "text/csv; charset=utf-8"
    response.headers["Content-Disposition"] = "attachment; filename=teachers.csv"
    return response


@app.route("/timetable", methods=("GET", "POST"))
@login_required
def timetable():
    courses = get_courses()
    course_id = request.args.get("course_id", type=int)
    course_ids = {course["id"] for course in courses}
    if course_id not in course_ids:
        course_id = courses[0]["id"] if courses else None

    if request.method == "POST":
        form = {
            "course_id": request.form.get("course_id", ""),
            "teacher_id": request.form.get("teacher_id", ""),
            "subject": request.form.get("subject", "").strip(),
            "weekday": request.form.get("weekday", ""),
            "period": request.form.get("period", ""),
        }
        errors = []
        try:
            form["course_id"] = int(form["course_id"])
            if form["course_id"] not in course_ids:
                raise ValueError
        except ValueError:
            errors.append("Choose a valid course.")
        try:
            form["teacher_id"] = int(form["teacher_id"])
        except ValueError:
            form["teacher_id"] = None
            errors.append("Choose a valid teacher.")
        if not form["subject"] or len(form["subject"]) > 120:
            errors.append("Enter a subject no longer than 120 characters.")
        if form["weekday"] not in WEEKDAYS:
            errors.append("Choose a valid weekday.")
        try:
            form["period"] = int(form["period"])
            if form["period"] not in range(1, len(PERIODS) + 1):
                raise ValueError
        except ValueError:
            form["period"] = None
            errors.append("Choose a valid period.")

        if not errors:
            with database_connection() as connection:
                teacher = connection.execute(
                    "SELECT status FROM teachers WHERE id = ?", (form["teacher_id"],)
                ).fetchone()
                if teacher is None or teacher["status"] != "Active":
                    errors.append("Choose an active teacher.")
                if connection.execute(
                    """
                    SELECT 1 FROM timetable
                    WHERE course_id = ? AND weekday = ? AND period = ?
                    """,
                    (form["course_id"], form["weekday"], form["period"]),
                ).fetchone():
                    errors.append("This course already has a lecture in that period.")
                if connection.execute(
                    """
                    SELECT 1 FROM timetable
                    WHERE teacher_id = ? AND weekday = ? AND period = ?
                    """,
                    (form["teacher_id"], form["weekday"], form["period"]),
                ).fetchone():
                    errors.append("That teacher is already teaching in that period.")
                if not errors:
                    try:
                        connection.execute(
                            """
                            INSERT INTO timetable
                                (course_id, teacher_id, subject, weekday, period)
                            VALUES (?, ?, ?, ?, ?)
                            """,
                            (
                                form["course_id"],
                                form["teacher_id"],
                                form["subject"],
                                form["weekday"],
                                form["period"],
                            ),
                        )
                        connection.commit()
                    except sqlite3.IntegrityError:
                        errors.append(
                            "The course or teacher was booked in this period by another request."
                        )
                    else:
                        flash("Lecture added to the timetable.", "success")
                        return redirect(
                            url_for("timetable", course_id=form["course_id"])
                        )
        for error in errors:
            flash(error, "error")
        return redirect(url_for("timetable", course_id=form["course_id"] or course_id))

    schedule_rows = []
    active_teachers = []
    if course_id is not None:
        with database_connection() as connection:
            schedule_rows = connection.execute(
                """
                SELECT timetable.id, timetable.subject, timetable.weekday,
                       timetable.period, teachers.name AS teacher,
                       teachers.status AS teacher_status
                FROM timetable
                INNER JOIN teachers ON teachers.id = timetable.teacher_id
                WHERE timetable.course_id = ?
                """,
                (course_id,),
            ).fetchall()
            active_teachers = connection.execute(
                """
                SELECT id, name FROM teachers
                WHERE status = 'Active'
                ORDER BY name COLLATE NOCASE
                """
            ).fetchall()

    schedule = {
        (row["weekday"], row["period"]): row for row in schedule_rows
    }
    return render_template(
        "timetable.html",
        courses=courses,
        course_id=course_id,
        periods=PERIODS,
        weekdays=WEEKDAYS,
        schedule=schedule,
        teachers=active_teachers,
    )


@app.route("/timetable/<int:entry_id>/delete", methods=("POST",))
@login_required
def delete_timetable_entry(entry_id):
    with database_connection() as connection:
        entry = connection.execute(
            "SELECT course_id FROM timetable WHERE id = ?", (entry_id,)
        ).fetchone()
        if entry is None:
            flash("That timetable entry no longer exists.", "error")
            return redirect(url_for("timetable"))
        connection.execute("DELETE FROM timetable WHERE id = ?", (entry_id,))
        connection.commit()
    flash("Lecture removed from the timetable.", "success")
    return redirect(url_for("timetable", course_id=entry["course_id"]))


@app.route("/students/new", methods=("GET", "POST"))
@login_required
def create_student():
    form_data = {
        "name": "",
        "email": "",
        "phone": "",
        "gender": "",
        "course_id": "",
        "date_of_birth": "",
        "enrollment_date": date.today().isoformat(),
        "status": "Active",
    }
    if request.method == "POST":
        form_data, errors = validate_student_form()
        if not errors:
            with database_connection() as connection:
                if not connection.execute(
                    "SELECT 1 FROM courses WHERE id = ?", (form_data["course_id"],)
                ).fetchone():
                    errors.append("Choose a valid course.")
                else:
                    try:
                        connection.execute(
                            """
                            INSERT INTO students
                                (name, email, phone, gender, course_id,
                                 date_of_birth, enrollment_date, status)
                            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                            """,
                            (
                                form_data["name"],
                                form_data["email"],
                                form_data["phone"] or None,
                                form_data["gender"] or None,
                                form_data["course_id"],
                                form_data["date_of_birth"] or None,
                                form_data["enrollment_date"] or date.today().isoformat(),
                                form_data["status"],
                            ),
                        )
                        connection.commit()
                    except sqlite3.IntegrityError:
                        errors.append("A student with that email address already exists.")
                    else:
                        flash("Student added successfully.", "success")
                        return redirect(url_for("students"))
    else:
        errors = []

    return render_student_form(form_data, errors)


@app.route("/students/<int:student_id>")
@login_required
def student_detail(student_id):
    with database_connection() as connection:
        student = connection.execute(
            """
            SELECT students.*, courses.name AS course
            FROM students
            INNER JOIN courses ON students.course_id = courses.id
            WHERE students.id = ?
            """,
            (student_id,),
        ).fetchone()
    if student is None:
        abort(404)
    return render_template("student_detail.html", student=student)


@app.route("/students/<int:student_id>/edit", methods=("GET", "POST"))
@login_required
def edit_student(student_id):
    with database_connection() as connection:
        student = connection.execute(
            "SELECT * FROM students WHERE id = ?", (student_id,)
        ).fetchone()
    if student is None:
        abort(404)

    form_data = {
        key: student[key] or ""
        for key in (
            "name",
            "email",
            "phone",
            "gender",
            "course_id",
            "date_of_birth",
            "enrollment_date",
            "status",
        )
    }
    if request.method == "POST":
        form_data, errors = validate_student_form()
        if not errors:
            with database_connection() as connection:
                if not connection.execute(
                    "SELECT 1 FROM courses WHERE id = ?", (form_data["course_id"],)
                ).fetchone():
                    errors.append("Choose a valid course.")
                else:
                    try:
                        connection.execute(
                            """
                            UPDATE students
                            SET name = ?, email = ?, phone = ?, gender = ?,
                                course_id = ?, date_of_birth = ?,
                                enrollment_date = ?, status = ?
                            WHERE id = ?
                            """,
                            (
                                form_data["name"],
                                form_data["email"],
                                form_data["phone"] or None,
                                form_data["gender"] or None,
                                form_data["course_id"],
                                form_data["date_of_birth"] or None,
                                form_data["enrollment_date"] or date.today().isoformat(),
                                form_data["status"],
                                student_id,
                            ),
                        )
                        connection.commit()
                    except sqlite3.IntegrityError:
                        errors.append("A student with that email address already exists.")
                    else:
                        flash("Student details updated.", "success")
                        return redirect(url_for("student_detail", student_id=student_id))
    else:
        errors = []

    return render_student_form(form_data, errors, student)


@app.route("/students/<int:student_id>/delete", methods=("POST",))
@login_required
def delete_student(student_id):
    with database_connection() as connection:
        cursor = connection.execute("DELETE FROM students WHERE id = ?", (student_id,))
        connection.commit()
    if cursor.rowcount:
        flash("Student deleted.", "success")
    else:
        flash("That student no longer exists.", "error")
    return redirect(url_for("students"))


@app.route("/students/export.csv")
@login_required
def export_students():
    _, _, _, where_clause, parameters = get_student_filters(request.args)
    with database_connection() as connection:
        records = connection.execute(
            f"""
            SELECT students.id, students.name, students.email, students.phone,
                   students.gender, courses.name AS course,
                   students.date_of_birth, students.enrollment_date, students.status
            FROM students
            INNER JOIN courses ON students.course_id = courses.id
            {where_clause}
            ORDER BY students.name COLLATE NOCASE, students.id
            """,
            parameters,
        ).fetchall()

    output = io.StringIO(newline="")
    writer = csv.writer(output)
    writer.writerow(
        (
            "ID",
            "Name",
            "Email",
            "Phone",
            "Gender",
            "Course",
            "Date of birth",
            "Enrollment date",
            "Status",
        )
    )
    for record in records:
        values = [record[key] for key in record.keys()]
        safe_values = []
        for value in values:
            if isinstance(value, str) and value.lstrip(" \t\r\n").startswith(
                ("=", "+", "-", "@")
            ):
                value = "'" + value
            safe_values.append(value)
        writer.writerow(safe_values)

    response = make_response("\ufeff" + output.getvalue())
    response.headers["Content-Type"] = "text/csv; charset=utf-8"
    response.headers["Content-Disposition"] = "attachment; filename=students.csv"
    return response


@app.route("/about")
def about():
    return render_template("about.html")


@app.route("/dashboard")
@login_required
def dashboard():
    return render_template("dashboard.html", **get_dashboard_data())


@app.route("/setup", methods=("GET", "POST"))
def setup():
    if has_admin_account():
        return redirect(url_for("login"))

    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        confirm_password = request.form.get("confirm_password", "")
        errors = []
        if not username or len(username) > 80:
            errors.append("Enter a username no longer than 80 characters.")
        if len(password) < 12:
            errors.append("Choose a password with at least 12 characters.")
        if password != confirm_password:
            errors.append("The passwords do not match.")

        if not errors:
            with database_connection() as connection:
                try:
                    connection.execute("BEGIN IMMEDIATE")
                    if connection.execute("SELECT 1 FROM admins LIMIT 1").fetchone():
                        connection.rollback()
                        return redirect(url_for("login"))
                    connection.execute(
                        "INSERT INTO admins (username, password_hash) VALUES (?, ?)",
                        (username, generate_password_hash(password)),
                    )
                    connection.commit()
                except sqlite3.IntegrityError:
                    connection.rollback()
                    errors.append("That username is already in use.")
                else:
                    session.clear()
                    session["admin_id"] = connection.execute(
                        "SELECT id FROM admins WHERE username = ?", (username,)
                    ).fetchone()["id"]
                    session["admin_username"] = username
                    flash("Admin account created. You are now signed in.", "success")
                    return redirect(url_for("dashboard"))
    else:
        errors = []

    return render_template("setup.html", errors=errors)


@app.route("/login", methods=("GET", "POST"))
def login():
    if has_admin_account() is False:
        return redirect(url_for("setup"))
    if "admin_id" in session:
        return redirect(url_for("dashboard"))

    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        with database_connection() as connection:
            admin = connection.execute(
                "SELECT id, username, password_hash FROM admins WHERE username = ?",
                (username,),
            ).fetchone()
        if admin is None or not check_password_hash(admin["password_hash"], password):
            flash("Invalid username or password.", "error")
        else:
            session.clear()
            session["admin_id"] = admin["id"]
            session["admin_username"] = admin["username"]
            flash("Signed in successfully.", "success")
            return redirect(url_for("dashboard"))

    return render_template("login.html")


@app.route("/logout", methods=("POST",))
def logout():
    session.clear()
    flash("You have been signed out.", "success")
    return redirect(url_for("login"))


if __name__ == "__main__":
    app.run(debug=True)
